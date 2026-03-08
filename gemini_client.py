"""
gemini_client.py — Shared Gemini API Helper (used by all 6 criterion files)
============================================================================

WHAT IS THIS FILE?
This file creates ONE shared connection to Google's Gemini AI. Instead of
each criterion file setting up its own connection (messy and repetitive),
they all just call `call_gemini("your question here")` from this file.

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
import hashlib

# python-dotenv lets us read API keys from a .env file
# instead of hardcoding them into the source code
from dotenv import load_dotenv

# This reads the .env file and puts the values into environment variables
# so we can access them with os.getenv()
load_dotenv()

# ── Batch analysis cache ─────────────────────────────────────────────────────
# Stores one-shot batch Gemini results keyed by md5 of article content.
# This means criteria 2, 4, 5, 6 all read from this dict instead of each
# making a separate Gemini call — cutting 4 calls down to 1.
_batch_cache: dict = {}


def prime_mega_cache(article_text: str, title: str, author_name: str) -> bool:
    """
    Makes ONE Gemini call that covers ALL AI-analysis for criteria 2-6 AND
    produces the final score — replacing what was previously 5 separate calls.

    Covers:
      - Criteria 2 (emotional), 4 (author), 5 (content), 6 (MDM)
      - Criterion 3 (factual): claim extraction + verification + extraordinary test
      - Final credibility score + verdict subtext

    Call this from scorer.py once before running any criteria.
    Returns True if the cache was successfully populated.
    """
    cache_key = hashlib.md5((article_text[:3000] + title).encode()).hexdigest()
    if cache_key in _batch_cache:
        return True  # Same content already analyzed

    sample = f"HEADLINE: {title}\n\nARTICLE (first 2500 chars):\n{article_text[:2500]}"
    author_info = f'Author: "{author_name}"' if author_name else "No named author."

    prompt = f"""You are an expert Canadian misinformation analyst using the ITSAP.00.300 framework from the Canadian Centre for Cyber Security. Analyze the article below and return a single JSON object covering ALL criteria.

TRUSTED CANADIAN SOURCES (score these highly — they are institutional, credible outlets):
- Government: canada.ca, gc.ca, cyber.gc.ca, statcan.gc.ca, healthcanada.gc.ca, parl.gc.ca
- Public broadcasters: cbc.ca, radio-canada.ca
- Major newspapers: theglobeandmail.com, thestar.com, nationalpost.com, macleans.ca, globalnews.ca
- Wire services: reuters.com, apnews.com, afp.com
For these sources: emotional score should be 75+, author score 80+, MDM classification should be "Valid" unless there is explicit factual error.

MDM CLASSIFICATION GUIDE (ITSAP.00.300):
- Valid: Factually accurate reporting from a credible source, even if covering controversial topics
- Misinformation: Contains specific factual errors NOT intentional (e.g. wrong statistics cited)
- Malinformation: Factually true but framed to mislead or harm (e.g. selective quoting)
- Disinformation: Deliberately fabricated content designed to deceive
- Unsustainable: Claims that cannot be verified or disproved with available information
NOTE: War/conflict reporting from established outlets is typically "Valid" or "Unsustainable", NOT "Misinformation".

{author_info}
{sample}

UNDETERMINABLE CONTENT DETECTION:
Some content is inherently NOT verifiable for factual credibility. You MUST flag these as undeterminable by setting `is_undeterminable` to true:
- Pure opinion pieces, editorials, or personal blogs that are ENTIRELY subjective with no verifiable factual claims.
- Religious texts, sermons, theological arguments, spiritual teachings, faith-based claims (e.g. "God exists", "prayer heals").
- Personal essays, philosophical musings, or motivational content.
- Astrology, horoscopes, paranormal claims, or supernatural content.
- Poetry, fiction, creative writing presented as non-news content.
IMPORTANT RED ALERT: If the text is just someone giving their strong personal opinion (like "dogs are better than cats"), you MUST set `is_undeterminable` to true. Do not attempt to score opinion pieces as "misinformation" just because you disagree with them or they lack sources. They are UNDETERMINABLE. Only score them normally if they make explicit, objective claims about reality that can be fact-checked.

