"""
criterion1_domain.py — Domain & Publisher Credibility
======================================================
WEIGHT: 20% of the final score

WHAT IS THIS CRITERION?
This checks whether the WEBSITE ITSELF is trustworthy, before we even
look at the article content. It's like checking the reputation of the
newspaper before reading the article.

Based on ITSAP.00.300 (Canadian Centre for Cyber Security):
  - "Verify domain names to ensure they match the organization"
  - "Perform a WHOIS lookup to verify domain ownership and registration age"
  - "Check that the organization has contact information and an About Us page"

WHAT IT CHECKS (5 sub-checks):
  1. TLD trust — is the domain .gc.ca (government), .ca, or .xyz (suspicious)?
  2. Domain age — how old is this website? New domains are a red flag.
  3. Typosquatting — is this domain pretending to be a real outlet? (e.g. cbcnews.co)
  4. MBFC lookup — is this publisher in our credibility database?
  5. Contact pages — does the site have About Us / Contact / Privacy pages?

WHAT IS WHOIS?
WHOIS is a public database that stores who registered a domain name and when.
We use the python-whois library to look this up automatically.

WHAT IS MBFC?
Media Bias Fact Check is a respected organization that rates news outlets
on their factual reporting history. We use a local copy of their data
(mbfc_data.json) so we don't need an external API for this.
"""

import json
import os
import whois
from datetime import datetime, timezone
from bs4 import BeautifulSoup


# ══════════════════════════════════════════════════════════════════════════════
# LOAD THE MBFC DATASET
# This runs ONCE when the app starts — it reads mbfc_data.json and builds
# a lookup dictionary so we can quickly check any domain
# ══════════════════════════════════════════════════════════════════════════════
_MBFC_PATH = os.path.join(os.path.dirname(__file__), "..", "mbfc_data.json")
try:
    with open(_MBFC_PATH, "r") as f:
        _mbfc_raw = json.load(f)
    # Build a dict: domain → outlet info, for fast lookups
    # Example: {"cbc.ca": {"factual_reporting": "HIGH", ...}}
    MBFC_INDEX = {entry["domain"]: entry for entry in _mbfc_raw["outlets"]}
except Exception:
    MBFC_INDEX = {}


# ══════════════════════════════════════════════════════════════════════════════
# KNOWN LEGITIMATE CANADIAN NEWS DOMAINS (for typosquatting detection)
# If someone registers "cbcnewz.co" to impersonate CBC, we want to catch that
# ══════════════════════════════════════════════════════════════════════════════
KNOWN_CANADIAN_DOMAINS = [
    "cbc.ca", "ctvnews.ca", "ctv.ca", "theglobeandmail.com",
    "nationalpost.com", "thestar.com", "torontostar.com", "globalnews.ca",
    "montrealgazette.com", "ottawacitizen.com", "vancouversun.com",
    "calgaryherald.com", "edmontonjournal.com", "winnipegfreepress.com",
    "macleans.ca", "lapresse.ca", "ledevoir.com", "thetyee.ca",
    "ipolitics.ca", "journaldequebec.com", "thechronicleherald.ca",
    # Government & public institutions (always trusted)
    "canada.ca", "gc.ca", "statcan.gc.ca", "healthcanada.gc.ca",
    "parl.gc.ca", "rcmp-grc.gc.ca", "canada.ca",
]


# ══════════════════════════════════════════════════════════════════════════════
# TLD TRUST SCORES
# TLD = Top-Level Domain (the last part of a domain, like .ca or .com)
# Government domains (.gc.ca) are most trustworthy
# Sketchy TLDs like .xyz are often used by fake news sites
# ══════════════════════════════════════════════════════════════════════════════
TLD_SCORES = {
    "gc.ca": 100,    # Official Canadian federal government
    "gov.ca": 100,   # Provincial government
    "ca": 75,        # Canadian domain
    "com": 60,       # Neutral — used by everyone
    "org": 60,       # Often non-profits
    "net": 40,       # Slightly suspicious
    "info": 20,      # Often used by fake news sites
    "co": 20,        # Often used to mimic .com sites
    "xyz": 10,       # Very suspicious
    "online": 10,
    "news": 35,
    "site": 15,
    "click": 10,
    "top": 10,
}


