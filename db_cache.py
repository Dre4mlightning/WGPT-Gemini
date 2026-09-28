import time
from pymongo import MongoClient

# --- MongoDB Setup ---
try:
    mongo_client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=1000)
    db = mongo_client["weathergpt"]
    telemetry_collection = db["telemetry_cache"]
except Exception:
    mongo_client = None
    telemetry_collection = None

CACHE_TTL_SECONDS = 900  # 15 minutes

def get_cached_telemetry(district: str):
    """Fetches telemetry from MongoDB if within TTL."""
    if telemetry_collection is None:
        return None
    try:
        doc = telemetry_collection.find_one({"district": district.lower()})
        if doc and (time.time() - doc.get("timestamp", 0) < CACHE_TTL_SECONDS):
            return doc.get("data")
    except Exception:
        pass
    return None

def set_cached_telemetry(district: str, data: dict):
    """Saves telemetry to MongoDB with timestamp."""
    if telemetry_collection is None:
        return
    try:
        telemetry_collection.update_one(
            {"district": district.lower()},
            {"$set": {"data": data, "timestamp": time.time()}},
            upsert=True
        )
    except Exception:
        pass