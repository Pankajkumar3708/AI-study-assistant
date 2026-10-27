"""Run this first to check your key, model and internet, without any window.

    python check_setup.py
"""
import os
import sys

from google import genai
from google.genai import types

key = os.environ.get("GEMINI_API_KEY")
print("Key found in this terminal:", bool(key))
if not key:
    sys.exit("GEMINI_API_KEY is not set in THIS terminal. Set it again here.")

model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000))
try:
    print("Model:", model)
    print("Reply:", client.models.generate_content(model=model, contents="Say hello in 5 words.").text)
except Exception as e:
    print("FAILED:", repr(e))
    print("\nModels your key can use:")
    try:
        for m in client.models.list():
            print(" ", m.name)
    except Exception as e2:
        print("Could not list models:", repr(e2))