Return ONLY this JSON structure (no markdown, no extra text):
{{
  "is_undeterminable": <true if the content is purely religious, spiritual, opinion-only, or subjective with zero verifiable claims; false otherwise>,
  "undeterminable_reason": "<If is_undeterminable is true, explain in 1-2 sentences why credibility cannot be determined (e.g. 'This is a religious sermon containing faith-based claims that cannot be empirically verified.'). Empty string if false.>",
  "emotional": {{
    "score": <0-100, 100=completely neutral, 0=extremely manipulative>,
    "reason": "<2 sentences on emotional tone and clickbait>"
  }},
  "author": {{
    "score": <0-100, 80-100=clearly real journalist, 0-49=fake/pseudonym>,
    "reason": "<2 sentences on author credibility>"
  }},
  "content": {{
    "score": <0-100, 100=entirely factual with data, 0=pure emotional appeal>,
    "reason": "<2 sentences on factual vs emotional balance>"
  }},
  "mdm": {{
    "classification": "<one of: Valid, Misinformation, Malinformation, Disinformation, Unsustainable>",
    "reason": "<2 sentences explaining the ITSAP.00.300 classification>"
  }},
  "factual": {{
    "core_claim": "<the single most important factual claim in one sentence, or empty string>",
    "score": <0-100, 90-100=confirmed by multiple reliable sources, 0-29=contradicted by sources>,
    "reason": "<2 sentences on whether the core claim is accurate per reputable Canadian sources>"
  }},
  "verdict_subtext": "<one sentence stating the content type and overall credibility assessment>",
  "neutral_summary": "<Write 6-8 paragraphs reporting ONLY what the article states, exactly as a wire service journalist would. Rules: (1) Report only facts and statements present in the article — who did what, who said what, what happened, when, where, figures/statistics mentioned. (2) Include all key quotes and attributed statements verbatim or close to verbatim. (3) Do NOT comment on what the article does or does not include. Do NOT write meta-sentences like 'the article states' or 'the article does not provide'. Do NOT analyze, editorialize, or form opinions. (4) Separate paragraphs with \\n\\n. (5) Write in plain past tense, third person, neutral wire-service style — like Reuters or AP would rewrite this story.>"
}}"""

    result = call_gemini(prompt)
    required = ("emotional", "author", "content", "mdm", "factual")
    if result and all(k in result for k in required):
        _batch_cache[cache_key] = result
        # Debug: show what fields came back
        print(f"[MegaCache] SUCCESS. Fields: {list(result.keys())}")
        print(f"[MegaCache] neutral_summary length: {len(result.get('neutral_summary', ''))}")
        print(f"[MegaCache] core_claim: {result.get('factual', {}).get('core_claim', 'MISSING')[:80]}")
        return True
    print(f"[MegaCache] FAILED. result={result is not None}, missing={[k for k in required if not result or k not in result]}")
    return False


# Keep old name as alias so existing tests/code doesn't break
def prime_batch_cache(article_text: str, title: str, author_name: str) -> bool:
    return prime_mega_cache(article_text, title, author_name)


def get_batch_result(article_text: str, title: str, analysis_type: str) -> dict | None:
    """
    Returns pre-computed batch result for a given analysis type,
    or None if the cache hasn't been primed yet.

    analysis_type: one of 'emotional', 'author', 'content', 'mdm'
    """
    cache_key = hashlib.md5((article_text[:3000] + title).encode()).hexdigest()
    batch = _batch_cache.get(cache_key)
    if batch:
        return batch.get(analysis_type)
    return None

# ── Set up Gemini clients (cycles through all GEMINI_API_KEY_* keys) ──────────
_api_keys = []
for key, value in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and value.strip():
        _api_keys.append(value.strip())

if not _api_keys and os.getenv("GEMINI_API_KEY"):
    _api_keys.append(os.getenv("GEMINI_API_KEY"))

_clients = []
_current_client_idx = 0

try:
    from google import genai
    from google.genai import types as genai_types

    for key in _api_keys:
        _clients.append(genai.Client(api_key=key))

    if not _clients:
        print("[WARNING] No Gemini API keys found in .env file.")
except ImportError:
    print("[WARNING] google-genai not installed. Run: pip install google-genai")

# ── Set up Groq fallback client (free tier, llama-3.3-70b) ───────────────────
# Groq has a generous free quota. Add GROQ_API_KEY to .env to enable.
_groq_client = None
try:
    _groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if _groq_key:
        from openai import OpenAI as _OpenAI
        _groq_client = _OpenAI(api_key=_groq_key, base_url="https://api.groq.com/openai/v1")
        print("[Groq] Fallback client ready (llama-3.3-70b-versatile).")
except ImportError:
    print("[Groq] openai package not installed. Run: pip install openai")
except Exception as e:
    print(f"[Groq] Client init failed: {e}")
try:
    _groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if _groq_key:
        from openai import OpenAI as _OpenAI
        _groq_client = _OpenAI(api_key=_groq_key, base_url="https://api.groq.com/openai/v1")
        print("[Groq] Fallback client ready (llama-3.3-70b-versatile).")
except ImportError:
    print("[Groq] openai package not installed. Run: pip install openai")
except Exception as e:
    print(f"[Groq] Client init failed: {e}")

# ── Set up Grok fallback client (xAI, paid) ───────────────────────────────────
_grok_client = None
try:
    _grok_key = os.getenv("GROK_API_KEY", "").strip()
    if _grok_key:
        from openai import OpenAI as _OpenAI
        _grok_client = _OpenAI(api_key=_grok_key, base_url="https://api.x.ai/v1")
        print("[Grok] Fallback client ready (xAI).")
except Exception as e:
    print(f"[Grok] Client init failed: {e}")


def _call_openai_compatible(client, model: str, prompt: str) -> dict | None:
    """Shared helper for OpenAI-compatible providers (Groq, Grok)."""
    if not client:
        return None
    try:
        # Groq/Grok strict requirement: the word "json" MUST be in the prompt if response_format is used
        if "json" not in prompt.lower():
            prompt += "\n\nProvide the output in valid JSON format."
            
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return None
    except Exception as e:
        print(f"[{model}] error: {e}")
        return None


def call_gemini(prompt: str, model: str = "gemini-2.0-flash") -> dict | None:
    """
    Sends a prompt to Gemini (primary) or Grok (fallback when quota exhausted).
    Returns a parsed JSON dict, or None if all providers fail.
    """
    global _current_client_idx

    # ── Try Gemini first (cycle through all keys) ─────────────────────────────
    for attempt in range(len(_clients)):
        client = _clients[_current_client_idx]
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
            )
            return json.loads(response.text)

        except json.JSONDecodeError:
            return None
        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg or "400" in error_msg or "expired" in error_msg or "invalid" in error_msg:
                print(f"[Gemini Quota/Error] API Key #{_current_client_idx + 1} exhausted/invalid. Switching...")
                _current_client_idx = (_current_client_idx + 1) % len(_clients)
                continue
            else:
                print(f"[Gemini error] {e}")
                return None

    # ── All Gemini keys exhausted — try Groq (free) then Grok (paid) ─────────
    if _groq_client:
        print("[Gemini] All keys exhausted. Falling back to Groq...")
        result = _call_openai_compatible(_groq_client, "llama-3.3-70b-versatile", prompt)
        if result is not None:
            return result

    if _grok_client:
        print("[Groq] Failed. Falling back to Grok...")
        return _call_openai_compatible(_grok_client, "grok-2-latest", prompt)

    print("[AI] All providers exhausted. No result available.")
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
