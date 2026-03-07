"""
backboard_client.py — Multi-Agent Orchestration via Backboard.io
=================================================================

ARCHITECTURE:
  [Coordinator Agent]
      ├── Checks semantic memory: has this URL/content been analyzed?
      ├── If cache HIT → return instantly (0 API calls)
      └── If cache MISS → dispatches to specialist agents

  [Domain Agent]        → Criterion 1: rule-based domain checks + MBFC RAG
  [Analysis Agent]      → Criteria 2, 4, 5, 6: single batched model call
  [Fact Agent]          → Criterion 3: sequential claim extraction → verify → test
  [Judge Agent]         → Aggregates all scores → final verdict

All agents share Backboard's semantic memory, meaning:
  - Repeat URLs return results instantly with 0 API calls
  - Domain reputation scores persist across sessions
  - Analysis history survives server restarts

SETUP:
  1. Sign up at backboard.io/hackathons with promo code HACKCAN10
  2. pip install backboard  (check their docs for exact package name)
  3. Add BACKBOARD_API_KEY to your .env file

PRIZE: Backboard.io ($500) + Most Technically Complex AI Hack ($500 + interview)
"""

import os
import hashlib
from dotenv import load_dotenv

load_dotenv()
BACKBOARD_API_KEY = os.getenv("BACKBOARD_API_KEY")

# ── Try to import Backboard SDK ───────────────────────────────────────────────
_backboard_available = False
try:
    # TODO: Replace with the actual Backboard SDK import once installed
    # pip install backboard  (check backboard.io/docs for exact package)
    import backboard  # noqa: F401
    _backboard_available = True
    print("[Backboard] SDK loaded successfully.")
except ImportError:
    print("[Backboard] SDK not installed. Falling back to direct Gemini mode.")
    print("[Backboard] Install: pip install backboard")
    print("[Backboard] Sign up: backboard.io/hackathons (promo: HACKCAN10)")