# ── SUB-CHECK 1: TLD Trust Score ─────────────────────────────────────────────
def _get_tld_score(domain: str) -> tuple:
    """
    Scores the domain based on its top-level domain (TLD).
    .gc.ca gets 100, .com gets 60, .xyz gets 10.
    Returns (score, reason).
    """
    # Special check for Canadian government domains
    if domain.endswith(".gc.ca") or domain == "gc.ca":
        return 100, "Government of Canada domain (.gc.ca) -- highest trust level"
    if domain.endswith(".canada.ca") or domain == "canada.ca":
        return 100, "Official Canada government domain -- highest trust level"

    # Get the TLD (last part after the dot)
    parts = domain.split(".")
    tld = parts[-1].lower()
    score = TLD_SCORES.get(tld, 50)  # Default 50 for unknown TLDs

    if score >= 75:
        reason = f"Trustworthy TLD (.{tld})"
    elif score >= 50:
        reason = f"Neutral TLD (.{tld}) -- common for legitimate sites"
    elif score >= 25:
        reason = f"Suspicious TLD (.{tld}) -- frequently used by low-credibility sites"
    else:
        reason = f"High-risk TLD (.{tld}) -- commonly used by fake news sites"

    return score, reason


# ── SUB-CHECK 2: Domain Age via WHOIS ────────────────────────────────────────
def _get_domain_age_score(domain: str) -> tuple:
    """
    Uses WHOIS to find out how old the domain is.
    Newer domains are more suspicious — a brand-new website claiming to be
    a news outlet is a major red flag.
    Returns (score, reason).
    """
    try:
        # whois.whois() sends a query to the public WHOIS database
        w = whois.whois(domain)
        creation_date = w.creation_date

        # WHOIS sometimes returns a list of dates — take the earliest one
        if isinstance(creation_date, list):
            creation_date = creation_date[0]

        if creation_date is None:
            return 40, "Could not determine domain registration date"

        # Make the date timezone-aware for comparison
        if creation_date.tzinfo is None:
            creation_date = creation_date.replace(tzinfo=timezone.utc)

        # Calculate how old the domain is
        now = datetime.now(timezone.utc)
        age_days = (now - creation_date).days
        age_years = age_days / 365.25

        # Score based on age
        if age_years < 0.5:
            return 5, f"Domain registered only {age_days} days ago -- major red flag"
        elif age_years < 1:
            return 20, f"Domain registered {age_days} days ago (under 1 year) -- red flag"
        elif age_years < 2:
            return 50, f"Domain is {age_years:.1f} years old -- relatively new"
        elif age_years < 5:
            return 75, f"Domain is {age_years:.1f} years old -- established"
        else:
            return 90, f"Domain is {age_years:.1f} years old -- long-standing"

    except Exception:
        return 40, "Could not perform WHOIS lookup -- domain age unknown"


# ── SUB-CHECK 3: Typosquatting Detection ─────────────────────────────────────
def _get_typosquatting_score(domain: str) -> tuple:
    """
    Checks if the domain looks like a FAKE version of a real Canadian outlet.

    Example: 'cbcnews.co' contains 'cbc' but isn't 'cbc.ca' — suspicious!

    WHAT IS TYPOSQUATTING?
    It's when someone registers a domain that looks very similar to a real one,
    hoping people won't notice the difference. Like "gogle.com" vs "google.com".

    Returns (score, reason).
    """
    domain_lower = domain.lower()

    # If it exactly matches a known outlet, it's legit
    if domain_lower in KNOWN_CANADIAN_DOMAINS:
        return 100, "Domain matches known legitimate Canadian outlet"

    # Check if the domain CONTAINS a known outlet's name but ISN'T the real one
    for known in KNOWN_CANADIAN_DOMAINS:
        known_name = known.split(".")[0]  # e.g. 'cbc' from 'cbc.ca'
        if known_name in domain_lower and domain_lower != known:
            return 15, f"Domain appears to mimic '{known}' -- possible typosquatting"

    # No mimicry detected — neutral score
    return 70, "No typosquatting pattern detected"


# ── SUB-CHECK 4: MBFC Database Lookup ────────────────────────────────────────
def _get_mbfc_score(domain: str) -> tuple:
    """
    Checks our local MBFC (Media Bias Fact Check) dataset to see if this
    publisher has been rated for factual reporting.

    If MBFC rates them as "VERY HIGH" → great. If "VERY LOW" → very bad.
    If not in the database → neutral (we just don't have data on them).

    Returns (score, reason).
    """
    if not MBFC_INDEX:
        return 50, "MBFC dataset unavailable -- publisher reputation unverifiable"

    # Look up the domain in our dataset
    outlet = MBFC_INDEX.get(domain) or MBFC_INDEX.get(domain.replace("www.", ""))

    if not outlet:
        return 50, "Publisher not found in MBFC credibility database"

    # Map MBFC ratings to our 0-100 score
    factual = outlet.get("factual_reporting", "UNKNOWN").upper()
    score_map = {
        "VERY HIGH": 100,
        "HIGH": 85,
        "MOSTLY FACTUAL": 65,
        "MIXED": 45,
        "LOW": 20,
        "VERY LOW": 5,
        "CONSPIRACY": 0,
        "PSEUDOSCIENCE": 0,
        "SATIRE": 40,
    }

    score = score_map.get(factual, 50)
    return score, f"MBFC rates this publisher's factual reporting as '{factual}'"


