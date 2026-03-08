# Verity &mdash; Canadian Misinformation Detector 🇨🇦

Verity is an AI-powered credibility analysis tool designed to help Canadians evaluate news articles and identify misinformation, disinformation, and malinformation (MDM). It scores content across 6 specific criteria directly derived from the **Canadian Centre for Cyber Security (ITSAP.00.300)** guidelines.

## 🚀 Features
- **AI-Powered Analysis**: Uses Google Gemini 2.0 Flash (with Groq and Grok fallbacks) to analyze content and calculate a nuanced credibility score (0-100).
- **Government Standards**: Built specifically around the official Canadian framework for assessing digital threats.
- **Multi-Agent Orchestration & Memory**: Integrates with Backboard.io to deploy specialized agents (Coordinator, Analysis, Fact, Judge). This enables cross-session semantic memory caching and Retrieval-Augmented Generation (RAG) against the ITSAP framework and Media Bias Fact Check (MBFC) data.
- **Detailed Breakdown**: Explains exactly *why* a score was given across 6 key areas:
  - **Website Trustworthiness**: Evaluates if the outlet has a history of publishing fake news, satire, or reliable journalism.
  - **Sensationalism & Clickbait**: Analyzes the emotional tone of the article to detect outrage, fear-mongering, or misleading headlines designed for clicks.
  - **Fact-Checking & Accuracy**: Extracts the main factual claim of the article and cross-references it with known facts.
  - **Author Verifiability**: Checks if the article is written by a real, credentialed journalist with a verifiable track record.
  - **Content Quality**: Looks at the structure of the writing, checking if it cites sources or relies purely on emotional appeals.
  - **Threat Classification (MDM Framework)**: Classifies the article into one of Canada's official digital threat categories:
    - **Valid**: Factually correct reporting from a credible source.
    - **Misinformation**: False information that is *not* intentional (e.g., an honest mistake or outdated statistic).
    - **Disinformation**: Information that is deliberately fabricated to deceive people.
    - **Malinformation**: Information based in reality, but exaggerated or taken out of context to mislead or cause harm.
    - **Unsustainable**: Claims that cannot be objectively verified or disproved (like pure opinions).
- **Audio & Conversational Follow-ups**: Uses ElevenLabs AI to read out verdicts, neutral summaries, and answer specific follow-up questions about the credibility analysis.
- **Trusted Source Boost**: Automatically recognizes and respects high-integrity Canadian institutional domains (e.g., `.gc.ca`, `canada.ca`, `cbc.ca`, `theglobeandmail.com`) and applies contextual scoring adjustments.

## 🧠 Codebase Architecture Guide

Verity handles complex operations through a streamlined, parallel-processing architecture designed to minimize API calls and maximize speed.

### Backend Routing & Orchestration (Python / Flask)
- **`app.py`**: The main Flask server application. It exposes REST API endpoints (`/analyze`, `/speak`, `/explain`, `/history`), routing requests from the web interface to the analysis pipeline and Text-to-Speech services.
- **`backboard_client.py`**: Manages our multi-agent framework via Backboard.io. It creates persistent agents, uploads RAG documents (MBFC lists and ITSAP guidelines), and handles an in-process memory cache to instantly retrieve past analyses without hitting LLM APIs again.
- **`scorer.py`**: The parallel execution engine. It simultaneously runs all 6 criteria using a `ThreadPoolExecutor`. It applies mathematical weighting, structural "boosts" for trusted Canadian domains, identifies inherently unverifiable content (e.g., pure opinion/religion), and calculates the final verdict tier.

### AI Integration & Analysis (`/analyzers`)
- **`gemini_client.py`**: The core AI bridge. Instead of making 6 separate API calls, it implements a `prime_mega_cache` function. This sends one massive structured prompt to Gemini to analyze criteria 2-6 simultaneously, returning a single JSON response. It cycles through API keys automatically and falls back to Groq (Llama 3.3) or Grok (xAI) if Google's quota is exhausted.
- **`/analyzers/*`**: Individual modular scripts for specific tests:
  - `criterion1_domain.py`: Rule-based checks on whether the domain is known for fake news, satire, or institutional trust.
  - `criterion2_emotional.py` to `criterion6_mdm.py`: Dedicated logic that extracts specific insights from the `gemini_client` mega-cache and handles specialized checks (like publication date recency in the factual criteria).
- **`scraper.py`**: The content extraction utility. Combines `newspaper4k`, `beautifulsoup4`, and `requests` to download raw HTML, bypass popups, and extract clean article text, headlines, authors, and publish dates so the AI has pure data to work with.

### Frontend Interface (HTML / CSS / JS)
- **`templates/index.html`**: A clean, single-page application structure. It includes a custom built SVG credibility gauge, tabbed interfaces for URL vs. Text inputs, and specialized components for displaying MDM classification pills and follow-up prompts.
- **`static/style.css`**: Completely custom Vanilla CSS. Employs a specific "warm cream" color palette to evoke an authoritative, editorial feel rather than a typical SaaS application. Uses CSS variables and flex/grid layouts.
- **`static/script.js`**: The interactive client layer. Manages asynchronous fetch calls, smoothly animates the score gauge via `requestAnimationFrame`, populates the Recent Analyses history, and orchestrates ElevenLabs audio playback.

## 🛠️ Tech Stack
- **Backend**: Python, Flask, ThreadPoolExecutor
- **AI & Orchestration**: Google `google-genai` SDK, Backboard.io SDK, Groq/OpenAI compatible APIs
- **Text-to-Speech**: ElevenLabs API
- **Scraping**: `newspaper4k`, `BeautifulSoup4`, `urllib`
- **Frontend**: HTML5, Vanilla CSS, Vanilla JavaScript

## ⚙️ Setup & Installation

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd Verity
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory and add your API keys:
   ```env
   # TruthLens API Keys
   # These are shared among all team members
   GEMINI_API_KEY_1=your_key_here
   GEMINI_API_KEY_2=your_second_key_here
   ELEVENLABS_API_KEY=your_key_here
   BACKBOARD_API_KEY=your_key_here
   GROQ_API_KEY=your_key_here
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```
   Open `http://localhost:5000` in your browser.

## 👥 Meet the Team
Developed for **Hack Canada 2026** by:
- **Adwait Gadigone**
- **Hasan Naqvi**
- **Hari Kolla**

---
*Disclaimer: This tool is for educational purposes. Always verify critical information with multiple official sources.*
