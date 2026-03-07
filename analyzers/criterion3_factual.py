"""
criterion3_factual.py — Factual Verifiability & Cross-Source Consistency
=========================================================================
WEIGHT: 25% of the final score (THE HIGHEST — this is the most important)

WHAT IS THIS CRITERION?
This is the CORE of Verity — it checks whether the article's main claim
is actually TRUE. It extracts the main factual claim from the article,
then asks Gemini to verify it against known facts.

Based on ITSAP.00.300 (Canadian Centre for Cyber Security):
  - "Use a fact-checking site to verify the information hasn't been proven false"
  - "Ensure the information is up to date"
  - "Is it an extraordinary claim?"

WHAT IT CHECKS (4 sub-checks):
  1. Core claim extraction — what is the main factual claim in this article?
  2. Claim verification — is that claim actually true?
  3. Date/recency — is the article dated? Is it current?
  4. Extraordinary claim test — big claims need big evidence
"""

from datetime import datetime
from gemini_client import call_gemini  # Our shared Gemini API connection


# ── SUB-CHECK 1: Extract the Core Claim ──────────────────────────────────────
def _extract_core_claim(text: str, title: str = "") -> str:
    """
    Uses Gemini to read the article and extract the SINGLE most important
    factual claim being made, as ONE clear sentence.

    WHY DO WE EXTRACT THE CLAIM FIRST?
    Instead of asking Gemini "is this article true?" (vague), we first
    identify WHAT specific claim the article makes, then verify THAT claim.
    This gives much more accurate and precise results.

    Example:
      Article about housing prices → Claim: "Average house prices in Toronto
      rose 15% in 2024"
      We can then verify if that specific number is correct.

    Returns the claim as a string, or "" if extraction fails.
    """
    if not text:
        return ""

    prompt = f"""
You are a fact-checking assistant for a Canadian misinformation detection tool.

Read this article and identify the single most important FACTUAL claim being made.
This should be a specific, verifiable statement (not an opinion or prediction).

Article headline: {title}
Article text (first 1500 characters): {text[:1500]}

Respond with ONLY valid JSON:
{{"claim": "<one clear sentence stating the main factual claim>"}}

If there is no clear factual claim, respond with:
{{"claim": ""}}
"""

    result = call_gemini(prompt)
    if result:
        return result.get("claim", "")
    return ""


# ── SUB-CHECK 2: Verify the Claim ───────────────────────────────────────────
def _verify_claim_with_gemini(claim: str) -> tuple:
    """
    Asks Gemini whether the extracted claim is accurate based on its
    knowledge of real-world events and reputable news sources.

    Gemini 2.0 Flash has extensive knowledge of current events (trained
    up to early 2025) making it suitable for real-time-ish verification.

    Returns (score 0-100, reason).
    """
    if not claim:
        return 50, "No claim extracted -- factual verification not possible"

    prompt = f"""
You are a fact-checker for a Canadian misinformation detection tool.

Assess this claim by explicitly CROSS-CHECKING it against your knowledge base of reputable news media (e.g., CBC, Reuters, AP, Globe and Mail) and real-world events. Determine if the information is consistent across these multiple reliable sources.

Claim: "{claim}"

Rate accuracy from 0 to 100 where:
- 90-100: Clearly confirmed by multiple reliable sources
- 70-89: Likely accurate, consistent with reputable reporting
- 50-69: Uncertain, unverifiable, or conflicting reports
- 30-49: Partially accurate but significantly distorted
- 0-29: Contradicted by reliable sources or clearly false

Respond with ONLY valid JSON:
{{"score": <0-100>, "reason": "<2-3 short sentences explicitly naming if other reputable sources confirm or contradict this claim>"}}
"""

    result = call_gemini(prompt)
    if result and "score" in result:
        score = max(0, min(100, int(result["score"])))
        return score, result.get("reason", "Fact verification complete")
    return 50, "Gemini fact verification unavailable -- treated as neutral"


