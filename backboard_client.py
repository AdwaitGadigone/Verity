"""
backboard_client.py — Multi-Agent Orchestration via Backboard.io
=================================================================

ARCHITECTURE (4 agents with persistent memory):

  [Coordinator Agent]  — memory="Auto" — checks semantic memory for cached results
  [Analysis Agent]     — RAG on MBFC data — handles criteria 2, 4, 5, 6 in one call
  [Fact Agent]         — handles criterion 3 (sequential fact-checking chain)
  [Judge Agent]        — memory="Auto" — aggregates scores, stores domain reputation

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

# ── System prompts for each agent ────────────────────────────────────────────
COORDINATOR_PROMPT = """You are the Coordinator for Verity, Canada's AI-powered news credibility detector.

Your job is to remember previously analyzed articles. When given a URL or content hash,
recall whether you've analyzed it before and return the cached result.

When storing a result, extract and remember:
- The URL or content hash
- The final credibility score (0-100)
- The verdict (Highly Credible / Likely Credible / Uncertain / Likely Misinformation / Misinformation)
- The MDM classification (Valid / Misinformation / Malinformation / Disinformation / Unsustainable)
- A brief summary of why

Always respond in valid JSON."""

ANALYSIS_PROMPT = """You are the Analysis Agent for Verity, a Canadian news credibility tool based on
the official ITSAP.00.300 framework from the Canadian Centre for Cyber Security.

You analyze articles for FOUR criteria simultaneously:
1. Emotional Manipulation & Clickbait (score 0-100, where 100=completely neutral)
2. Author & Source Credibility (score 0-100, where 80-100=clearly real journalist)
3. Content Quality & Factual Substance (score 0-100, where 100=entirely factual)
4. MDM Classification (Valid / Misinformation / Malinformation / Disinformation / Unsustainable)

You have access to the Media Bias Fact Check (MBFC) database for Canadian outlets via documents.

Always respond in valid JSON with keys: emotional, author, content, mdm."""

FACT_PROMPT = """You are the Fact-Checking Agent for Verity, a Canadian news credibility tool.

You verify claims in three sequential steps:
1. Extract the single most important factual claim from the article
2. Cross-check that claim against reputable Canadian sources (CBC, Globe and Mail, Reuters, AP)
3. Assess whether it's an extraordinary claim requiring extraordinary evidence (ITSAP.00.300)

Always respond in valid JSON."""

JUDGE_PROMPT = """You are the Judge Agent for Verity, a Canadian news credibility tool based on ITSAP.00.300.

You receive scores from four specialist agents and determine the final credibility verdict.
You remember domain reputations across sessions to improve consistency.

Scoring weights: Domain (20%) + Emotional (20%) + Factual (25%) + Author (15%) + Content (10%) + MDM (10%)

Verdict tiers:
- 90-100: Highly Credible
- 72-89:  Likely Credible
- 45-71:  Uncertain
- 25-44:  Likely Misinformation
- 0-24:   Misinformation / Disinformation

