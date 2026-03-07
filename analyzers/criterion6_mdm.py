"""
criterion6_mdm.py — MDM Classification (the ITSAP.00.300 framework)
=====================================================================
WEIGHT: 10% of the final score

WHAT IS MDM?
MDM stands for Misinformation, Disinformation, Malinformation — the three
types of "bad" information defined by the Canadian Centre for Cyber Security
in their official guide (ITSAP.00.300).

This criterion directly implements ITSAP.00.300 by classifying the article
into one of 5 categories:

  VALID:           Factually correct, not misleading              → Score: 100
  MISINFORMATION:  False but NOT intentionally harmful            → Score: 40
  MALINFORMATION:  True but EXAGGERATED to mislead                → Score: 25
  DISINFORMATION:  Intentionally false, designed to manipulate    → Score: 10
  UNSUSTAINABLE:   Cannot be confirmed or disproved               → Score: 50

WHY IS THIS IMPORTANT?
This classification is displayed prominently in the UI because it directly
maps to the Canadian government's framework. During the hackathon demo,
we can point to the official ITSAP document and say "our tool classifies
articles using the exact same categories the Canadian government uses."
"""

from gemini_client import call_gemini, get_batch_result  # Our shared Gemini API connection


# ── Score mapping — directly from ITSAP.00.300 definitions ──────────────────
MDM_SCORES = {
    "Valid": 100,
    "Misinformation": 40,
    "Malinformation": 25,
    "Disinformation": 10,
    "Unsustainable": 50,
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
def analyze(article_data: dict) -> dict:
    """
    Uses Gemini AI to classify the article into one of the 5 MDM categories
    defined by the Canadian Centre for Cyber Security.

    Parameters:
        article_data: The dictionary from scraper.py

    Returns:
        {
            "score": 0-100,
            "reason": "2-3 short sentences explaining the classification",
            "classification": "Valid" | "Misinformation" | etc.
        }

    The "classification" field is used by the frontend to display the
    MDM badge (e.g. "Classified as: Disinformation").
    """
    title = article_data.get("title", "")
    text = article_data.get("text", "")

    # If there's no text to analyze, default to "Unsustainable"
    if not text:
        return {
            "score": 50,
            "reason": "No content available for MDM classification",
            "classification": "Unsustainable"
        }

    # Check batch cache first (primed by scorer.py before criteria run)
    cached = get_batch_result(text, title, "mdm")
    if cached and "classification" in cached:
        result = cached
    else:
        # Fallback: direct Gemini call
        sample = f"HEADLINE: {title}\n\nARTICLE TEXT (first 2000 chars):\n{text[:2000]}"
        prompt = f"""
You are a misinformation analyst for a Canadian cybersecurity tool.
Classify this article using the MDM framework from the Canadian Centre
for Cyber Security (ITSAP.00.300).

The 5 classifications are:
1. "Valid" -- Factually correct, based on confirmable data, not misleading
2. "Misinformation" -- Contains false information, NOT intentionally designed to harm
3. "Malinformation" -- Based in truth but exaggerated or distorted to mislead
4. "Disinformation" -- Intentionally false, deliberately designed to manipulate
5. "Unsustainable" -- Cannot be confirmed or disproved based on available information

Article:
{sample}

Respond with ONLY valid JSON:
{{
  "classification": "<one of: Valid, Misinformation, Malinformation, Disinformation, Unsustainable>",
  "reason": "<2-3 short sentences explaining why this classification applies>"
}}
"""
        result = call_gemini(prompt)

    if result and "classification" in result:
        classification = result["classification"]
        reason = result.get("reason", "Classification complete")

        # Make sure Gemini returned a valid category (sometimes AI gets creative)
        if classification not in MDM_SCORES:
            classification = "Unsustainable"
            reason = "Classification could not be determined -- treated as Unsustainable"

        return {
            "score": MDM_SCORES[classification],
            "reason": reason,
            "classification": classification
        }

    # If Gemini failed, default to Unsustainable (neutral)
    return {
        "score": 50,
        "reason": "MDM classification unavailable -- treated as Unsustainable",
        "classification": "Unsustainable"
    }