# ── SUB-CHECK 3: Date / Recency ─────────────────────────────────────────────
def _check_date_recency(publish_date: str) -> tuple:
    """
    Checks if the article has a publish date and how old it is.

    WHY DOES THIS MATTER?
    Articles WITHOUT dates are a red flag — legitimate news always dates
    their articles. Also, old articles being reshared as "new" is a common
    misinformation tactic.

    Returns (score 0-100, reason).
    """
    if not publish_date or publish_date in ("None", ""):
        return 25, "Article has no visible publish date -- undated content is a red flag"

    try:
        # Try to parse the date string into a datetime object
        date_str = str(publish_date).split("+")[0].split("Z")[0].strip()

        # Try multiple date formats since different sites format dates differently
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                pub_date = datetime.strptime(date_str[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return 50, "Could not parse publish date -- date format unclear"

        # Calculate how old the article is
        age_days = (datetime.now() - pub_date).days

        if age_days < 0:
            return 30, "Publish date is in the future -- suspicious"
        elif age_days <= 7:
            return 90, f"Article is recent (published {age_days} days ago)"
        elif age_days <= 90:
            return 80, f"Article is relatively recent (published {age_days} days ago)"
        elif age_days <= 365:
            return 65, f"Article is {age_days} days old -- verify it is not reshared as new"
        else:
            years = age_days // 365
            return 40, f"Article is {years} year(s) old -- may be outdated"

    except Exception:
        return 50, "Could not determine article recency"


# ── SUB-CHECK 4: Extraordinary Claim Detection ──────────────────────────────
def _check_extraordinary_claim(text: str, title: str, claim: str) -> tuple:
    """
    Checks if the article makes an EXTRAORDINARY claim, and if so,
    whether it provides proportionate evidence.

    ITSAP.00.300: "Is it an extraordinary claim?"
    The principle: extraordinary claims require extraordinary evidence.

    Example:
      "Taxes went up 2%" → normal claim → doesn't need a lot of evidence
      "Government hiding cure for cancer!" → extraordinary → needs HUGE evidence

    Returns (score 0-100, reason).
    """
    sample = f"HEADLINE: {title}\nCLAIM: {claim}\nARTICLE EXCERPT: {text[:1000]}"

    prompt = f"""
You are a fact-checking assistant for a Canadian misinformation detection tool.

Analyze this article. Determine if it makes an "extraordinary claim"
(dramatic, surprising, or unprecedented -- contradicts common knowledge).

Then assess whether it provides proportionate evidence
(citations, expert sources, data, links to primary sources).

Article:
{sample}

Respond with ONLY valid JSON:
{{
  "is_extraordinary": <true or false>,
  "has_evidence": <true or false>,
  "score": <0-100>,
  "reason": "<2-3 short sentences explaining your assessment>"
}}

Score guide:
- Not extraordinary: 75
- Extraordinary WITH strong evidence: 80
- Extraordinary with some evidence: 55
- Extraordinary with NO evidence: 10
"""

    result = call_gemini(prompt)
    if result and "score" in result:
        score = max(0, min(100, int(result["score"])))
        return score, result.get("reason", "Extraordinary claim assessment complete")
    return 60, "Could not assess extraordinary claim status -- treated as neutral"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
def analyze(article_data: dict) -> dict:
    """
    Runs all factual verifiability checks.

    Parameters:
        article_data: The dictionary from scraper.py

    Returns:
        {"score": 0-100, "reason": "explanation", "core_claim": "the extracted claim"}

    NOTE: We also return "core_claim" so the frontend can show the user
    WHAT specific claim was fact-checked. This is important for transparency.
    """
    title = article_data.get("title", "")
    text = article_data.get("text", "")
    publish_date = article_data.get("publish_date")

    if not text:
        return {"score": 40, "reason": "No article text available for fact verification", "core_claim": ""}

    # Step 1: What claim does this article make?
    core_claim = _extract_core_claim(text, title)

    # Step 2: Is that claim actually true?
    verify_score, verify_reason = _verify_claim_with_gemini(core_claim)

    # Step 3: Is the article dated and current?
    date_score, date_reason = _check_date_recency(
        str(publish_date) if publish_date else ""
    )

    # Step 4: Is this an extraordinary claim without evidence?
    extra_score, extra_reason = _check_extraordinary_claim(text, title, core_claim)

    # Combine — verification gets highest weight (it's the core check)
    final_score = int(round(
        verify_score * 0.55 +
        date_score * 0.20 +
        extra_score * 0.25
    ))

    # Pick the most important finding as the reason
    if verify_score < 35:
        reason = verify_reason
    elif extra_score < 20:
        reason = f"{extra_reason}. {verify_reason}."
    elif date_score < 30:
        reason = f"{date_reason}. {verify_reason}."
    else:
        reason = verify_reason

    return {"score": final_score, "reason": reason, "core_claim": core_claim}
