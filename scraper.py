"""
scraper.py — Article Content Extractor
========================================

WHAT DOES THIS FILE DO?
When a user gives us a URL, we need to actually go TO that website, download
the page, and pull out the useful parts: the headline, the article text,
the author's name, the publish date, and the domain name.

Think of it like copy-pasting an article, but automated.

LIBRARIES WE USE:
  - requests: A Python library for downloading web pages (like a browser
    but without the visual part — it just gets the raw HTML code)
  - BeautifulSoup (bs4): A library that reads HTML code and lets us search
    through it. HTML is the language web pages are written in.
  - newspaper4k: A smart library that can automatically find and extract
    article content from news websites. It knows where the title, author,
    and body text usually are on a news page.

HOW IT WORKS:
  1. Try newspaper4k first (it's the smartest — handles most news sites)
  2. If that fails, fall back to BeautifulSoup (simpler but more reliable)
  3. Also fetch the homepage HTML (used by other criteria to check for
     About Us / Contact pages)
"""

import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# newspaper4k is a library that specializes in extracting article content
# from news websites. It knows where to find the title, author, text, etc.
# We wrap the import in try/except in case it's not installed
try:
    from newspaper import Article
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False


def get_domain(url: str) -> str:
    """
    Extracts just the domain name from a full URL.

    Example:
      'https://www.cbc.ca/news/politics/some-article' → 'cbc.ca'

    urlparse() breaks a URL into parts:
      - scheme: 'https'
      - netloc: 'www.cbc.ca'  (the network location = domain)
      - path:   '/news/politics/some-article'

    We remove 'www.' because 'www.cbc.ca' and 'cbc.ca' are the same site.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    return domain


def scrape_url(url: str) -> dict:
    """
    Main scraping function: given a URL, downloads the page and extracts
    all the useful article information.

    Returns a dictionary (dict) with these keys:
      - title (str):        The article headline
      - text (str):         The full article body text
      - authors (list):     List of author names (may be empty)
      - publish_date (str): When the article was published (may be None)
      - domain (str):       The website domain (e.g. 'cbc.ca')
      - url (str):          The original URL the user gave us
      - homepage_html (str): Raw HTML of the site's homepage
      - error (str or None): Error message if scraping partially failed

    WHY A DICTIONARY?
    All 6 criterion modules expect the SAME data format. By putting everything
    in a dict, we can pass it to any criterion and it knows what to expect.
    """
    # Start with an empty result — we'll fill in what we can
    result = {
        "title": "",
        "text": "",
        "authors": [],
        "publish_date": None,
        "domain": get_domain(url),
        "url": url,
        "homepage_html": "",
        "error": None
    }

    # ── STEP 1: Try newspaper4k first (best for news sites) ──────────────
    # newspaper4k is smart — it can figure out where the article text is
    # on most news websites. It handles different layouts automatically.
    if NEWSPAPER_AVAILABLE:
        try:
            # Create an Article object for this URL
            article = Article(url)

            # Download the webpage HTML
            article.download()

            # Parse it — newspaper4k reads the HTML and extracts the parts
            article.parse()

            # Save what newspaper4k found
            result["title"] = article.title or ""
            result["text"] = article.text or ""
            result["authors"] = article.authors or []

            # Convert the date to a string if it exists
            # (newspaper4k returns a datetime object, we need a string)
            result["publish_date"] = (
                str(article.publish_date) if article.publish_date else None
            )

        except Exception as e:
            # newspaper4k failed — that's okay, we'll try BeautifulSoup next
            result["error"] = f"newspaper4k failed: {str(e)}"

    # ── STEP 2: If newspaper4k didn't get the text, try BeautifulSoup ────
    # BeautifulSoup is simpler but more reliable as a fallback.
    # It just reads ALL the paragraph tags (<p>) from the page.
    if not result["text"]:
        try:
            # Download the raw HTML of the page
            # User-Agent tells the website what "browser" is visiting
            # (some sites block requests without a User-Agent header)
            headers = {"User-Agent": "Mozilla/5.0 (compatible; VerityBot/1.0)"}
            response = requests.get(url, timeout=10, headers=headers)

            # Parse the HTML with BeautifulSoup
            # 'html.parser' is Python's built-in HTML reader
            soup = BeautifulSoup(response.text, "html.parser")

            # Try to get the title from the <title> tag
            if not result["title"] and soup.title:
                result["title"] = soup.title.string or ""

            # Find ALL <p> (paragraph) tags and combine their text
            # This gives us the article body text
            paragraphs = soup.find_all("p")
            result["text"] = " ".join(p.get_text() for p in paragraphs)

            # If BeautifulSoup got text, clear the error from Step 1
            if result["text"]:
                result["error"] = None

        except Exception as e:
            result["error"] = f"All scrapers failed: {str(e)}"

    # ── STEP 3: Fetch the homepage HTML ──────────────────────────────────
    # We need the homepage to check for About Us / Contact / Privacy pages
    # (used by criterion 1 and criterion 5)
    try:
        parsed = urlparse(url)
        homepage_url = f"{parsed.scheme}://{parsed.netloc}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; VerityBot/1.0)"}
        homepage_response = requests.get(homepage_url, timeout=8, headers=headers)
        result["homepage_html"] = homepage_response.text
    except Exception:
        result["homepage_html"] = ""

    return result


def scrape_text(text: str, title: str = "") -> dict:
    """
    When the user pastes raw text instead of a URL, we wrap it in the
    same dictionary format that scrape_url() returns.

    This way, all 6 criterion modules work the same way regardless of
    whether the input was a URL or pasted text.

    For pasted text, we don't have a domain, authors, or date — those
    criteria will just return neutral (middle) scores.
    """
    return {
        "title": title,
        "text": text,
        "authors": [],
        "publish_date": None,
        "domain": "",         # No domain when text is pasted directly
        "url": "",
        "homepage_html": "",
        "error": None
    }
