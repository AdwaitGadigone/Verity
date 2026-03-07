"""
criterion2_emotional.py — Emotional Manipulation & Clickbait Language
======================================================================
WEIGHT: 20% of the final score

WHAT IS THIS CRITERION?
This checks whether the article uses emotional tricks to manipulate readers
instead of just reporting facts. Think of those "You won't BELIEVE what
happened next!" articles — that's clickbait designed to get clicks, not
inform people.

Based on ITSAP.00.300 (Canadian Centre for Cyber Security):
  - "Does it provoke an emotional response?"
  - "Does it contain clickbait?"
  - "Does it use small pieces of valid information that are exaggerated?"

WHAT IT CHECKS (4 sub-checks):
  1. ALL CAPS abuse — "THIS IS SHOCKING!!!" vs normal writing
  2. Exclamation mark overuse — professional news rarely uses !!!
  3. Clickbait phrases — known manipulation phrases like "you won't believe"
  4. Gemini AI analysis — catches subtle emotional manipulation

HIGH SCORE = the article is calm and factual (good)
LOW SCORE = the article is emotionally manipulative (bad)
"""

import re                        # Regular expressions — pattern matching in text
from gemini_client import call_gemini  # Our shared Gemini API connection


# ══════════════════════════════════════════════════════════════════════════════
# CLICKBAIT PHRASE DATABASE
# These are patterns commonly found in fake news and clickbait articles.
# We use regex (regular expressions) to search for them in the article text.
#
# WHAT IS REGEX?
# Regex is a way to search for patterns in text. For example:
#   r"you won.?t believe" matches "you won't believe" and "you wont believe"
#   The .? means "any character, optionally" — so it matches with or without '
# ══════════════════════════════════════════════════════════════════════════════
CLICKBAIT_PATTERNS = [
    r"you won.?t believe",
    r"shocking[:\s!]",
    r"they don.?t want you to know",
    r"what really happened",
    r"the truth about",
    r"exposed[:\s!]",
    r"breaking[:\s!]",
    r"doctors hate",
    r"one weird trick",
    r"this will shock you",
    r"share before.*deleted",
    r"mainstream media won.?t tell you",
    r"they.?re hiding",
    r"wake up",
    r"must (see|watch|read)",
    r"going viral",
    r"urgent[:\s!]",
    r"secret (they|the government)",
    r"[0-9]+ reasons why",
    r"what (the media|they|experts?) (won.?t|don.?t|refuse to) tell",
    r"the real truth",
    r"can.?t believe",
    r"everyone is talking about",
    r"finally revealed",
    r"this changes everything",
]


# ── SUB-CHECK 1: ALL CAPS Ratio ─────────────────────────────────────────────
def _score_caps_ratio(text: str, title: str = "") -> tuple:
    """
    Counts what percentage of words are ALL CAPITALS.
    Legitimate journalism almost never uses ALL CAPS for emphasis.

    Examples:
      "The Prime Minister announced new policy" → normal
      "The PM EXPOSED SHOCKING FRAUD in GOVERNMENT" → manipulative

    Returns (score 0-100, reason). 100 = no caps abuse.
    """
    combined = f"{title} {text[:1000]}"
    words = combined.split()

    if not words:
        return 70, "Insufficient text for ALL CAPS analysis"

    # Count words that are FULLY UPPERCASE and at least 3 letters
    # (we skip short ones like "UN" or "CBC" — those are legitimate acronyms)
    caps_words = [w for w in words if w.isupper() and len(w) >= 3 and w.isalpha()]
    ratio = len(caps_words) / len(words)

    if ratio > 0.15:
        return 10, f"Heavy use of ALL CAPS ({len(caps_words)} fully-capitalized words) -- emotional manipulation signal"
    elif ratio > 0.08:
        return 35, "Moderate ALL CAPS usage detected -- possible emotional manipulation"
    elif ratio > 0.03:
        return 65, "Some capitalization emphasis detected"
    else:
        return 90, "No excessive ALL CAPS usage -- normal writing style"


# ── SUB-CHECK 2: Exclamation Mark Density ────────────────────────────────────
def _score_exclamation_density(text: str) -> tuple:
    """
    Counts exclamation marks per 1000 characters.
    Real journalism uses them very sparingly (if at all).

    Returns (score 0-100, reason). 100 = no exclamation abuse.
    """
    if not text:
        return 70, "Insufficient text for punctuation analysis"

    exclamation_count = text.count("!")
    density = (exclamation_count / len(text)) * 1000  # per 1000 characters

    if density > 5:
        return 15, f"Very high exclamation mark density ({exclamation_count} found) -- emotional writing style"
    elif density > 2:
        return 45, f"Elevated exclamation mark usage ({exclamation_count} found)"
    elif density > 0.5:
        return 70, f"Minor exclamation mark usage ({exclamation_count} found)"
    else:
        return 90, "Low exclamation mark usage -- consistent with professional journalism"


