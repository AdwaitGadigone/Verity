"""
gemini_client.py — Shared Gemini API Helper (used by all 6 criterion files)
============================================================================

WHAT IS THIS FILE?
This file creates ONE shared connection to Google's Gemini AI. Instead of
each criterion file setting up its own connection (messy and repetitive),
they all just call `call_gemini("your question here")` from this file.

WHAT IS GEMINI?
Gemini is Google's AI model (like ChatGPT but made by Google). We send it
a text prompt (a question) and it sends back an answer. We use it to analyze
articles for emotional tone, factual accuracy, and more.

WHAT IS AN API?
API = Application Programming Interface. It's how two programs talk to each
other over the internet. We send a request to Google's servers, and they
send back a response. The API key is like a password that proves we're
allowed to use the service.

WHAT IS JSON?
JSON = JavaScript Object Notation. It's a standard format for sending data
between programs. It looks like a Python dictionary:
  {"score": 85, "reason": "This article is mostly factual"}

We force Gemini to respond in JSON so we can easily extract the score and
reason from its answer.

HOW TO USE THIS FILE:
    from gemini_client import call_gemini

    result = call_gemini("Is this article factual? ...")
    # result will be a Python dict like {"score": 85, "reason": "..."}
    # or None if something went wrong
"""

import os
import json

# python-dotenv lets us read API keys from a .env file
# instead of hardcoding them into the source code
from dotenv import load_dotenv

# This reads the .env file and puts the values into environment variables
# so we can access them with os.getenv()
load_dotenv()

# ── Set up Multiple Gemini Clients (for rate limit bypass) ───────────────────
# We search the .env file for ALL variables starting with "GEMINI_API_KEY"
# (e.g., GEMINI_API_KEY_1, GEMINI_API_KEY_2). This allows us to cycle through
# multiple keys to bypass the free-tier quota limits during the hackathon.
_api_keys = []
for key, value in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and value.strip():
        _api_keys.append(value.strip())

# Fallback if the user simply has exactly "GEMINI_API_KEY"
fallback_key = os.getenv("GEMINI_API_KEY")
if not _api_keys and fallback_key:
    _api_keys.append(fallback_key)

_clients = []
_current_client_idx = 0

try:
    from google import genai
    from google.genai import types as genai_types

    # Create a client connection for EACH valid key we found
    for key in _api_keys:
        _clients.append(genai.Client(api_key=key))
        
    if not _clients:
        print("[WARNING] No Gemini API keys found in .env file.")
except ImportError:
    print("[WARNING] google-genai not installed. Run: pip install google-genai")


def call_gemini(prompt: str, model: str = "gemini-2.0-flash") -> dict | None:
    """
    Sends a question (prompt) to Google Gemini and returns the answer as
    a Python dictionary.

    This is the ONLY function the rest of the app needs to call for AI analysis.

    Parameters:
        prompt (str): The full question/instruction to send to Gemini
        model (str):  Which Gemini model to use (default: gemini-2.0-flash,
                      which is fast and free-tier friendly)

    Returns:
        A Python dict with Gemini's answer (parsed from JSON), for example:
          {"score": 85, "reason": "The article cites multiple credible sources"}
        OR None if something went wrong (network error, API limit, etc.)

    Why we return None on failure instead of crashing:
        During the hackathon demo, we can't have the whole app crash just
        because one API call failed. If Gemini is down or slow, the rest
        of the analysis still works — that criterion just gets a neutral score.
    """
    # If we don't have ANY working clients, return None (no crash)
    if not _clients:
        return None

    global _current_client_idx

    # We use a loop so if one key fails with a quota limit, we try the next.
    # We will try EXACTLY the number of keys we have before giving up.
    for attempt in range(len(_clients)):
        client = _clients[_current_client_idx]
        try:
            # Send the prompt to Gemini
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=512,
                ),
            )

            # Parse the JSON text into a Python dictionary
            return json.loads(response.text)

        except json.JSONDecodeError:
            # Gemini returned something that wasn't valid JSON, not a quota issue
            return None
        except Exception as e:
            error_msg = str(e).lower()
            # Check if this error is a 429 Resource Exhausted (quota hit)
            if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                print(f"[Gemini Quota] API Key #{_current_client_idx + 1} exhausted. Switching to next key...")
                _current_client_idx = (_current_client_idx + 1) % len(_clients)
                # Loop continues and tries again with the new client
                continue
            else:
                # Any other weird error (network failure, etc.)
                print(f"[Gemini error] {e}")
                return None

    # If the loop fully finishes, it means ALL our keys are exhausted
    print("[Gemini error] ALL provided API keys have exhausted their free-tier quotas.")
    return None


def gemini_final_score(criteria_results: dict, domain: str, article_text: str = "") -> dict | None:
    """
    Sends the 6 criteria results to Gemini and asks it to determine the FINAL overall credibility score.
    Returns a dictionary with 'final_score' (0-100) and 'verdict_subtext'.
    """
    if not _clients:
        return None

    global _current_client_idx

    # Format the criteria summary for the prompt
    summary = ""
    for k, v in criteria_results.items():
        summary += f"- {k.title()} Score: {v.get('score')}/100. Reason: {v.get('reason')}\n"

    prompt = f"""
    You are the final judge for a Canadian misinformation detection tool called Verity.
    Your job is to look at the scores from 6 automated criteria and determine the final overall credibility score (0-100).

    DOMAIN: {domain}
    CRITERIA RESULTS:
    {summary}

    Given these 6 factors, what is the TRUE overall credibility of this source/content?
    For official government domains (like .gc.ca, canada.ca) or established major news outlets, the final score should reflect their high institutional credibility, even if technical criteria like "Author name" scored lower (since institutions often don't use personal bylines).
    For random blogs or fake news sites, the score should reflect the danger.

    CRITICAL INSTRUCTION: In your `verdict_subtext`, you MUST clearly state the **TYPE** of content this is (e.g., "This is an opinion piece", "This is a movie review", "This is objective news reporting", "This is satire") as part of your brief justification for the score.

    Respond ONLY in valid JSON format exactly like this:
    {{
      "final_score": 85,
      "verdict_subtext": "This is objective news reporting from an official Canadian government source with high institutional credibility."
    }}
    """

    for attempt in range(len(_clients)):
        client = _clients[_current_client_idx]
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=1024,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                print(f"[Gemini Quota] Final Score API Key #{_current_client_idx + 1} exhausted. Switching keys...")
                _current_client_idx = (_current_client_idx + 1) % len(_clients)
                continue
            else:
                print(f"[Gemini final score error] {e}")
                return None
    
    print("[Gemini error] ALL API keys exhausted. Final score calculation failing over to fallback math.")
    return None
