"""
criterion5_content.py — Content Integrity & Presentation
==========================================================
WEIGHT: 10% of the final score

WHAT IS THIS CRITERION?
This checks the QUALITY of the content and the website's design.
Professional news sites look clean and polished. Fake news sites often
have animated GIFs, pop-ups, excessive images, and sloppy formatting.

Based on ITSAP.00.300 (Canadian Centre for Cyber Security):
  - "Look for out of place design elements such as unprofessional logos,
     colours, spacing and animated gifs"
  - "Conduct a reverse image search to ensure images are not copied
     from a legitimate website"

WHAT IT CHECKS (3 sub-checks):
  1. Design quality markers — animated GIFs, pop-ups, sloppy HTML
  2. Content substance — is the article factual or just emotional fluff?
  3. Image flag — reminds the user to check images manually
"""

import re                        # Regular expressions for pattern matching
from gemini_client import call_gemini  # Our shared Gemini API connection


# ── SUB-CHECK 1: Design Quality Markers ──────────────────────────────────────
def _check_design_markers(homepage_html: str) -> tuple:
    """
    Scans the homepage HTML for signs of unprofessional design.

    WHAT IS HTML?
    HTML (HyperText Markup Language) is the code that makes up web pages.
    When you "View Source" on any website, you see HTML. It uses tags like
    <p> for paragraphs, <img> for images, <marquee> for scrolling text.

    WHY CHECK HTML FOR RED FLAGS?
    Legitimate news sites use modern, clean HTML. Fake news sites often use
    outdated elements like <marquee> (scrolling text from the 1990s),
    animated GIFs everywhere, and pop-up overlays.

    Returns (score 0-100, reason).
    """
    html = homepage_html.lower() if homepage_html else ""

    if not html:
        return 60, "Could not access page HTML -- design quality unverifiable"

    red_flags = []

    # Check for animated GIFs (common on low-quality sites)
    if re.search(r'<img[^>]+\.gif', html):
        red_flags.append("animated GIFs detected")

    # Check for <marquee> tag (outdated, unprofessional scrolling text)
    if "<marquee" in html:
        red_flags.append("<marquee> tag found (very unprofessional)")

    # Check for excessive inline styles (sign of bad coding practices)
    inline_style_count = len(re.findall(r'style="[^"]{50,}"', html))
    if inline_style_count > 20:
        red_flags.append(f"excessive inline styling ({inline_style_count} instances)")

    # Check for too many images (image spam)
    img_count = len(re.findall(r'<img', html))
    if img_count > 30:
        red_flags.append(f"unusually high image count ({img_count} images)")

    # Check for pop-up/overlay elements (common on clickbait sites)
    if re.search(r'(popup|pop-up|overlay|modal)', html):
        red_flags.append("pop-up/overlay elements detected")

    # Score based on how many red flags we found
    if len(red_flags) >= 3:
        return 20, "Multiple unprofessional design markers: " + ", ".join(red_flags[:2])
    elif len(red_flags) == 2:
        return 40, "Some unprofessional design elements: " + ", ".join(red_flags)
    elif len(red_flags) == 1:
        return 65, f"Minor design concern: {red_flags[0]}"
    else:
        return 88, "No major unprofessional design markers detected"


# ── SUB-CHECK 2: Factual vs Emotional Content ───────────────────────────────
def _check_factual_vs_emotional_content(text: str) -> tuple:
    """
    Uses Gemini to assess whether the article is primarily FACTUAL
    (has real data, quotes, verifiable claims) or just EMOTIONAL
    (pure opinion, outrage, fear-mongering without substance).

    Returns (score 0-100, reason). 100 = all factual, 0 = pure emotional.
    """
    if not text:
        return 50, "Content integrity check unavailable -- treated as neutral"

    prompt = f"""
You are evaluating article content integrity for a Canadian misinformation detection tool.

Assess whether the following article presents factual, verifiable information,
or relies primarily on emotional appeals or sensational language with little factual substance.

Article text (first 1500 characters):
{text[:1500]}

Rate from 0 to 100 where:
- 100 = Entirely factual -- concrete data, events, quotes, verifiable claims
- 70 = Mostly factual with some opinion/editorial
- 50 = Equal mix of fact and emotional content
- 30 = Mostly emotional/opinion with few facts
- 0 = Pure emotional appeal -- no factual substance at all

Respond with ONLY valid JSON:
{{"score": <0-100>, "reason": "<2-3 short sentences explaining the content balance and any bias>"}}
"""

    result = call_gemini(prompt)
    if result and "score" in result:
        score = max(0, min(100, int(result["score"])))
        return score, result.get("reason", "Content integrity assessed")
    return 50, "Could not assess content integrity -- treated as neutral"


# ── SUB-CHECK 3: Image Integrity Flag ────────────────────────────────────────
def _flag_images(homepage_html: str) -> str:
    """
    If the page contains images, we flag this for the user as a
    recommended manual check. We can't do reverse image search
    automatically, but we can remind the user to do it.

    ITSAP.00.300 specifically says: "Conduct a reverse image search"

    Returns a flag message string (or "" if no images found).
    """
    if not homepage_html:
        return ""
    img_count = len(re.findall(r'<img', homepage_html.lower()))
    if img_count > 0:
        return f"({img_count} images detected -- manual reverse image search recommended per ITSAP.00.300)"
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
def analyze(article_data: dict) -> dict:
    """
    Runs all content integrity checks.

    Parameters:
        article_data: The dictionary from scraper.py

    Returns:
        {"score": 0-100, "reason": "explanation"}
    """
    text = article_data.get("text", "")
    homepage_html = article_data.get("homepage_html", "")

    # Run sub-checks
    design_score, design_reason = _check_design_markers(homepage_html)
    content_score, content_reason = _check_factual_vs_emotional_content(text)
    image_flag = _flag_images(homepage_html)

    # Combine — content quality gets higher weight since design check
    # only works when we have HTML
    final_score = int(round(
        design_score * 0.35 +
        content_score * 0.65
    ))

    # Pick the most important finding
    if design_score < 30:
        reason = design_reason
    else:
        reason = content_reason

    # Append image flag if relevant
    if image_flag:
        reason = f"{reason} {image_flag}"

    return {"score": final_score, "reason": reason}