# ── SUB-CHECK 5: Contact Page Presence ───────────────────────────────────────
def _get_contact_score(homepage_html: str) -> tuple:
    """
    Checks the homepage for About Us, Contact, and Privacy Policy links.
    Legitimate news outlets ALWAYS have these pages. Missing contact info
    is a red flag per ITSAP.00.300.

    Returns (score, reason).
    """
    if not homepage_html:
        return 50, "Could not access homepage to verify contact information"

    html_lower = homepage_html.lower()

    # Check for each trust signal
    has_about = "about us" in html_lower or "about-us" in html_lower
    has_contact = "contact" in html_lower
    has_privacy = "privacy" in html_lower

    signals_found = sum([has_about, has_contact, has_privacy])

    if signals_found == 3:
        return 90, "Homepage has About Us, Contact, and Privacy pages -- good transparency"
    elif signals_found == 2:
        return 70, "Homepage has some transparency pages but is missing one"
    elif signals_found == 1:
        return 40, "Homepage has limited contact/transparency information"
    else:
        return 10, "No About Us, Contact, or Privacy page found -- red flag"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — called by scorer.py
# ══════════════════════════════════════════════════════════════════════════════
# ── Domains that always get a perfect score ─────────────────────────────────
# These are official Canadian government domains. They ARE the source of
# truth for Canadian government information and cannot be misinformation.
GOVERNMENT_DOMAINS = [
    ".gc.ca", ".canada.ca", ".parl.gc.ca", ".statcan.gc.ca",
    ".healthcanada.gc.ca", ".rcmp-grc.gc.ca", ".forces.gc.ca",
]


def analyze(domain: str, homepage_html: str = "") -> dict:
    """
    Runs all 5 domain checks and combines them into a single 0-100 score.

    Parameters:
        domain: The website domain (e.g. 'cbc.ca')
        homepage_html: The raw HTML of the site's homepage

    Returns:
        {"score": 0-100, "reason": "2-3 short sentences explaining the domain assessment"}
    """
    # ── GOVERNMENT DOMAIN SHORT-CIRCUIT ──────────────────────────────────────
    # Official Canadian Government domains (.gc.ca, .canada.ca) automatically
    # receive a perfect domain score. There is no need to check domain age,
    # MBFC ratings, or contact pages for government websites.
    domain_lower = domain.lower()
    for gov in GOVERNMENT_DOMAINS:
        if domain_lower.endswith(gov) or domain_lower == gov.lstrip("."):
            return {
                "score": 100,
                "reason": f"Official Government of Canada domain ({domain}). "
                          f"Government of Canada sites are verified authoritative sources "
                          f"per ITSAP.00.300."
            }
    # CBC is Canada's national public broadcaster — treat as high credibility
    if domain_lower in ("cbc.ca", "www.cbc.ca"):
        return {
            "score": 95,
            "reason": "Canadian Broadcasting Corporation (CBC) — Canada's national public broadcaster. "
                      "MBFC rates CBC as HIGH factual reporting."
        }

    # Run all 5 sub-checks
    tld_score, tld_reason = _get_tld_score(domain)
    age_score, age_reason = _get_domain_age_score(domain)
    typo_score, typo_reason = _get_typosquatting_score(domain)
    mbfc_score, mbfc_reason = _get_mbfc_score(domain)
    contact_score, contact_reason = _get_contact_score(homepage_html)

    # Combine with weights (MBFC and age are most reliable)
    final_score = int(round(
        tld_score * 0.15 +
        age_score * 0.30 +
        typo_score * 0.20 +
        mbfc_score * 0.25 +
        contact_score * 0.10
    ))

    # Pick the most important finding as the displayed reason
    if typo_score < 30:
        reason = typo_reason
    elif mbfc_score <= 20:
        reason = mbfc_reason
    elif age_score <= 20:
        reason = age_reason
    elif mbfc_score >= 80:
        reason = f"{mbfc_reason}. {age_reason}."
    else:
        reason = f"{age_reason}. {contact_reason}."

    return {"score": final_score, "reason": reason}