# ── SUB-CHECK 3: Clickbait Phrase Detection ──────────────────────────────────
def _score_clickbait(title: str, text: str) -> tuple:
    """
    Searches the title and article text for known clickbait phrases.

    WHAT IS re.search()?
    re.search(pattern, text) looks for a regex pattern anywhere in the text.
    If it finds a match, it returns a Match object. If not, it returns None.

    Returns (score 0-100, reason). 100 = no clickbait found.
    """
    # Combine title and first 500 characters of text, all lowercase
    combined = f"{title} {text[:500]}".lower()
    matches = []

    # Check each clickbait pattern against the combined text
    for pattern in CLICKBAIT_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            matches.append(match.group(0))  # Save the matched text

    # Score based on how many clickbait phrases we found
    if len(matches) >= 3:
        quoted = ", ".join('"' + m + '"' for m in matches[:2])
        return 10, f"Multiple clickbait phrases detected: {quoted}"
    elif len(matches) == 2:
        quoted = ", ".join('"' + m + '"' for m in matches)
        return 25, f"Clickbait phrases detected: {quoted}"
    elif len(matches) == 1:
        return 50, f'Clickbait phrase detected: "{matches[0]}"'
    else:
        return 95, "No clickbait phrases detected"


# ── SUB-CHECK 4: Gemini AI Emotional Tone Analysis ──────────────────────────
def _score_emotional_with_gemini(text: str, title: str = "") -> tuple:
    """
    Uses Gemini AI to analyze the article's emotional tone at a deeper level.
    Gemini can catch subtle emotional manipulation that simple pattern matching
    (regex) misses — like fear-mongering through word choice.

    Returns (score 0-100, reason). 100 = completely neutral/factual.
    """
    # Send first 2000 characters to Gemini (enough for tone analysis)
    sample = f"HEADLINE: {title}\n\nARTICLE EXCERPT:\n{text[:2000]}"

    prompt = f"""
You are analyzing an article for emotional manipulation as part of a Canadian misinformation detection tool.

Analyze for:
1. Fear-mongering or outrage language designed to provoke emotional reactions
2. Exaggerated or distorted framing of facts
3. Language designed to manipulate rather than inform

Rate 0 to 100 where:
- 100 = Completely neutral and factual
- 50 = Mixed -- some emotional language but also factual
- 0 = Extremely manipulative -- designed to provoke fear/anger/outrage

Article:
{sample}

Respond with ONLY valid JSON:
{{"score": <0-100>, "reason": "<2-3 short sentences explaining the emotional tone>"}}
"""

    result = call_gemini(prompt)
    if result and "score" in result:
        score = max(0, min(100, int(result["score"])))
        return score, result.get("reason", "Gemini emotional analysis complete")
    return 50, "Gemini emotional analysis unavailable -- treated as neutral"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
def analyze(article_data: dict) -> dict:
    """
    Runs all 4 emotional manipulation checks and combines them.

    Parameters:
        article_data: The dictionary from scraper.py

    Returns:
        {"score": 0-100, "reason": "explanation"}
    """
    title = article_data.get("title", "")
    text = article_data.get("text", "")

    if not text and not title:
        return {"score": 50, "reason": "No content available for emotional analysis"}

    # Run all 4 sub-checks
    caps_score, caps_reason = _score_caps_ratio(text, title)
    exclaim_score, exclaim_reason = _score_exclamation_density(text)
    clickbait_score, clickbait_reason = _score_clickbait(title, text)
    gemini_score, gemini_reason = _score_emotional_with_gemini(text, title)

    # Combine with weights — Gemini gets the highest weight because
    # it does the deepest analysis (catches what regex misses)
    final_score = int(round(
        caps_score * 0.20 +
        exclaim_score * 0.10 +
        clickbait_score * 0.25 +
        gemini_score * 0.45
    ))

    # Pick the most important finding as the displayed reason
    if clickbait_score < 30:
        reason = clickbait_reason
    elif caps_score < 30:
        reason = caps_reason
    else:
        reason = gemini_reason

    return {"score": final_score, "reason": reason}
