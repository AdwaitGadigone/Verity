"""
backboard_client.py — Multi-Agent Orchestration via Backboard.io
=================================================================

ARCHITECTURE — 1 Gemini call per new article, 0 for repeats:

  [Coordinator]  — in-process dict cache (instant, 0 API calls)
  [Analysis]     — calls prime_mega_cache() → 1 Gemini call covering ALL criteria
  [Fact]         — reads from mega cache (0 additional calls)
  [Judge]        — reads final_score from mega cache (0 additional calls)

Backboard agents are used for:
  - Semantic memory storage (visible in Backboard dashboard for prize demo)
  - RAG documents (MBFC data, ITSAP framework) attached to Analysis agent

Agent IDs are persisted in .backboard_config.json so assistants are reused across
server restarts (avoids re-creating + re-uploading RAG docs every time).
"""

import os
import json
import asyncio
import hashlib
import tempfile
from dotenv import load_dotenv

load_dotenv()
BACKBOARD_API_KEY = os.getenv("BACKBOARD_API_KEY")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), ".backboard_config.json")

# ── ITSAP.00.300 Framework Summary (uploaded as RAG doc) ──────────────────────
ITSAP_SUMMARY = """Canadian Centre for Cyber Security — ITSAP.00.300
How to Identify Misinformation, Disinformation and Malinformation

KEY QUESTIONS TO ASK:
1. Does it provoke an emotional response? Fear, anger, outrage?
2. Does it contain clickbait or sensational headlines?
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
- Government: canada.ca, gc.ca, cyber.gc.ca, statcan.gc.ca
- Public broadcasters: cbc.ca, radio-canada.ca
- Major outlets: theglobeandmail.com, thestar.com, nationalpost.com, macleans.ca
"""

# ── System prompts for Backboard agents (used for RAG + memory, not inference) ─
COORDINATOR_PROMPT = """You are the Coordinator for Verity, Canada's AI-powered news credibility detector.
You store and recall previously analyzed articles for semantic memory."""

ANALYSIS_PROMPT = """You are the Analysis Agent for Verity, a Canadian news credibility tool based on
the official ITSAP.00.300 framework from the Canadian Centre for Cyber Security.
You have access to the Media Bias Fact Check (MBFC) database and ITSAP.00.300 guidelines via documents."""

FACT_PROMPT = """You are the Fact-Checking Agent for Verity, a Canadian news credibility tool.
You verify claims against reputable Canadian sources (CBC, Globe and Mail, Reuters, AP)."""

JUDGE_PROMPT = """You are the Judge Agent for Verity, a Canadian news credibility tool based on ITSAP.00.300.
You remember domain reputations across sessions to improve consistency.
Scoring weights: Domain (20%) + Emotional (20%) + Factual (25%) + Author (15%) + Content (10%) + MDM (10%)"""


