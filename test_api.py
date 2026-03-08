import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()
_api_keys = []
for key, value in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and value.strip():
        _api_keys.append(value.strip())

if not _api_keys and os.getenv("GEMINI_API_KEY"):
    _api_keys.append(os.getenv("GEMINI_API_KEY"))

print(f"Loaded {len(_api_keys)} API keys.")

if _api_keys:
    for i, _api_key in enumerate(_api_keys):
        print(f"\\n--- Testing API Key {i+1} ---")
        try:
            client = genai.Client(api_key=_api_key)
            prompt = """Return {"test": true}"""
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=2048,
                ),
            )
            print("SUCCESS:")
            print(response.text)
        except Exception as e:
            print("ERROR:", e)
