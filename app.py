"""
app.py — Verity Flask Web Server (the main entry point)
=========================================================

WHAT IS FLASK?
Flask is a Python library that turns your Python script into a web server.
A web server is a program that listens for requests from web browsers and
sends back web pages (HTML) or data (JSON).

Think of it like this:
  1. You type http://localhost:5000 in your browser
  2. Your browser sends a request to Flask
  3. Flask runs a Python function and sends back HTML (the webpage)
  4. Your browser displays it

HOW FLASK WORKS (the basics):
  - @app.route("/") means "when someone visits the homepage, run this function"
  - @app.route("/analyze") means "when someone sends data to /analyze, run this function"
  - request.get_json() reads JSON data sent by the browser
  - jsonify() converts a Python dict into JSON to send back to the browser
  - render_template() sends an HTML file to the browser

WHAT IS A REST API?
When the browser sends a POST request to /analyze with article data, and
Flask sends back JSON with the analysis results — that's a REST API.
It's how the frontend (HTML/CSS/JS) talks to the backend (Python).

HOW TO RUN THIS:
  python app.py
  Then open http://localhost:5000 in your browser

ROUTES IN THIS APP:
  GET  /         → Shows the Verity homepage (index.html)
  POST /analyze  → Takes a URL or text, runs all 6 criteria, returns scores
  GET  /history  → Returns the last 20 analyses from this session
"""

import os
from datetime import datetime, timezone
from collections import deque

# Flask is the web framework — it's what makes Python serve web pages
# - Flask: the main class that creates the web server
# - request: lets us read data sent by the browser
# - jsonify: converts Python dicts to JSON responses
# - render_template: sends HTML files from the templates/ folder
from flask import Flask, request, jsonify, render_template

# CORS = Cross-Origin Resource Sharing
# Without this, browsers block JavaScript from talking to our server
# because the browser thinks it might be a security risk
# (It's a browser safety feature — we disable it for local development)
from flask_cors import CORS

# Flask-Limiter caps how many requests a single visitor can make, so one
# user (or a script) can't hammer /analyze and burn through the Gemini quota
# or run up costs for everyone else.
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# python-dotenv reads API keys from our .env file
from dotenv import load_dotenv

# Our own files (these are the ones WE wrote):
import scraper   # scraper.py — extracts text from article URLs
import scorer    # scorer.py — runs all 6 criteria and calculates final score
from backboard_client import orchestrator  # Backboard multi-agent orchestrator

# Load API keys from .env file
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ── In-memory analysis history (last 20 analyses) ────────────────────────────
# In production this would use Backboard's persistent semantic memory.
# For the demo, this survives the session and showcases the caching concept.
_analysis_history: deque = deque(maxlen=20)

# ── Create the Flask app ─────────────────────────────────────────────────────
# Flask(__name__) creates a new web server
# __name__ is a Python variable that tells Flask where to find our files
app = Flask(__name__)

# Allow the browser's JavaScript to talk to our server
CORS(app)

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Storage defaults to in-process memory, which is fine for `python app.py`
# but does NOT share counters across multiple worker processes/instances
# (e.g. a multi-instance serverless deploy). For that, set RATELIMIT_STORAGE_URI
# to a shared backend, e.g. Redis/Upstash: redis://default:<pw>@<host>:<port>
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=["60 per minute", "1000 per day"],
)


