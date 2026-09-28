import requests

API_KEY = "AQ.Ab8RN6J5hxtudAhpyAY3vLbBT6C2pf7Ro1tUqy522nOVbH6uDA"

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
headers = {
    "x-goog-api-key": API_KEY,
    "Content-Type": "application/json"
}
payload = {
    "contents": [{"parts": [{"text": "Hello, verify API connection."}]}]
}

res = requests.post(url, headers=headers, json=payload)
print("Status Code:", res.status_code)
print("Response:", res.text)