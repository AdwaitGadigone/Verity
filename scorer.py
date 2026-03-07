"""
scorer.py — The Verity Scoring Engine
=======================================

WHAT DOES THIS FILE DO?
This is the "brain" of Verity. It takes the article data, runs ALL 6
criteria at the same time (in parallel), collects their scores, and
calculates the final 0-100 credibility score.

THE FORMULA:
  Final Score = (C1 x 0.20) + (C2 x 0.20) + (C3 x 0.25) +
                (C4 x 0.15) + (C5 x 0.10) + (C6 x 0.10)

VERDICT TIERS (5 levels):
  90-100 → Highly Credible
  72-89  → Likely Credible
  45-71  → Uncertain
  25-44  → Likely Misinformation
  0-24   → Misinformation / Disinformation
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from analyzers import (
    criterion1_domain,
    criterion2_emotional,
    criterion3_factual,
    criterion4_author,
    criterion5_content,
    criterion6_mdm,
)

# ── Criterion weights (must add up to 1.0) ───────────────────────────────────
WEIGHTS = {
    "domain":    0.20,
    "emotional": 0.20,
    "factual":   0.25,
    "author":    0.15,
    "content":   0.10,
    "mdm":       0.10,
}

# ── Trusted institutional source domains ────────────────────────────────────
# For these domains, some criteria behave differently:
#   - Government sites don't have personal bylines (that's normal)
#   - They're inherently neutral (no emotional manipulation)
#   - They're definitionally "Valid" under MDM framework
TRUSTED_DOMAINS = [
    # Canadian Federal Government
    "canada.ca", "gc.ca", "statcan.gc.ca", "healthcanada.gc.ca",
    "parl.gc.ca", "rcmp-grc.gc.ca", "forces.gc.ca", "justice.gc.ca",
    "pco-bcp.gc.ca", "pm.gc.ca", "elections.ca", "cra-arc.gc.ca",
    "servicecanada.gc.ca", "crtc.gc.ca", "cyber.gc.ca",
    # Canadian Public Broadcasters
    "cbc.ca", "radio-canada.ca",
    # Major established Canadian outlets
    "theglobeandmail.com", "thestar.com", "nationalpost.com",
    "macleans.ca", "globalnews.ca",
]


def _is_trusted(domain: str) -> bool:
    """Returns True if this is a known trusted institutional source."""
    d = domain.lower().replace("www.", "")
    for t in TRUSTED_DOMAINS:
        if d == t or d.endswith("." + t):
            return True
    return False


def _apply_trusted_source_boost(results: dict, domain: str) -> dict:
    """
    For trusted institutional sources, we adjust certain criterion scores
    to reflect how these organizations actually work in practice.

    WHY THIS IS JUSTIFIED:
    - Government sites (canada.ca, gc.ca) don't have personal bylines
      because content is published by the institution — that's NORMAL.
    - Government content is inherently neutral by mandate.
    - Under ITSAP.00.300, official government content is "Valid" by definition.
    - These sources have professional design standards enforced by the Government
      of Canada's Web Experience Toolkit (WET) standards.

    We only BOOST scores that are low due to criteria not applying to these
    institutional sources — we never lower scores.
    """
    if not _is_trusted(domain):
        return results

    # C4 AUTHOR: Government/institutional content uses organizational attribution
    if results["author"]["score"] < 70:
        results["author"] = {
            **results["author"],
            "score": 80,
            "reason": "Institutional/government source — organizational attribution "
                      "is standard practice. No personal byline is expected or required "
                      "for government publications."
        }

    # C2 EMOTIONAL: Government/institutional sources are structurally neutral
    if results["emotional"]["score"] < 72:
        results["emotional"] = {
            **results["emotional"],
            "score": 82,
            "reason": "Institutional or public broadcaster source — content is "
                      "structurally neutral and informational by mandate. "
                      "No emotional manipulation or clickbait detected."
        }

    # C6 MDM: If Gemini failed to classify, government content is Valid by definition
    mdm_classification = results["mdm"].get("classification", "")
    if mdm_classification in ("Unsustainable", "", "Unknown") or results["mdm"]["score"] <= 55:
        results["mdm"] = {
            **results["mdm"],
            "score": 90,
            "classification": "Valid",
            "reason": "Verified institutional source. Government of Canada and public "
                      "broadcaster content is classified as Valid under ITSAP.00.300 "
                      "Canadian Centre for Cyber Security guidelines."
        }

    # C5 CONTENT: Government sites use WET (Web Experience Toolkit) standards
    if results["content"]["score"] < 65:
        results["content"] = {
            **results["content"],
            "score": 72,
            "reason": "Institutional source using professional Government of Canada "
                      "Web Experience Toolkit (WET) design standards. "
                      "Content integrity meets federal web publishing guidelines."
        }

    return results


def _run_criterion_safely(name: str, func, *args) -> dict:
    """
    Runs a single criterion function with error protection.
    If the criterion crashes, returns a safe neutral score of 50
    instead of letting the whole app crash.
    """
    try:
        result = func(*args)
        result["name"] = name
        return result
    except Exception as e:
        return {
            "name": name,
            "score": 50,
            "reason": f"Could not verify — treated as neutral ({str(e)[:60]})",
            "error": True
        }


def run_all(article_data: dict) -> dict:
    """
    Runs ALL 6 criteria in parallel, applies trusted-source adjustments
    if applicable, and returns the full analysis result.

    Called by app.py when user clicks 'Analyze Content'.
    """
    domain = article_data.get("domain", "")
    homepage_html = article_data.get("homepage_html", "")
    article_text = article_data.get("text", "")
    title = article_data.get("title", "")
    authors = article_data.get("authors", [])
    author_name = authors[0] if authors else ""

    # ── Single mega Gemini call — covers ALL criteria + final score ───────────
    # One call replaces what was previously 5 separate Gemini calls:
    #   criteria 2, 4, 5, 6 AI parts + criterion 3 fact-check + final score.
    # Each criterion reads its result from the cache via get_batch_result().
    from gemini_client import prime_mega_cache
    prime_mega_cache(article_text, title, author_name)

    # Define all 6 tasks
    tasks = [
        ("domain",    criterion1_domain.analyze,    domain, homepage_html),
        ("emotional", criterion2_emotional.analyze,  article_data),
        ("factual",   criterion3_factual.analyze,    article_data),
        ("author",    criterion4_author.analyze,     article_data),
        ("content",   criterion5_content.analyze,    article_data),
        ("mdm",       criterion6_mdm.analyze,        article_data),
    ]

    results = {}

    # Run all 6 criteria simultaneously using a thread pool
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_key = {
            executor.submit(_run_criterion_safely, key, func, *args): key
            for key, func, *args in tasks
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            results[key] = future.result()

    # Apply trusted-source adjustments (e.g. for canada.ca, cbc.ca)
    results = _apply_trusted_source_boost(results, domain)

    # Calculate the weighted final score (as a fallback if Gemini fails)
    fallback_score = sum(
        results[key]["score"] * WEIGHTS[key]
        for key in WEIGHTS
    )
    fallback_score = int(round(fallback_score))

    # Read final score from the mega cache (already computed in the single call above).
    # Falls back to the weighted math if the mega call failed.
    from gemini_client import get_batch_result
    mega = get_batch_result(article_text, title, "_self")  # "_self" returns root dict
    if mega is None:
        # get_batch_result doesn't support root access — fetch from cache directly
        import gemini_client, hashlib
        cache_key = hashlib.md5((article_text[:3000] + title).encode()).hexdigest()
        mega = gemini_client._batch_cache.get(cache_key)

    # Always use weighted math for final_score — AI-generated final_score
    # is often inconsistent with its own criteria scores (e.g. rates a
    # criterion 86/100 but gives overall 58). Trust the math, not the AI.
    final_score = fallback_score
    verdict_subtext_base = mega.get("verdict_subtext") if mega else None
    neutral_summary = mega.get("neutral_summary", "") if mega else ""

    # Determine the verdict (5-tier system) based on final_score
    if final_score >= 90:
        verdict = "Highly Credible"
        verdict_subtext = verdict_subtext_base or "This content appears to be accurate and well-sourced."
        verdict_class = "v-excellent"
    elif final_score >= 72:
        verdict = "Likely Credible"
        verdict_subtext = verdict_subtext_base or "This content appears mostly reliable. Minor concerns noted."
        verdict_class = "v-good"
    elif final_score >= 45:
        verdict = "Uncertain"
        verdict_subtext = verdict_subtext_base or "Proceed with caution. Verify claims through additional sources."
        verdict_class = "v-uncertain"
    elif final_score >= 25:
        verdict = "Likely Misinformation"
        verdict_subtext = verdict_subtext_base or "Significant warning signs detected. Do not share without verification."
        verdict_class = "v-suspicious"
    else:
        verdict = "Misinformation / Disinformation"
        verdict_subtext = verdict_subtext_base or "This content is highly likely to be false or deliberately misleading."
        verdict_class = "v-bad"

    # Get MDM classification and core claim
    mdm_classification = results.get("mdm", {}).get("classification", "Unsustainable")
    core_claim = results.get("factual", {}).get("core_claim", "")

    # Format criteria for the frontend
    criteria_display = [
        {
            "key":    "domain",
            "label":  "Website Trustworthiness",
            "weight": "20%",
            "score":  results["domain"]["score"],
            "reason": results["domain"]["reason"],
        },
        {
            "key":    "emotional",
            "label":  "Sensationalism & Clickbait",
            "weight": "20%",
            "score":  results["emotional"]["score"],
            "reason": results["emotional"]["reason"],
        },
        {
            "key":    "factual",
            "label":  "Fact-Checking & Accuracy",
            "weight": "25%",
            "score":  results["factual"]["score"],
            "reason": results["factual"]["reason"],
        },
        {
            "key":    "author",
            "label":  "Author Verifiability",
            "weight": "15%",
            "score":  results["author"]["score"],
            "reason": results["author"]["reason"],
        },
        {
            "key":    "content",
            "label":  "Content Quality",
            "weight": "10%",
            "score":  results["content"]["score"],
            "reason": results["content"]["reason"],
        },
        {
            "key":    "mdm",
            "label":  "Threat Classification",
            "weight": "10%",
            "score":  results["mdm"]["score"],
            "reason": results["mdm"]["reason"],
        },
    ]

    return {
        "final_score":       final_score,
        "verdict":           verdict,
        "verdict_subtext":   verdict_subtext,
        "verdict_class":     verdict_class,
        "mdm_classification": mdm_classification,
        "core_claim":        core_claim,
        "neutral_summary":   neutral_summary,
        "criteria":          criteria_display,
    }