def _run(coro):
    """Run an async coroutine from synchronous Flask code."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


class BackboardOrchestrator:
    def __init__(self):
        self.available = False
        self._client = None
        self._coordinator_id = None
        self._analysis_id = None
        self._fact_id = None
        self._judge_id = None
        # In-process cache: content_hash → full result dict (0 API calls for repeats)
        self._local_result_cache: dict = {}

        if not BACKBOARD_API_KEY:
            print("[Backboard] No API key found. Set BACKBOARD_API_KEY in .env")
            return

        try:
            from backboard import BackboardClient
            self._client = BackboardClient(api_key=BACKBOARD_API_KEY)
            _run(self._init_agents())
            self.available = True
            print("[Backboard] Ready — 4 agents initialized with semantic memory.")
        except Exception as e:
            print(f"[Backboard] Init failed: {e}. Using direct Gemini fallback.")

    async def _init_agents(self):
        """Create agents once, persist IDs to .backboard_config.json for reuse."""
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                config = json.load(f)

        self._coordinator_id = config.get("coordinator_id")
        self._analysis_id = config.get("analysis_id")
        self._fact_id = config.get("fact_id")
        self._judge_id = config.get("judge_id")

        changed = False

        if not self._coordinator_id:
            a = await self._client.create_assistant(
                name="Verity Coordinator",
                system_prompt=COORDINATOR_PROMPT,
            )
            self._coordinator_id = str(a.assistant_id)
            changed = True
            print(f"[Backboard] Created Coordinator agent: {self._coordinator_id}")

        if not self._analysis_id:
            a = await self._client.create_assistant(
                name="Verity Analysis Agent",
                system_prompt=ANALYSIS_PROMPT,
            )
            self._analysis_id = str(a.assistant_id)
            changed = True
            print(f"[Backboard] Created Analysis agent: {self._analysis_id}")
            await self._upload_mbfc_rag()

        if not self._fact_id:
            a = await self._client.create_assistant(
                name="Verity Fact Agent",
                system_prompt=FACT_PROMPT,
            )
            self._fact_id = str(a.assistant_id)
            changed = True
            print(f"[Backboard] Created Fact agent: {self._fact_id}")

        if not self._judge_id:
            a = await self._client.create_assistant(
                name="Verity Judge Agent",
                system_prompt=JUDGE_PROMPT,
            )
            self._judge_id = str(a.assistant_id)
            changed = True
            print(f"[Backboard] Created Judge agent: {self._judge_id}")

        if changed:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "coordinator_id": self._coordinator_id,
                    "analysis_id":    self._analysis_id,
                    "fact_id":        self._fact_id,
                    "judge_id":       self._judge_id,
                }, f, indent=2)
            print(f"[Backboard] Agent IDs saved to {CONFIG_FILE}")

    async def _upload_mbfc_rag(self):
        """Upload MBFC outlet data + ITSAP framework as RAG documents."""
        try:
            mbfc_path = os.path.join(os.path.dirname(__file__), "mbfc_data.json")
            if os.path.exists(mbfc_path):
                doc = await self._client.upload_document_to_assistant(
                    self._analysis_id, mbfc_path
                )
                print(f"[Backboard] MBFC data uploaded as RAG doc: {doc.document_id}")

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                             delete=False, prefix="itsap_") as f:
                f.write(ITSAP_SUMMARY)
                tmp_path = f.name
            doc2 = await self._client.upload_document_to_assistant(
                self._analysis_id, tmp_path
            )
            os.unlink(tmp_path)
            print(f"[Backboard] ITSAP summary uploaded as RAG doc: {doc2.document_id}")
        except Exception as e:
            print(f"[Backboard] RAG upload failed (non-critical): {e}")

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, article_data: dict) -> dict | None:
        """Orchestrate a full analysis. Returns result dict or None (use fallback)."""
        if not self.available:
            return None
        try:
            return _run(self._orchestrate(article_data))
        except Exception as e:
            print(f"[Backboard] Orchestration error: {e}. Using fallback.")
            return None

    # ── Orchestration ─────────────────────────────────────────────────────────

    async def _orchestrate(self, article_data: dict) -> dict | None:
        url = article_data.get("url", "")
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        content_hash = hashlib.md5((url or text[:2000]).encode()).hexdigest()[:12]

        # ── 1. Coordinator: check in-process cache (0 API calls) ─────────────
        cached = self._local_result_cache.get(content_hash)
        if cached:
            print(f"[Backboard] Memory HIT for {url or content_hash}")
            result = dict(cached)
            result["from_cache"] = True
            return result

        print(f"[Backboard] Cache miss — running analysis (1 Gemini call)")

        # ── 2. Domain: rule-based, no AI needed ──────────────────────────────
        from analyzers import criterion1_domain
        domain = article_data.get("domain", "")
        homepage_html = article_data.get("homepage_html", "")
        domain_result = criterion1_domain.analyze(domain, homepage_html)

        # ── 3. Single Gemini call covers ALL AI criteria + final score ────────
        authors = article_data.get("authors", [])
        author_name = authors[0] if authors else ""
        from gemini_client import prime_mega_cache
        prime_mega_cache(text, title, author_name)

        # ── 4. Read all agent results from the mega cache ─────────────────────
        analysis_result = self._read_analysis_from_cache(text, title)
        fact_result = self._read_fact_from_cache(article_data)
        final = self._build_final_result(article_data, domain_result, analysis_result, fact_result)

        if final:
            # Store in local cache (instant recall for rest of session)
            self._local_result_cache[content_hash] = final
            # Fire-and-forget to Backboard memory (non-blocking, for dashboard demo)
            import threading
            threading.Thread(
                target=_run,
                args=(self._store_to_backboard_memory(url, content_hash, final),),
                daemon=True,
            ).start()

        return final

    # ── Read results from in-process mega cache (0 API calls) ─────────────────

    def _read_analysis_from_cache(self, text: str, title: str) -> dict:
        """Read emotional/author/content/mdm from the mega cache."""
        from gemini_client import get_batch_result
        neutral = {"score": 50, "reason": "Unavailable"}
        return {
            "emotional": get_batch_result(text, title, "emotional") or neutral,
            "author":    get_batch_result(text, title, "author")    or neutral,
            "content":   get_batch_result(text, title, "content")   or neutral,
            "mdm":       get_batch_result(text, title, "mdm")       or {
                "classification": "Unsustainable", "reason": "Unavailable"
            },
            "factual":   get_batch_result(text, title, "factual")   or {},
        }

    def _read_fact_from_cache(self, article_data: dict) -> dict:
        """Read factual result from mega cache, apply date recency weighting."""
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        publish_date = article_data.get("publish_date", "")

        from gemini_client import get_batch_result
        cached = get_batch_result(text, title, "factual")
        if cached and "score" in cached:
            from analyzers.criterion3_factual import _check_date_recency
            date_score, date_reason = _check_date_recency(str(publish_date) if publish_date else "")
            verify_score = max(0, min(100, int(cached["score"])))
            final_score = int(round(verify_score * 0.70 + date_score * 0.30))
            reason = cached.get("reason", "")
            if date_score < 30:
                reason = f"{date_reason}. {reason}"
            return {"score": final_score, "reason": reason, "core_claim": cached.get("core_claim", "")}

        # Mega cache missed (Gemini quota likely exhausted) — return rule-based date check only.
        # Do NOT fall back to criterion3_factual.analyze() — that makes 2 more Gemini calls that
        # will also fail, wasting quota.
        from analyzers.criterion3_factual import _check_date_recency
        date_score, date_reason = _check_date_recency(str(publish_date) if publish_date else "")
        return {
            "score": date_score,
            "reason": f"{date_reason}. AI fact-checking unavailable (quota exhausted).",
            "core_claim": "",
        }

    def _build_final_result(self, article_data: dict, domain: dict,
                             analysis: dict, fact: dict) -> dict | None:
        """Aggregate all criterion scores into the final verdict."""
        import scorer
        from analyzers.criterion6_mdm import MDM_SCORES

        mdm_data = analysis.get("mdm", {})
        classification = mdm_data.get("classification", "Unsustainable")
        if classification not in MDM_SCORES:
            classification = "Unsustainable"

        results = {
            "domain":    {"score": domain.get("score", 50),                 "reason": domain.get("reason", "")},
            "emotional": {"score": analysis["emotional"].get("score", 50),  "reason": analysis["emotional"].get("reason", "")},
            "factual":   {"score": fact.get("score", 50),                   "reason": fact.get("reason", ""), "core_claim": fact.get("core_claim", "")},
            "author":    {"score": analysis["author"].get("score", 50),     "reason": analysis["author"].get("reason", "")},
            "content":   {"score": analysis["content"].get("score", 50),    "reason": analysis["content"].get("reason", "")},
            "mdm":       {"score": MDM_SCORES.get(classification, 50),      "reason": mdm_data.get("reason", ""), "classification": classification},
        }

        domain_name = article_data.get("domain", "")
        results = scorer._apply_trusted_source_boost(results, domain_name)

        # Read final_score from mega cache; fall back to weighted math
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        from gemini_client import get_batch_result
        mega = get_batch_result(text, title, "_self")

        # get_batch_result doesn't support root — fetch directly
        import gemini_client
        cache_key = hashlib.md5((text[:3000] + title).encode()).hexdigest()
        root = gemini_client._batch_cache.get(cache_key)

        # Always use weighted math — AI final_score is often inconsistent
        # with its own criteria scores, so we never trust it directly.
        final_score = int(round(sum(
            results[k]["score"] * scorer.WEIGHTS[k] for k in scorer.WEIGHTS
        )))
        verdict_subtext_base = root.get("verdict_subtext", "") if root else ""
        neutral_summary = root.get("neutral_summary", "") if root else ""

        is_undeterminable = root.get("is_undeterminable", False) if root else False
        undeterminable_reason = root.get("undeterminable_reason", "") if root else ""

        if is_undeterminable:
            verdict, verdict_class = "Undeterminable", "v-undeterminable"
            verdict_subtext = undeterminable_reason or "This content is inherently subjective or belief-based. Credibility cannot be objectively determined."
        elif final_score >= 90:
            verdict, verdict_class = "Highly Credible", "v-excellent"
            verdict_subtext = verdict_subtext_base or "This content appears to be accurate and well-sourced."
        elif final_score >= 72:
            verdict, verdict_class = "Likely Credible", "v-good"
            verdict_subtext = verdict_subtext_base or "This content appears mostly reliable. Minor concerns noted."
        elif final_score >= 45:
            verdict, verdict_class = "Questionable", "v-questionable"
            verdict_subtext = verdict_subtext_base or "Mixed credibility. Verify claims through additional sources."
        elif final_score >= 25:
            verdict, verdict_class = "Likely Misinformation", "v-suspicious"
            verdict_subtext = verdict_subtext_base or "Significant warning signs detected. Do not share without verification."
        else:
            verdict, verdict_class = "Misinformation / Disinformation", "v-bad"
            verdict_subtext = verdict_subtext_base or "This content is highly likely to be false or deliberately misleading."

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
            "is_undeterminable":  is_undeterminable,
            "mdm_classification": results["mdm"]["classification"],  # post-boost value
            "core_claim":         fact.get("core_claim", ""),
            "neutral_summary":    neutral_summary,
            "criteria":           criteria_display,
            "powered_by":         "backboard",
        }

    # ── Backboard memory storage (fire-and-forget, non-blocking) ─────────────

    async def _store_to_backboard_memory(self, url: str, content_hash: str, result: dict):
        """Store analysis result in Backboard coordinator memory for cross-session recall."""
        if not self._client or not self._coordinator_id:
            return
        try:
            thread = await self._client.create_thread(self._coordinator_id)
            identifier = url if url else f"content:{content_hash}"
            memory_text = (
                f"Verity analysis stored for: {identifier}\n"
                f"Score: {result.get('final_score')}/100 | "
                f"Verdict: {result.get('verdict')} | "
                f"MDM: {result.get('mdm_classification')}\n"
                f"Summary: {result.get('verdict_subtext', '')}"
            )
            await self._client.add_message(
                thread_id=thread.thread_id,
                content=memory_text,
                memory="Auto",
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            print(f"[Backboard] Memory stored for {identifier}")
        except Exception as e:
            print(f"[Backboard] Memory store failed (non-critical): {e}")


# Singleton — imported by app.py
orchestrator = BackboardOrchestrator()
