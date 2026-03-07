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
  POST /speak    → Takes verdict text, returns audio from ElevenLabs
"""

import os
import json
from datetime import datetime, timezone
from collections import deque

# Flask is the web framework — it's what makes Python serve web pages
# - Flask: the main class that creates the web server
# - request: lets us read data sent by the browser
# - jsonify: converts Python dicts to JSON responses
# - render_template: sends HTML files from the templates/ folder
# - Response: lets us send raw bytes (used for audio)
from flask import Flask, request, jsonify, render_template, Response

# CORS = Cross-Origin Resource Sharing
# Without this, browsers block JavaScript from talking to our server
# because the browser thinks it might be a security risk
# (It's a browser safety feature — we disable it for local development)
from flask_cors import CORS

# python-dotenv reads API keys from our .env file
from dotenv import load_dotenv

# Our own files (these are the ones WE wrote):
import scraper   # scraper.py — extracts text from article URLs
import scorer    # scorer.py — runs all 6 criteria and calculates final score
from backboard_client import orchestrator  # Backboard multi-agent orchestrator

# Load API keys from .env file
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

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
            "verdict_class": result.get("verdict_class", "v-uncertain"),
            "final_score": result.get("final_score", 0),
            "mdm_classification": result.get("mdm_classification", ""),
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
# ROUTE 3: Text-to-speech (ElevenLabs)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/speak", methods=["POST"])
def speak():
    """
    This endpoint converts text to speech using ElevenLabs AI.

    HOW IT WORKS:
      1. The browser sends us JSON: {"text": "Verity analysis complete..."}
      2. We send that text to ElevenLabs' API
      3. ElevenLabs sends back audio (MP3 bytes)
      4. We send those audio bytes to the browser
      5. The browser plays the audio

    WHAT IS ELEVENLABS?
    ElevenLabs is an AI company that generates realistic human-sounding speech.
    We use it for the "Read Verdict Aloud" button — it reads the analysis
    results to the user in a natural voice.
    """
    if not ELEVENLABS_API_KEY:
        return jsonify({"error": "ElevenLabs API key not configured"}), 503

    try:
        data = request.get_json()
        text = data.get("text", "")

        if not text:
            return jsonify({"error": "No text provided"}), 400

        # Import the ElevenLabs SDK (their Python library)
        # We import it here instead of at the top because it's only used
        # for this one feature, and the app still works without it
        from elevenlabs import ElevenLabs

        # Create a connection to ElevenLabs using our API key
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        # Generate speech from text
        # - voice_id: "George" — a deep, authoritative voice that sounds
        #   professional for a fact-checking tool
        # - model_id: "eleven_multilingual_v2" — their best quality model
        # - output_format: MP3 audio at 44100 Hz, 128 kbps
        audio_generator = client.text_to_speech.convert(
            voice_id="JBFqnCBsd6RMkjVDRZzb",  # "George" voice
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        # The generator gives us audio in chunks — join them into one blob
        # b"" is an empty bytes object, and b"".join() combines byte chunks
        audio_bytes = b"".join(audio_generator)

        # Send the MP3 audio back to the browser
        # Response() lets us send raw bytes with the right content type
        return Response(
            audio_bytes,
            mimetype="audio/mpeg",  # tells the browser "this is an MP3 file"
            headers={"Content-Disposition": "inline; filename=verdict.mp3"}
        )

    except Exception as e:
        print(f"[ERROR] /speak: {e}")
        return jsonify({"error": f"Text-to-speech failed: {str(e)}"}), 500


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
# ROUTE 5: Conversational explain (for follow-up voice questions)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/explain", methods=["POST"])
def explain():
    """
    Generates a focused spoken explanation answering a follow-up question
    about the analysis, then converts it to ElevenLabs audio.

    question_type options:
      "why_flagged"   — explains the worst-scoring criterion in detail
      "what_check"    — gives specific verification recommendations
      "compare"       — how this outlet has performed historically
    """
    if not ELEVENLABS_API_KEY:
        return jsonify({"error": "ElevenLabs API key not configured"}), 503

    try:
        data = request.get_json()
        question_type = data.get("question_type", "why_flagged")
        verdict_data = data.get("verdict_data", {})

        criteria = verdict_data.get("criteria", [])
        verdict = verdict_data.get("verdict", "Uncertain")
        final_score = verdict_data.get("final_score", 50)
        mdm = verdict_data.get("mdm_classification", "Unsustainable")

        # Find weakest and strongest criteria
        weakest = min(criteria, key=lambda c: c["score"]) if criteria else None
        strongest = max(criteria, key=lambda c: c["score"]) if criteria else None

        if question_type == "why_flagged":
            if weakest:
                speech_text = (
                    f"The biggest concern is {weakest['label']}, which scored "
                    f"{weakest['score']} out of 100. {weakest['reason']} "
                    f"This is weighted at {weakest['weight']} of the total score, "
                    f"making it a significant factor in the overall {verdict} rating."
                )
            else:
                speech_text = f"This content scored {final_score} out of 100. No specific criterion data is available."

        elif question_type == "what_check":
            checks = []
            for c in sorted(criteria, key=lambda x: x["score"])[:3]:
                checks.append(f"For {c['label']}: {c['reason']}")
            speech_text = (
                "Here are the top things to verify before sharing this content. "
                + " ".join(checks) + " "
                "Always cross-reference with CBC, Globe and Mail, or official government sources."
            )

        elif question_type == "compare":
            if strongest:
                speech_text = (
                    f"The strongest signal for this content is {strongest['label']}, "
                    f"scoring {strongest['score']} out of 100. {strongest['reason']} "
                    f"Overall, this content is classified as {mdm} under the "
                    f"Canadian Centre for Cyber Security framework."
                )
            else:
                speech_text = f"This content is classified as {mdm} with a score of {final_score} out of 100."
        else:
            speech_text = f"This content scored {final_score} out of 100 and is rated {verdict}."

        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio_generator = client.text_to_speech.convert(
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            text=speech_text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        audio_bytes = b"".join(audio_generator)
        return Response(audio_bytes, mimetype="audio/mpeg",
                        headers={"Content-Disposition": "inline; filename=explain.mp3"})

    except Exception as e:
        print(f"[ERROR] /explain: {e}")
        return jsonify({"error": f"Explain failed: {str(e)}"}), 500


# ══════════════════════════════════════════════════════════════════════════════
# START THE SERVER
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # __name__ == "__main__" means "only run this if you ran 'python app.py'"
    # (not if another file imported this file)

    print("=" * 60)
    print("Verity -- Canadian Misinformation Detection Tool")
    print("   Powered by Canadian Centre for Cyber Security (ITSAP.00.300)")
    print("   Running at: http://localhost:5000")
    print("=" * 60)

    # app.run() starts the web server
    # debug=True → auto-restarts when you save a file (great for development)
    # host="0.0.0.0" → allows access from other devices on the network
    # port=5000 → the server listens on port 5000
    app.run(debug=True, host="0.0.0.0", port=5000)
