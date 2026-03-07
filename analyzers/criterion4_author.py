"""
criterion4_author.py — Author & Source Transparency
=====================================================
WEIGHT: 15% of the final score

WHAT IS THIS CRITERION?
This checks WHO wrote the article and whether they cite their sources.
Real journalism always has a named author and references where the
information came from. Anonymous articles with zero sources are red flags.

Based on ITSAP.00.300 (Canadian Centre for Cyber Security):
  - "Verify the author and sources cited in the article"
  - Legitimate journalism always has named, verifiable authors

WHAT IT CHECKS (3 sub-checks):
  1. Named byline — is there a real author name? (not "Staff" or "Admin")
  2. Author verifiability — does Gemini think this is a real journalist?
  3. Source citations — does the article say things like "according to" or
     "the study found"? (signs of proper sourcing)
"""

import re                        # Regular expressions for pattern matching
from gemini_client import call_gemini, get_batch_result  # Our shared Gemini API connection

# Generic/fake bylines that don't identify a real person
GENERIC_BYLINES = [
    "staff", "admin", "editor", "webmaster", "news desk",
    "news team", "reporter", "contributor", "anonymous", "unknown"
]


# ── SUB-CHECK 1: Named Byline ───────────────────────────────────────────────
def _score_byline(authors: list) -> tuple:
    """
    Checks if the article has a real, named author.

    WHY DOES THIS MATTER?
    Legitimate journalists put their name on their work because they stand
    behind it. Anonymous articles or ones credited to "Staff" provide no
    accountability — a hallmark of misinformation.

    Parameters:
        authors: A list of author names from the scraper (may be empty)

    Returns (score 0-100, reason).
    """
    if not authors:
        return 15, "No author listed -- anonymous articles are a credibility red flag"

    author = authors[0].strip().lower()

    # Check if the author name is just a generic placeholder
    if any(generic in author for generic in GENERIC_BYLINES):
        return 25, f"Generic byline ('{authors[0]}') -- no identifiable journalist"

    # A real name usually has at least 2 parts (first name + last name)
    name_parts = authors[0].strip().split()
    if len(name_parts) >= 2:
        return 85, f"Named author found: {authors[0]}"
    else:
        return 50, f"Partial author name: '{authors[0]}' -- may not be fully identifiable"


# ── SUB-CHECK 2: Author Verifiability ────────────────────────────────────────
def _score_author_verifiability(author_name: str, text: str) -> tuple:
    """
    Uses Gemini to assess whether the author name looks like a real person.
    Checks the batch cache first (primed by scorer.py) before making a new call.

    Returns (score 0-100, reason).
    """
    if not author_name:
        return 40, "Author verifiability check skipped -- no author name available"

    # Check batch cache first
    cached = get_batch_result(text, "", "author")
    if cached and "score" in cached:
        score = max(0, min(100, int(cached["score"])))
        return score, cached.get("reason", "Author verifiability assessed")

    # Fallback: direct Gemini call
    prompt = f"""
You are helping a Canadian misinformation detection tool evaluate author credibility.

Author name: "{author_name}"
Article excerpt (first 300 chars): "{text[:300]}"

Assess whether this appears to be a real, identifiable journalist or a pseudonym/fake name.

Respond with ONLY valid JSON:
{{"score": <0-100>, "reason": "<2-3 short sentences explaining the author assessment>"}}

Score guide: 80-100 = clearly real journalist, 50-79 = likely real but unconfirmed,
0-49 = appears to be a pseudonym or fake name
"""
    result = call_gemini(prompt)
    if result and "score" in result:
        score = max(0, min(100, int(result["score"])))
        return score, result.get("reason", "Author verifiability assessed")
    return 50, "Could not verify author identity -- treated as neutral"


# ── SUB-CHECK 3: Source Citations ────────────────────────────────────────────
def _score_source_citations(text: str) -> tuple:
    """
    Searches the article text for phrases that indicate the author is
    citing their sources (like a Works Cited page in an essay, but inline).

    Examples of citation signals:
      "According to Health Canada..."
      "The study found that..."
      "A spokesperson said..."
      "Statistics Canada data shows..."

    WHAT IS re.search()?
    It looks for a pattern (regex) anywhere in the text.
    We use it to count how many different citation patterns appear.

    Returns (score 0-100, reason).
    """
    if not text:
        return 30, "No article text -- cannot check for source citations"

    text_lower = text.lower()

    # Patterns that indicate the article cites sources
    citation_patterns = [
        r"according to",
        r"said (the|a|an)",
        r"told reporters",
        r"in a statement",
        r"per the",
        r"cited",
        r"study (found|showed|says)",
        r"research shows",
        r"data (shows|reveals|suggests)",
        r"government (report|data|statistics)",
        r"statistics canada",
        r"health canada",
        r"a (spokesperson|representative)",
        r"the (report|study|survey) (found|shows)",
    ]

    # Count how many different citation patterns are present
    citation_count = sum(
        1 for pattern in citation_patterns
        if re.search(pattern, text_lower)
    )

    if citation_count >= 4:
        return 90, f"Well-sourced article -- {citation_count} citation signals detected"
    elif citation_count >= 2:
        return 70, f"Some sourcing present -- {citation_count} citation signals detected"
    elif citation_count == 1:
        return 45, "Limited sourcing -- only 1 citation signal detected"
    else:
        return 15, "No source citations detected -- all claims appear unsourced"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
def analyze(article_data: dict) -> dict:
    """
    Runs all author/source transparency checks.

    Parameters:
        article_data: The dictionary from scraper.py

    Returns:
        {"score": 0-100, "reason": "explanation"}
    """
    authors = article_data.get("authors", [])
    text = article_data.get("text", "")

    # Run all 3 sub-checks
    byline_score, byline_reason = _score_byline(authors)
    author_name = authors[0] if authors else ""
    verif_score, verif_reason = _score_author_verifiability(author_name, text)
    citation_score, citation_reason = _score_source_citations(text)

    # Combine — citations get highest weight (most verifiable signal)
    final_score = int(round(
        byline_score * 0.35 +
        verif_score * 0.25 +
        citation_score * 0.40
    ))

    # Pick the most important finding
    if byline_score < 30:
        reason = byline_reason
    elif citation_score < 25:
        reason = f"{citation_reason}. {byline_reason}."
    elif citation_score >= 80 and byline_score >= 80:
        reason = f"{byline_reason}. {citation_reason}."
    else:
        reason = citation_reason

    return {"score": final_score, "reason": reason}