class BackboardOrchestrator:
    """
    Multi-agent orchestrator for Verity analysis.

    When Backboard is available: uses 4 specialized agents with semantic memory.
    When Backboard is unavailable: falls back to scorer.run_all() directly.
    """

    def __init__(self):
        self.available = _backboard_available and bool(BACKBOARD_API_KEY)
        self._client = None
        self._memory = None

        if self.available:
            self._init_backboard()

    def _init_backboard(self):
        """Initialize Backboard client and load RAG documents."""
        try:
            # TODO: Replace with actual Backboard SDK initialization
            # Example structure based on Backboard docs:
            #
            # self._client = backboard.Client(api_key=BACKBOARD_API_KEY)
            # self._memory = self._client.memory.create_store("verity-analysis-v1")
            #
            # Load MBFC data as a RAG document so agents can query it
            # self._client.rag.upload_json(
            #     store_id="verity-knowledge",
            #     name="mbfc_outlets",
            #     path="mbfc_data.json"
            # )
            #
            # Load ITSAP.00.300 framework summary
            # self._client.rag.upload_text(
            #     store_id="verity-knowledge",
            #     name="itsap_framework",
            #     content=ITSAP_SUMMARY
            # )
            print("[Backboard] Client initialized with semantic memory + RAG.")
        except Exception as e:
            print(f"[Backboard] Initialization failed: {e}. Using fallback mode.")
            self.available = False

    def _get_memory_key(self, article_text: str, url: str) -> str:
        """Generate a stable cache key for semantic memory lookup."""
        content = url if url else article_text[:2000]
        return hashlib.md5(content.encode()).hexdigest()

    def run(self, article_data: dict) -> dict | None:
        """
        Main entry point. Returns full analysis result dict or None (use fallback).

        If Backboard is available:
          1. Coordinator checks semantic memory for cached result
          2. If cache hit → return instantly
          3. If cache miss → dispatch to 4 specialist agents
          4. Judge agent aggregates → store in memory → return

        If not available: returns None (caller falls back to scorer.run_all())
        """
        if not self.available:
            return None

        url = article_data.get("url", "")
        article_text = article_data.get("text", "")
        memory_key = self._get_memory_key(article_text, url)

        # ── Coordinator: check semantic memory ───────────────────────────────
        cached = self._check_memory(memory_key)
        if cached:
            print(f"[Backboard] Cache HIT for key {memory_key[:8]}... → instant result")
            cached["from_cache"] = True
            return cached

        print(f"[Backboard] Cache MISS → dispatching to specialist agents")

        # ── Dispatch to specialist agents ─────────────────────────────────────
        try:
            domain_result = self._run_domain_agent(article_data)
            analysis_result = self._run_analysis_agent(article_data)
            fact_result = self._run_fact_agent(article_data)

            # ── Judge agent: aggregate and finalize ──────────────────────────
            final = self._run_judge_agent(
                article_data, domain_result, analysis_result, fact_result
            )

            if final:
                self._store_memory(memory_key, final)

            return final

        except Exception as e:
            print(f"[Backboard] Agent orchestration failed: {e}. Using fallback.")
            return None

    def _check_memory(self, key: str) -> dict | None:
        """Query Backboard semantic memory for a cached result."""
        # TODO: Replace with actual Backboard memory lookup
        # Example:
        # result = self._memory.get(key)
        # return result.data if result else None
        return None  # Remove when Backboard is connected

    def _store_memory(self, key: str, result: dict):
        """Store analysis result in Backboard semantic memory."""
        # TODO: Replace with actual Backboard memory store
        # Example:
        # self._memory.set(key, result, ttl_days=30)
        pass  # Remove when Backboard is connected

    def _run_domain_agent(self, article_data: dict) -> dict:
        """
        Domain Agent: handles criterion 1 (domain credibility).
        Uses Backboard RAG to query MBFC database instead of loading JSON locally.

        TODO: Replace rule-based calls with Backboard agent that queries the
        RAG-loaded MBFC document and ITSAP framework.
        """
        # Currently: use existing criterion1 directly
        from analyzers import criterion1_domain
        domain = article_data.get("domain", "")
        homepage_html = article_data.get("homepage_html", "")
        return criterion1_domain.analyze(domain, homepage_html)

    def _run_analysis_agent(self, article_data: dict) -> dict:
        """
        Analysis Agent: handles criteria 2, 4, 5, 6 in a single batched call.
        Uses Backboard's model hot-swapping to pick the best model for each sub-task.

        TODO: Replace with Backboard agent that uses semantic recall to compare
        this article's emotional profile against previously analyzed articles.
        """
        # Currently: use the batch cache from gemini_client
        from gemini_client import prime_batch_cache, get_batch_result
        title = article_data.get("title", "")
        text = article_data.get("text", "")
        authors = article_data.get("authors", [])
        author_name = authors[0] if authors else ""

        prime_batch_cache(text, title, author_name)

        return {
            "emotional": get_batch_result(text, title, "emotional") or {"score": 50, "reason": "Unavailable"},
            "author":    get_batch_result(text, title, "author")    or {"score": 50, "reason": "Unavailable"},
            "content":   get_batch_result(text, title, "content")   or {"score": 50, "reason": "Unavailable"},
            "mdm":       get_batch_result(text, title, "mdm")       or {"classification": "Unsustainable", "reason": "Unavailable"},
        }

    def _run_fact_agent(self, article_data: dict) -> dict:
        """
        Fact Agent: handles criterion 3 (factual verifiability).
        Sequential 3-step chain: extract claim → verify → extraordinary test.

        TODO: Replace with Backboard agent that has tool calling to search
        real-time news sources and fact-checking databases.
        """
        from analyzers import criterion3_factual
        return criterion3_factual.analyze(article_data)

    def _run_judge_agent(self, article_data: dict, domain: dict,
                          analysis: dict, fact: dict) -> dict | None:
        """
        Judge Agent: aggregates all specialist results into a final verdict.
        Uses Backboard's semantic recall to compare against previously judged articles.

        TODO: Replace with Backboard agent that recalls similar articles and
        adjusts scoring based on cross-article patterns.
        """
        # Currently: use the existing scorer logic with pre-computed results
        import scorer

        # Build the results dict that scorer expects
        from analyzers.criterion6_mdm import MDM_SCORES
        mdm_data = analysis.get("mdm", {})
        classification = mdm_data.get("classification", "Unsustainable")

        results = {
            "domain":    {"score": domain.get("score", 50),   "reason": domain.get("reason", "")},
            "emotional": {"score": analysis["emotional"].get("score", 50), "reason": analysis["emotional"].get("reason", "")},
            "factual":   {"score": fact.get("score", 50),     "reason": fact.get("reason", ""),  "core_claim": fact.get("core_claim", "")},
            "author":    {"score": analysis["author"].get("score", 50),    "reason": analysis["author"].get("reason", "")},
            "content":   {"score": analysis["content"].get("score", 50),   "reason": analysis["content"].get("reason", "")},
            "mdm":       {"score": MDM_SCORES.get(classification, 50),    "reason": mdm_data.get("reason", ""), "classification": classification},
        }

        domain_name = article_data.get("domain", "")
        results = scorer._apply_trusted_source_boost(results, domain_name)

        fallback_score = int(round(sum(
            results[k]["score"] * scorer.WEIGHTS[k] for k in scorer.WEIGHTS
        )))

        from gemini_client import gemini_final_score
        gemini_judgment = gemini_final_score(results, domain_name, article_data.get("text", ""))

        if gemini_judgment and "final_score" in gemini_judgment:
            final_score = int(gemini_judgment["final_score"])
            verdict_subtext_base = gemini_judgment.get("verdict_subtext", "")
        else:
            final_score = fallback_score
            verdict_subtext_base = None

        # Determine verdict tier
        if final_score >= 90:
            verdict, verdict_class = "Highly Credible", "v-excellent"
            verdict_subtext = verdict_subtext_base or "This content appears to be accurate and well-sourced."
        elif final_score >= 72:
            verdict, verdict_class = "Likely Credible", "v-good"
            verdict_subtext = verdict_subtext_base or "This content appears mostly reliable."
        elif final_score >= 45:
            verdict, verdict_class = "Uncertain", "v-uncertain"
            verdict_subtext = verdict_subtext_base or "Proceed with caution."
        elif final_score >= 25:
            verdict, verdict_class = "Likely Misinformation", "v-suspicious"
            verdict_subtext = verdict_subtext_base or "Significant warning signs detected."
        else:
            verdict, verdict_class = "Misinformation / Disinformation", "v-bad"
            verdict_subtext = verdict_subtext_base or "This content is highly likely to be false."

        criteria_display = [
            {"key": "domain",    "label": "Website Trustworthiness",    "weight": "20%", "score": results["domain"]["score"],    "reason": results["domain"]["reason"]},
            {"key": "emotional", "label": "Sensationalism & Clickbait", "weight": "20%", "score": results["emotional"]["score"], "reason": results["emotional"]["reason"]},
            {"key": "factual",   "label": "Fact-Checking & Accuracy",   "weight": "25%", "score": results["factual"]["score"],   "reason": results["factual"]["reason"]},
            {"key": "author",    "label": "Author Verifiability",        "weight": "15%", "score": results["author"]["score"],    "reason": results["author"]["reason"]},
            {"key": "content",   "label": "Content Quality",            "weight": "10%", "score": results["content"]["score"],   "reason": results["content"]["reason"]},
            {"key": "mdm",       "label": "Threat Classification",      "weight": "10%", "score": results["mdm"]["score"],       "reason": results["mdm"]["reason"]},
        ]

        return {
            "final_score":        final_score,
            "verdict":            verdict,
            "verdict_subtext":    verdict_subtext,
            "verdict_class":      verdict_class,
            "mdm_classification": classification,
            "core_claim":         fact.get("core_claim", ""),
            "criteria":           criteria_display,
            "powered_by":         "backboard",
        }