Always respond in valid JSON."""


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


def _run(coro):
    """Run an async coroutine from synchronous Flask code."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # If there's already a running loop (shouldn't happen in Flask sync)
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
        # Load existing config if available
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                config = json.load(f)

        # Reuse existing agent IDs if they exist
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
            self._coordinator_id = a.assistant_id
            changed = True
            print(f"[Backboard] Created Coordinator agent: {self._coordinator_id}")

        if not self._analysis_id:
            a = await self._client.create_assistant(
                name="Verity Analysis Agent",
                system_prompt=ANALYSIS_PROMPT,
            )
            self._analysis_id = a.assistant_id
            changed = True
            print(f"[Backboard] Created Analysis agent: {self._analysis_id}")

            # Upload MBFC data as RAG document for this agent
            await self._upload_mbfc_rag()

        if not self._fact_id:
            a = await self._client.create_assistant(
                name="Verity Fact Agent",
                system_prompt=FACT_PROMPT,
            )
            self._fact_id = a.assistant_id
            changed = True
            print(f"[Backboard] Created Fact agent: {self._fact_id}")

        if not self._judge_id:
            a = await self._client.create_assistant(
                name="Verity Judge Agent",
                system_prompt=JUDGE_PROMPT,
            )
            self._judge_id = a.assistant_id
            changed = True
            print(f"[Backboard] Created Judge agent: {self._judge_id}")

        if changed:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "coordinator_id": str(self._coordinator_id),
                    "analysis_id":    str(self._analysis_id),
                    "fact_id":        str(self._fact_id),
                    "judge_id":       str(self._judge_id),
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

            # Write ITSAP summary as a temp text file and upload
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
        """
        Orchestrate a full analysis. Returns result dict or None (use fallback).
        """
        if not self.available:
            return None
        try:
            return _run(self._orchestrate(article_data))
        except Exception as e:
            print(f"[Backboard] Orchestration error: {e}. Using fallback.")
            return None

    # ── Agent calls ───────────────────────────────────────────────────────────

    async def _orchestrate(self, article_data: dict) -> dict | None:
        url = article_data.get("url", "")
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        content_hash = hashlib.md5((url or text[:2000]).encode()).hexdigest()[:12]

        # ── 1. Coordinator: check semantic memory cache ───────────────────────
        cached = await self._coordinator_check(url, content_hash)
        if cached:
            print(f"[Backboard] Semantic memory HIT for {url or content_hash}")
            cached["from_cache"] = True
            return cached

        print(f"[Backboard] Cache miss — dispatching to 3 specialist agents")

        # ── 2. Run domain (rule-based, no Backboard needed) ──────────────────
        from analyzers import criterion1_domain
        domain = article_data.get("domain", "")
        homepage_html = article_data.get("homepage_html", "")
        domain_result = criterion1_domain.analyze(domain, homepage_html)

        # ── 3. Analysis Agent: criteria 2, 4, 5, 6 (one batched call) ────────
        analysis_result = await self._run_analysis_agent(article_data)

        # ── 4. Fact Agent: criterion 3 (sequential) ───────────────────────────
        fact_result = await self._run_fact_agent(article_data)

        # ── 5. Judge Agent: aggregate + final verdict ─────────────────────────
        final = await self._run_judge_agent(
            article_data, domain_result, analysis_result, fact_result
        )

        if final:
            # Store result in coordinator memory for future cache hits
            await self._coordinator_store(url, content_hash, final)

        return final

    async def _coordinator_check(self, url: str, content_hash: str) -> dict | None:
        """Ask coordinator if this URL/content was analyzed before."""
        try:
            thread = await self._client.create_thread(self._coordinator_id)
            identifier = url if url else f"content hash {content_hash}"
            response = await self._client.add_message(
                thread_id=thread.thread_id,
                content=(
                    f"Have you previously analyzed this article? Identifier: {identifier}\n"
                    "If yes, return the stored result as JSON with keys: "
                    "final_score, verdict, verdict_class, verdict_subtext, mdm_classification, criteria.\n"
                    "If no prior record exists, respond with exactly: {{\"cached\": false}}"
                ),
                memory="Auto",
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            data = json.loads(response.content)
            if data.get("cached") is False or "final_score" not in data:
                return None
            return data
        except Exception:
            return None

    async def _coordinator_store(self, url: str, content_hash: str, result: dict):
        """Store analysis result in coordinator's semantic memory."""
        try:
            thread = await self._client.create_thread(self._coordinator_id)
            identifier = url if url else f"content hash {content_hash}"
            summary = (
                f"Verity analysis complete for: {identifier}\n"
                f"Score: {result.get('final_score')}/100\n"
                f"Verdict: {result.get('verdict')}\n"
                f"MDM Classification: {result.get('mdm_classification')}\n"
                f"Subtext: {result.get('verdict_subtext', '')}\n"
                f"Full result JSON: {json.dumps(result)}"
            )
            await self._client.add_message(
                thread_id=thread.thread_id,
                content=summary,
                memory="Auto",
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
        except Exception as e:
            print(f"[Backboard] Memory store failed (non-critical): {e}")

    async def _run_analysis_agent(self, article_data: dict) -> dict:
        """Analysis Agent: criteria 2, 4, 5, 6 in one Backboard call with RAG."""
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        authors = article_data.get("authors", [])
        author_name = authors[0] if authors else "Unknown"

        prompt = (
            f"Analyze this Canadian news article for 4 criteria. "
            f"Use your MBFC and ITSAP.00.300 documents to inform your assessment.\n\n"
            f"Author: {author_name}\n"
            f"Headline: {title}\n"
            f"Article (first 2500 chars): {text[:2500]}\n\n"
            "Return ONLY valid JSON:\n"
            '{"emotional": {"score": <0-100>, "reason": "<2-3 sentences>"},'
            ' "author": {"score": <0-100>, "reason": "<2-3 sentences>"},'
            ' "content": {"score": <0-100>, "reason": "<2-3 sentences>"},'
            ' "mdm": {"classification": "<Valid|Misinformation|Malinformation|Disinformation|Unsustainable>",'
            ' "reason": "<2-3 sentences>"}}'
        )

        try:
            thread = await self._client.create_thread(self._analysis_id)
            response = await self._client.add_message(
                thread_id=thread.thread_id,
                content=prompt,
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            data = json.loads(response.content)
            return data
        except Exception as e:
            print(f"[Backboard] Analysis agent failed: {e}. Using batch cache.")
            # Fallback: use existing Gemini batch cache
            from gemini_client import prime_batch_cache, get_batch_result
            prime_batch_cache(text, title, author_name)
            return {
                "emotional": get_batch_result(text, title, "emotional") or {"score": 50, "reason": "Unavailable"},
                "author":    get_batch_result(text, title, "author")    or {"score": 50, "reason": "Unavailable"},
                "content":   get_batch_result(text, title, "content")   or {"score": 50, "reason": "Unavailable"},
                "mdm":       get_batch_result(text, title, "mdm")       or {"classification": "Unsustainable", "reason": "Unavailable"},
            }

    async def _run_fact_agent(self, article_data: dict) -> dict:
        """Fact Agent: sequential 3-step claim extraction → verification → extraordinary test."""
        text = article_data.get("text", "")
        title = article_data.get("title", "")
        publish_date = article_data.get("publish_date", "")

        try:
            thread = await self._client.create_thread(self._fact_id)

            # Step 1: Extract claim
            r1 = await self._client.add_message(
                thread_id=thread.thread_id,
                content=(
                    f"Extract the single most important factual claim from this article.\n"
                    f"Headline: {title}\nText: {text[:1500]}\n"
                    'Return ONLY JSON: {"claim": "<one clear sentence>"}'
                ),
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            claim_data = json.loads(r1.content)
            claim = claim_data.get("claim", "")

            # Step 2: Verify claim (same thread — agent remembers the claim)
            r2 = await self._client.add_message(
                thread_id=thread.thread_id,
                content=(
                    f"Now cross-check this claim against reputable Canadian sources "
                    f"(CBC, Globe and Mail, Reuters, AP): \"{claim}\"\n"
                    "Rate accuracy 0-100 and explain.\n"
                    'Return ONLY JSON: {"score": <0-100>, "reason": "<2-3 sentences>"}'
                ),
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            verify_data = json.loads(r2.content)
            verify_score = max(0, min(100, int(verify_data.get("score", 50))))
            verify_reason = verify_data.get("reason", "")

            # Step 3: Extraordinary claim test (same thread)
            r3 = await self._client.add_message(
                thread_id=thread.thread_id,
                content=(
                    "Is the claim extraordinary (dramatic, contradicts common knowledge)? "
                    "Does the article provide proportionate evidence?\n"
                    'Return ONLY JSON: {"is_extraordinary": <bool>, "has_evidence": <bool>, '
                    '"score": <0-100>, "reason": "<2-3 sentences>"}'
                ),
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            extra_data = json.loads(r3.content)
            extra_score = max(0, min(100, int(extra_data.get("score", 60))))

            # Date check (rule-based, no Backboard needed)
            from analyzers.criterion3_factual import _check_date_recency
            date_score, date_reason = _check_date_recency(str(publish_date) if publish_date else "")

            final_score = int(round(
                verify_score * 0.55 + date_score * 0.20 + extra_score * 0.25
            ))

            reason = verify_reason if verify_score < 35 else (
                extra_data.get("reason", verify_reason) if extra_score < 20 else verify_reason
            )

            return {"score": final_score, "reason": reason, "core_claim": claim}

        except Exception as e:
            print(f"[Backboard] Fact agent failed: {e}. Using direct criterion3.")
            from analyzers import criterion3_factual
            return criterion3_factual.analyze(article_data)

    async def _run_judge_agent(self, article_data: dict, domain: dict,
                                analysis: dict, fact: dict) -> dict | None:
        """Judge Agent: aggregate all scores into final verdict with memory of domain history."""
        import scorer
        from analyzers.criterion6_mdm import MDM_SCORES

        mdm_data = analysis.get("mdm", {})
        classification = mdm_data.get("classification", "Unsustainable")
        if classification not in MDM_SCORES:
            classification = "Unsustainable"

        results = {
            "domain":    {"score": domain.get("score", 50),              "reason": domain.get("reason", "")},
            "emotional": {"score": analysis["emotional"].get("score", 50), "reason": analysis["emotional"].get("reason", "")},
            "factual":   {"score": fact.get("score", 50),                "reason": fact.get("reason", ""), "core_claim": fact.get("core_claim", "")},
            "author":    {"score": analysis["author"].get("score", 50),   "reason": analysis["author"].get("reason", "")},
            "content":   {"score": analysis["content"].get("score", 50),  "reason": analysis["content"].get("reason", "")},
            "mdm":       {"score": MDM_SCORES.get(classification, 50),   "reason": mdm_data.get("reason", ""), "classification": classification},
        }

        domain_name = article_data.get("domain", "")
        results = scorer._apply_trusted_source_boost(results, domain_name)

        fallback_score = int(round(sum(
            results[k]["score"] * scorer.WEIGHTS[k] for k in scorer.WEIGHTS
        )))

        # Ask Judge agent to review and finalize (with domain memory)
        try:
            thread = await self._client.create_thread(self._judge_id)
            summary = "\n".join(
                f"- {k.title()}: {v['score']}/100 — {v['reason']}" for k, v in results.items()
            )
            response = await self._client.add_message(
                thread_id=thread.thread_id,
                content=(
                    f"Domain: {domain_name}\n"
                    f"Criterion scores:\n{summary}\n\n"
                    "Determine the final credibility score (0-100) and a one-sentence verdict_subtext. "
                    "Consider domain history if you remember it.\n"
                    'Return ONLY JSON: {"final_score": <0-100>, "verdict_subtext": "<sentence>"}'
                ),
                memory="Auto",
                llm_provider="google",
                model_name="gemini-2.0-flash",
                stream=False,
            )
            judgment = json.loads(response.content)
            final_score = int(judgment.get("final_score", fallback_score))
            verdict_subtext_base = judgment.get("verdict_subtext", "")
        except Exception as e:
            print(f"[Backboard] Judge agent failed: {e}. Using fallback score.")
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


# Singleton — imported by app.py
orchestrator = BackboardOrchestrator()
