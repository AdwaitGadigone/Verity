# Verity &mdash; Canadian Misinformation Detector 🇨🇦

Verity is an AI-powered tool designed to help Canadians identify misinformation, disinformation, and malinformation (MDM). It scores articles across 6 specific criteria derived from the **Canadian Centre for Cyber Security (ITSAP.00.300)** guidelines.

## 🚀 Features
- **AI-Powered Scoring**: Uses Google Gemini 2.0 Flash to analyze content and provide a nuanced credibility score (0-100).
- **Government Standards**: Built specifically around the official Canadian framework for identifying online threats.
- **Detailed Breakdown**: Explains exactly *why* a score was given across 6 key areas:
  - Website Trustworthiness
  - Sensationalism & Clickbait
  - Fact-Checking & Accuracy (with cross-source verification)
  - Author Verifiability
  - Content Quality
  - Threat Classification (MDM)
- **Audio Verdicts**: Uses ElevenLabs AI to read out the analysis for accessibility.
- **Trusted Source Boost**: Automatically recognizes and respects high-integrity domains like `.gc.ca`, `canada.ca`, and major Canadian news outlets.

## 🛠️ Tech Stack
- **Backend**: Python (Flask)
- **Frontend**: HTML5, Vanilla CSS, JavaScript
- **AI**: Google Gemini API, ElevenLabs API
- **Scraping**: Newspaper4k, BeautifulSoup4

## ⚙️ Setup & Installation

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd HackCanada
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory and add your API keys:
   ```env
   GEMINI_API_KEY_1=your_key_here
   GEMINI_API_KEY_2=your_second_key_here (optional backup)
   ELEVENLABS_API_KEY=your_key_here
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
- **Haroldina Koolaid**

---
*Disclaimer: This tool is for educational purposes. Always verify critical information with multiple official sources.*