@app.errorhandler(429)
def rate_limit_exceeded(e):
    """Matches the app's JSON error style instead of Flask-Limiter's default plain text."""
    return jsonify({"error": "Too many requests. Please slow down and try again shortly."}), 429


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE 1: Homepage
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    """
    This function runs when someone visits http://localhost:5000/
    It sends back the index.html file from the templates/ folder.

    In Flask, HTML files MUST be in a folder called 'templates/' —
    that's where render_template() looks for them.
    """
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE 2: Analyze an article
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/analyze", methods=["POST"])
@limiter.limit("6 per minute; 60 per hour")
def analyze():
    """
    This is the main analysis endpoint — the brain of Verity.

    HOW IT WORKS:
      1. The browser sends us JSON data: {"mode": "url", "input": "https://..."}
      2. We scrape the article or wrap the raw text
      3. We run all 6 criteria scorers (in parallel for speed)
      4. We send back JSON with the score, verdict, and breakdown

    methods=["POST"] means this route only accepts POST requests.
    (POST = sending data TO the server, GET = asking for data FROM the server)
    """
    try:
        # ── Read the data sent by the browser ─────────────────────────────
        # request.get_json() parses the JSON body from the browser's fetch() call
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        mode = data.get("mode", "url")          # "url" or "text"
        user_input = data.get("input", "").strip()  # the URL or article text

        if not user_input:
            return jsonify({"error": "No input provided"}), 400

        # ── Reject absurdly large payloads before they reach Gemini ────────
        # Protects API quota/cost from abuse; a real article is a few
        # thousand words, so 50k characters is generous headroom.
        MAX_INPUT_CHARS = 50_000
        if len(user_input) > MAX_INPUT_CHARS:
            return jsonify({
                "error": f"Input is too long ({len(user_input):,} characters). "
                         f"Please paste no more than {MAX_INPUT_CHARS:,} characters."
            }), 400

        # ── TEST BYPASS FOR NO-QUOTA DEMO ──────────────────────────────
        if user_input.strip().upper() == "TEST UNDETERMINABLE":
            return jsonify({
                "final_score": 0,
                "verdict": "Undeterminable",
                "verdict_subtext": "This content is inherently subjective or belief-based. Credibility cannot be objectively determined.",
                "verdict_class": "v-undeterminable",
                "is_undeterminable": True,
                "mdm_classification": "Unsustainable",
                "core_claim": "",
                "neutral_summary": "",
                "criteria": [
                    {"key": "domain", "label": "Website Trustworthiness", "score": "N/A", "reason": "Not applicable to subjective content."},
                    {"key": "emotional", "label": "Sensationalism & Clickbait", "score": "N/A", "reason": "Not applicable to subjective content."},
                    {"key": "factual", "label": "Fact-Checking & Accuracy", "score": "N/A", "reason": "Not applicable to subjective content."},
                    {"key": "author", "label": "Author Verifiability", "score": "N/A", "reason": "Not applicable to subjective content."},
                    {"key": "content", "label": "Content Quality", "score": "N/A", "reason": "Not applicable to subjective content."},
                    {"key": "mdm", "label": "Threat Classification", "score": "N/A", "reason": "Not applicable to subjective content."}
                ]
            })

        # ── Step 1: Get the article content ───────────────────────────────
        if mode == "url":
            # User pasted a URL → scrape the article from that website
            article_data = scraper.scrape_url(user_input)
        else:
            # User pasted raw text → wrap it in the same format
            article_data = scraper.scrape_text(user_input)

        # If we couldn't get ANY text at all, tell the user
        if not article_data.get("text") and not article_data.get("title"):
            return jsonify({
                "error": "Could not extract content from the provided URL. "
                         "Try pasting the article text instead."
            }), 422  # 422 = "I understood your request but can't process it"

        # ── Step 2: Run analysis via Backboard agents (or fallback) ──────
        # Try Backboard multi-agent orchestration first (semantic memory,
        # RAG, cross-session caching). Falls back to direct scorer if
        # Backboard is not configured or unavailable.
        result = orchestrator.run(article_data)
        if result is None:
            result = scorer.run_all(article_data)

        # Add some extra info for the frontend to display
        result["input_url"] = user_input if mode == "url" else ""
        result["article_title"] = article_data.get("title", "")
        result["scrape_error"] = article_data.get("error")

        # Save to history for the /history endpoint
        _analysis_history.appendleft({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": user_input if mode == "url" else "",
            "title": article_data.get("title", "Pasted text"),
            "verdict": result.get("verdict", ""),
            "verdict_class": result.get("verdict_class", "v-questionable"),
            "final_score": result.get("final_score", 0),
            "mdm_classification": result.get("mdm_classification", ""),
            "is_undeterminable": result.get("is_undeterminable", False)
        })

        # Send the result back to the browser as JSON
        # 200 = "OK, everything worked"
        return jsonify(result), 200

    except Exception as e:
        # If ANYTHING unexpected happens, return a friendly error
        # The app should NEVER crash during a demo — this is our safety net
        print(f"[ERROR] /analyze: {e}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500



# ══════════════════════════════════════════════════════════════════════════════
# ROUTE 4: Analysis history
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/history", methods=["GET"])
def history():
    """
    Returns the last 20 analyses from the in-memory history store.
    In production this would query Backboard's semantic memory for
    persistent cross-session results.
    """
    return jsonify(list(_analysis_history)), 200


# ══════════════════════════════════════════════════════════════════════════════
# START THE SERVER
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # __name__ == "__main__" means "only run this if you ran 'python app.py'"
    # (not if another file imported this file)

    print("=" * 60)
    print("Verity -- Canadian Misinformation Detection Tool")
    print("   Powered by Canadian Centre for Cyber Security (ITSAP.00.300)")
    print("   Running at: http://localhost:5001")
    print("=" * 60)

    # app.run() starts the web server
    # debug=True → auto-restarts when you save a file (great for development)
    # host="0.0.0.0" → allows access from other devices on the network
    # port=5000 → the server listens on port 5000
    app.run(debug=True, host="0.0.0.0", port=5001)
