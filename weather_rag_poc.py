import os
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not api_key:
    # If the key is missing from Render's environment, this prevents the SDK from falling back to OAuth
    raise ValueError("GEMINI_API_KEY is not configured in the environment variables.")

client = genai.Client(api_key=api_key)

TELEMETRY_CACHE = {}
COORDS_CACHE = {}
CACHE_TTL = 900

ALIASES = {
    "calcutta": "kolkata",
    "bombay": "mumbai",
    "madras": "chennai",
    "bengaluru": "bangalore",
    "banaras": "varanasi",
    "orissa": "odisha",
    "barabati": "cuttack",
    "vizag": "visakhapatnam"
}

PERSONA_RULES = {
    "general": (
        "Focus on general public safety, traffic and road transport delays, urban waterlogging, "
        "and daily outdoor commute safety. Provide clear precautionary advice."
    ),
    "farmers": (
        "Focus on agricultural decisions: soil saturation, harvest/sowing schedules, "
        "pesticide spraying feasibility, standing crop protection, and irrigation advice."
    ),
    "marines": (
        "Focus on marine and fisheries safety: squall warnings, gust conditions, wave swells, "
        "and explicit advice on whether fishermen should avoid venturing into the sea or return to shore."
    ),
    "aviators": (
        "Focus on aviation and drone flight envelopes: cloud ceiling, surface wind gusts, visibility, "
        "and drone operation compliance (VFR limits, wind speed > 25 km/h warnings)."
    )
}

def geocode_place_india(place_name: str):
    key = place_name.lower().strip()
    key = ALIASES.get(key, key)

    if key in COORDS_CACHE:
        return COORDS_CACHE[key]

    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(key)}&count=1&language=en&format=json&country_code=IN"
        res = requests.get(geo_url, timeout=3.0).json()
        results = res.get("results")
        if results and len(results) > 0:
            match = results[0]
            lat = match.get("latitude")
            lon = match.get("longitude")
            admin1 = match.get("admin1", "")
            resolved = {
                "name": match.get("name", place_name).title(),
                "state": admin1,
                "lat": lat,
                "lon": lon
            }
            COORDS_CACHE[key] = resolved
            return resolved
    except Exception as e:
        print(f"Geocoding Error for {place_name}: {e}")

    return None

def resolve_district_telemetry(place_name: str):
    """Fetches real-time weather and live air quality (AQI, PM2.5, PM10) for any Indian location."""
    key = place_name.lower().strip()
    key = ALIASES.get(key, key)

    # 1. Cache hit check
    item = TELEMETRY_CACHE.get(key)
    if item and (time.time() - item.get("timestamp", 0) < CACHE_TTL):
        return item.get("data")

    # 2. Geocode location coordinates
    geo = geocode_place_india(key)
    if not geo:
        return None

    try:
        lat, lon = geo["lat"], geo["lon"]
        
        # Weather Telemetry
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
        )
        w_res = requests.get(weather_url, timeout=2.5).json()
        w_data = w_res.get("current", {})

        # Live Air Quality Telemetry (Open-Meteo Air Quality API)
        aqi_url = (
            f"https://air-quality-api.open-meteo.com/v1/air-quality?"
            f"latitude={lat}&longitude={lon}&"
            f"current=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,us_aqi,european_aqi"
        )
        aqi_res = requests.get(aqi_url, timeout=2.5).json()
        aqi_data = aqi_res.get("current", {})

        combined_telemetry = {
            "weather": {
                "temperature_c": w_data.get("temperature_2m"),
                "relative_humidity_pct": w_data.get("relative_humidity_2m"),
                "precipitation_mm": w_data.get("precipitation"),
                "wind_speed_kmh": w_data.get("wind_speed_10m")
            },
            "air_quality": {
                "aqi_index": aqi_data.get("us_aqi"),
                "pm2_5_ug_m3": aqi_data.get("pm2_5"),
                "pm10_ug_m3": aqi_data.get("pm10"),
                "ozone_ug_m3": aqi_data.get("ozone"),
                "nitrogen_dioxide_ug_m3": aqi_data.get("nitrogen_dioxide")
            }
        }

        payload = {
            "location": f"{geo['name']}, {geo['state']}",
            "coordinates": (lat, lon),
            "telemetry": combined_telemetry
        }

        TELEMETRY_CACHE[key] = {"data": payload, "timestamp": time.time()}
        return payload
    except Exception as e:
        print(f"Telemetry Fetch Error: {e}")
        return None