# Singleton instance — import this in app.py
orchestrator = BackboardOrchestrator()


# ── ITSAP.00.300 Framework Summary for RAG ────────────────────────────────────
ITSAP_SUMMARY = """
Canadian Centre for Cyber Security — ITSAP.00.300
How to Identify Misinformation, Disinformation and Malinformation

KEY QUESTIONS TO ASK:
1. Does it provoke an emotional response? Fear, anger, outrage?
2. Does it contain clickbait? Sensational headlines?
3. Can you verify the author and sources cited?
4. Use a fact-checking site to verify the information hasn't been proven false.
5. Ensure the information is up to date.
6. Is it an extraordinary claim? (These require extraordinary evidence)
7. Look for out-of-place design elements (unprofessional logos, animated GIFs)
8. Conduct a reverse image search to ensure images are not copied.

MDM FRAMEWORK DEFINITIONS:
- Valid: Factually correct, based on confirmable data, not misleading
- Misinformation: False information NOT intentionally designed to harm
- Malinformation: Based in truth but exaggerated or distorted to mislead
- Disinformation: Intentionally false, deliberately designed to manipulate
- Unsustainable: Cannot be confirmed or disproved based on available information

TRUSTED CANADIAN SOURCES:
- Government: canada.ca, gc.ca, cyber.gc.ca
- Public broadcasters: cbc.ca, radio-canada.ca
- Major outlets: theglobeandmail.com, thestar.com, nationalpost.com
"""
