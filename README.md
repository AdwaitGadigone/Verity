# Verity &mdash; Canadian Misinformation Detector 🇨🇦

Verity is an AI-powered credibility analysis tool built for Canadians. It evaluates news articles and identifies misinformation, disinformation, and malinformation (MDM) using the **Canadian Centre for Cyber Security (ITSAP.00.300)** guidelines.

## 🚀 How It Works
- **Instant Analysis**: Submit a URL or paste text to get a Nuanced Credibility Score (0-100) instantly.
- **Undeterminable Content Detection**: Automatically flags subjective, opinionated, or religious content. If credibility cannot be objectively verified, Verity refuses to guess and explicitly scores it as **N/A**.
- **Audio Verdicts**: Uses ElevenLabs AI to read explanations and neutral summaries out loud.
- **Smart Memory**: Remembers past articles to save time and API quota.

## 📊 The 6 Verification Criteria

Verity explicitly breaks down the credibility of any article across these 6 areas:

1. **Website Trustworthiness**: Is the domain a known satirical site, a frequent publisher of fake news, or a highly trusted Canadian institution (like `.gc.ca` or `cbc.ca`)?
2. **Sensationalism & Clickbait**: Does the article use emotionally manipulative language, fear tactics, or heavily exaggerated headlines designed purely for clicks?
3. **Fact-Checking & Accuracy**: What is the core claim of the article? Can that specific claim be verified by other reputable sources? 
4. **Author Verifiability**: Is there a named author? If so, are they a credentialed, identifiable journalist with a clean track record?
5. **Content Quality**: Is the article well-written? Does it cite primary sources, or does it rely entirely on unsupported claims and poor formatting?
6. **Threat Classification (MDM Framework)**: Under official Canadian guidelines, how is this threat categorized?
   - **Valid**: Factually correct reporting from a credible source.
   - **Misinformation**: False information that is *not* intentional (e.g., an honest mistake or outdated statistic).
   - **Disinformation**: Information that is deliberately fabricated to deceive people.
   - **Malinformation**: Information based in reality, but exaggerated or taken out of context to mislead or cause harm.
   - **Unsustainable**: Claims that cannot be objectively verified or disproved (like pure opinions).

---

## 🛠️ Tech Stack
- **Backend**: Python, Flask
- **AI**: Google Gemini 2.0 Flash (Logic), ElevenLabs (Voice)
- **AI Orchestration**: Backboard.io (Agents & RAG Memory)
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
   GEMINI_API_KEY_3=your_third_key_here
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