def get_matching_bulletin(search_text: str) -> str:
    if not os.path.exists("bulletins.json"):
        return ""
    text_lower = search_text.lower()
    try:
        with open("bulletins.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            district = item.get("district", "").lower()
            if district and (district in text_lower or ALIASES.get(district, district) in text_lower):
                valid = f"Validity: {item.get('valid_from', '')} to {item.get('valid_until', '')}"
                return f"[OFFICIAL IMD BULLETIN FOR {district.upper()}]\n{valid}\n{item.get('text', '')}"
        return ""
    except Exception:
        return ""

def extract_potential_location(text: str) -> str:
    try:
        res = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=f"Extract only the primary Indian city, district, town, or place mentioned in this text. If none, reply NONE. Return only the single place name:\nText: {text}",
            config={"temperature": 0.0, "max_output_tokens": 15}
        )
        loc = res.text.strip()
        if loc and loc.upper() != "NONE" and len(loc) < 30:
            return loc
    except Exception:
        pass
    return ""

def run_weather_assistant(prompt: str, history: list = None, persona: str = "general") -> str:
    now_str = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
    target_persona = persona.lower().strip() if persona else "general"
    persona_rule = PERSONA_RULES.get(target_persona, PERSONA_RULES["general"])

    target_place = extract_potential_location(prompt)
    if not target_place and history:
        for turn in reversed(history[-2:]):
            content = turn.get("content") or turn.get("text") or ""
            target_place = extract_potential_location(content)
            if target_place:
                break

    telemetry_payload = resolve_district_telemetry(target_place) if target_place else None

    matched_bulletin = get_matching_bulletin(prompt)
    if not matched_bulletin and target_place:
        matched_bulletin = get_matching_bulletin(target_place)

    sys_instruction = (
        f"You are WeatherGPT, an authoritative decision-intelligence and disaster advisory engine for India.\n"
        f"CURRENT DATE AND TIME: {now_str}.\n"
        f"ACTIVE PERSONA: {target_persona.upper()}\n"
        f"PERSONA MANDATE: {persona_rule}\n\n"
        "RESPONSE STRUCTURE (Strictly enforce this 3-part layout):\n"
        "1. **DIRECT VERDICT**: State a clear, definitive operational decision in sentence 1:\n"
        "   - Use: **PROCEED (YES)**, **DO NOT PROCEED (NO)**, or **DELAY / WAIT 24-48 HOURS**.\n"
        "   - Give the single primary reason immediately.\n\n"
        "2. **ACTIONABLE CHECKLIST (Numbered 1-3)**:\n"
        "   - Give concrete physical actions the user must execute today/tomorrow.\n"
        "   - For Farmers: State drainage steps, sowing depth, or spray window hours.\n"
        "   - For Marine: State boat anchor security, distance limits from coast, or total recall.\n"
        "   - For Aviation: State permissible flight window, max wind gust limit, or altitude ceiling.\n"
        "   - For Civic: State route detour, peak risk hours, or mask requirements.\n\n"
        "3. **TELEMETRY THRESHOLDS**:\n"
        "   - Cite the exact metric that triggered this decision (e.g., 'Soil saturation risk due to 93% relative humidity', 'Wind gusts exceeding 35 km/h').\n\n"
        "STRICT CONSTRAINTS:\n"
        "- Never say 'it is up to you' or give vague generic advice.\n"
        "- Do not pad with textbook definitions of crops or weather.\n"
        "- Ground decisions strictly on the live telemetry and active IMD bulletins provided."
    )

    if matched_bulletin:
        sys_instruction += f"\n\nActive IMD Bulletin:\n{matched_bulletin}"
    if telemetry_payload:
        sys_instruction += f"\n\nLive Telemetry ({telemetry_payload['location']}): {json.dumps(telemetry_payload['telemetry'])}"

    contents = []
    if history:
        for turn in history[-4:]:
            role = "user" if turn.get("role") in ["user", "human"] else "model"
            txt = turn.get("content") or turn.get("text")
            if txt:
                contents.append({"role": role, "parts": [{"text": str(txt)}]})

    contents.append({"role": "user", "parts": [{"text": str(prompt)}]})

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=contents,
            config={
                "system_instruction": sys_instruction,
                "temperature": 0.2,
                "max_output_tokens": 450
            }
        )
        return response.text.strip() if response and response.text else "Advisory generated without text."
    except Exception as e:
        return f"Unable to process advisory: {str(e)}"