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

    # ── STEP 2: Extract text via BeautifulSoup if newspaper4k failed or returned too little text ─────
    if not result["text"] or len(result["text"]) < 250:
        try:
            # Use standard browser headers to bypass blockages (like Akamai on Hindustan Times)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
            response = requests.get(url, timeout=10, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")

            # Try to get the title from the <title> tag or og:title
            if not result["title"]:
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    result["title"] = og_title.get("content")
                elif soup.title:
                    result["title"] = soup.title.string or ""

            # Check for Access Denied or empty titles and fallback to URL slug
            current_title = str(result["title"]).lower() if result["title"] else ""
            if not current_title or "access denied" in current_title or "cloudflare" in current_title:
                import re
                from urllib.parse import unquote
                path = urlparse(url).path
                path = re.sub(r'/+$', '', path)
                slug = path.split('/')[-1]
                slug = re.sub(r'\.(html|php|aspx|jsp)$', '', slug, flags=re.IGNORECASE)
                slug = re.sub(r'-\d{6,}', '', slug)
                fallback_title = unquote(slug).replace('-', ' ').title()
                if fallback_title and len(fallback_title) > 3:
                    result["title"] = fallback_title

            # Find ALL <p> (paragraph) tags and combine their text
            paragraphs = soup.find_all("p")
            text_blocks = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
            
            # Many modern news sites (like Hindustan Times) put text in specific divs, not just <p> tags
            # HT uses "storyParagraph" and "detailPage" classes
            article_divs = soup.find_all("div", class_=lambda c: c and any(sub in str(c).lower() for sub in ["detail", "story", "article-body", "content", "storyparagraph"]))
            for div in article_divs:
                # Don't grab text from the whole massive page container, just the text blocks
                # We skip huge divs that contain the entire page wrapper by looking at string length
                div_text = div.get_text(separator=" ", strip=True)
                if div_text and 50 < len(div_text) < 5000 and div_text not in text_blocks:
                    text_blocks.append(div_text)
            
            # Overwrite the result text if we found more substantial content
            fresh_text = " ".join(text_blocks)
            if len(fresh_text) > len(result.get("text", "")):
                result["text"] = fresh_text
            
            # If text is still suspiciously short, use the meta description
            if len(result["text"]) < 200:
                og_desc = soup.find("meta", property="og:description")
                if og_desc and og_desc.get("content"):
                    desc = og_desc.get("content").strip()
                    if desc not in result["text"]:
                        result["text"] = desc + ". " + result["text"]

            if result["text"]:
                result["error"] = None
        except Exception as e:
            result["error"] = f"All scrapers failed: {str(e)}"
            
    # ── STEP 3: Fallback Author Extraction via HTML Meta Tags ────────────
    # Even if newspaper4k got the text, it often misses authors.
    # We always do a quick HTML parse to find author tags if they're missing.
    if not result["authors"]:
        try:
            # Use same bypass headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
            # Only fetch if we didn't already fetch it in Step 2
            if not result["text"]: 
                pass # Handled above
            else:
                response = requests.get(url, timeout=10, headers=headers)
                soup = BeautifulSoup(response.text, "html.parser")
                
            authors_found = []
            
            # Check for multiple tags of the same type (like multiple dc.creator tags)
            meta_names = ["author", "byl", "dc.creator"]
            for name in meta_names:
                tags = soup.find_all("meta", {"name": name})
                for tag in tags:
                    content = tag.get("content")
                    if content and content.strip() and content.strip() not in authors_found:
                        authors_found.append(content.strip())
            
            if not authors_found:
                # Also check property="article:author"
                tags = soup.find_all("meta", {"property": "article:author"})
                for tag in tags:
                    content = tag.get("content")
                    if content and content.strip() and content.strip() not in authors_found:
                        authors_found.append(content.strip())
                        
            if not authors_found:
                # Check rel="author" links or class="author" elements
                tags = soup.find_all("a", {"rel": "author"}) + \
                       soup.find_all(attrs={"class": lambda c: c and "author" in str(c).lower()})
                for tag in tags:
                    content = tag.get("content") or tag.get_text()
                    if content and content.strip() and content.strip() not in authors_found:
                        authors_found.append(content.strip())

            if authors_found:
                # Sometimes authors are comma-separated within a single tag
                final_authors = []
                for a in authors_found:
                    cleaned = a.replace(" and ", ",")
                    final_authors.extend([x.strip() for x in cleaned.split(",") if x.strip()])
                result["authors"] = list(dict.fromkeys(final_authors)) # remove duplicates
        except Exception:
            pass


    # ── STEP 3: Fetch the homepage HTML ──────────────────────────────────
    # We need the homepage to check for About Us / Contact / Privacy pages
    # (used by criterion 1 and criterion 5)
    try:
        parsed = urlparse(url)
        homepage_url = f"{parsed.scheme}://{parsed.netloc}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        homepage_response = requests.get(homepage_url, timeout=8, headers=headers)
        result["homepage_html"] = homepage_response.text
    except Exception:
        result["homepage_html"] = ""

    # Truncate to prevent token exhaustion on our LLM APIs
    if result.get("text"):
        result["text"] = result["text"][:4000]
    if result.get("title"):
        result["title"] = result["title"][:300]
        
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
