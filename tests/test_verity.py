"""
tests/test_verity.py — Unit tests for Verity
=============================================
Run with: python3 -m pytest tests/ -v

Tests cover:
  - gemini_client batch cache (no real API calls needed)
  - All 6 criterion rule-based sub-checks
  - scorer weighted math and trusted-source boost
  - Flask route input validation (/analyze, /speak, /explain, /history)
"""

import json
import sys
import os
import hashlib
import importlib
from unittest.mock import patch, MagicMock

# ── Ensure project root is on the path ───────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

FAKE_ARTICLE = {
    "title": "Government Announces New Housing Policy",
    "text": (
        "The federal government announced a new housing policy on Monday. "
        "According to Health Canada, the policy will affect over 2 million Canadians. "
        "Housing Minister Jane Smith said in a statement that the initiative aims to "
        "reduce costs by 15 percent. Statistics Canada data shows homelessness has "
        "risen 8 percent since 2020."
    ),
    "authors": ["Jane Doe"],
    "domain": "cbc.ca",
    "url": "https://cbc.ca/news/housing-policy",
    "homepage_html": "<html><body><p>CBC News</p></body></html>",
    "publish_date": "2025-01-15",
}

FAKE_CLICKBAIT_ARTICLE = {
    "title": "YOU WON'T BELIEVE what the government is hiding!!!",
    "text": "They don't want you to know THE TRUTH about vaccines!!! SHARE BEFORE DELETED!!!",
    "authors": [],
    "domain": "fakenews123.xyz",
    "url": "",
    "homepage_html": "<html><marquee>BREAKING NEWS</marquee><img src='a.gif'/></html>",
    "publish_date": "",
}


# ═══════════════════════════════════════════════════════════════════════════════
# GEMINI CLIENT — batch cache tests (no real API)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchCache:
    def setup_method(self):
        """Reset batch cache before each test."""
        import gemini_client
        gemini_client._batch_cache.clear()

    def test_get_batch_result_returns_none_when_empty(self):
        from gemini_client import get_batch_result
        result = get_batch_result("some text", "some title", "emotional")
        assert result is None

    def _make_fake_mega(self, emotional_score=85, mdm="Valid", include_summary=True):
        base = {
            "emotional": {"score": emotional_score, "reason": "Neutral tone"},
            "author":    {"score": 75, "reason": "Named journalist"},
            "content":   {"score": 80, "reason": "Factual content"},
            "mdm":       {"classification": mdm, "reason": "Accurate"},
            "factual":   {"core_claim": "Test claim", "score": 80, "reason": "Confirmed"},
            "final_score": 82,
            "verdict_subtext": "Reliable reporting.",
        }
        if include_summary:
            base["neutral_summary"] = (
                "The article reports on a new federal housing policy.\n\n"
                "The government cites Statistics Canada data showing an 8% rise in homelessness.\n\n"
                "The policy aims to reduce housing costs by 15%.\n\n"
                "No independent verification of the 15% figure is provided.\n\n"
                "Overall, this is a government policy announcement with limited external sourcing."
            )
        return base

    def test_prime_batch_cache_stores_result(self):
        from gemini_client import prime_batch_cache, get_batch_result

        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega()):
            success = prime_batch_cache("article text", "headline", "John Doe")

        assert success is True
        assert get_batch_result("article text", "headline", "emotional")["score"] == 85
        assert get_batch_result("article text", "headline", "mdm")["classification"] == "Valid"
        assert get_batch_result("article text", "headline", "factual")["core_claim"] == "Test claim"

    def test_prime_batch_cache_is_idempotent(self):
        """Calling prime_batch_cache twice with same content only calls Gemini once."""
        from gemini_client import prime_batch_cache

        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega()) as mock_gemini:
            prime_batch_cache("same text", "same title", "author")
            prime_batch_cache("same text", "same title", "author")

        assert mock_gemini.call_count == 1  # Second call hits cache

    def test_cache_key_differs_by_content(self):
        from gemini_client import prime_batch_cache, get_batch_result

        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega(emotional_score=90)):
            prime_batch_cache("text A", "title A", "")
        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega(emotional_score=10)):
            prime_batch_cache("text B", "title B", "")

        assert get_batch_result("text A", "title A", "emotional")["score"] == 90
        assert get_batch_result("text B", "title B", "emotional")["score"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# NEUTRAL SUMMARY — generation and pass-through tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestNeutralSummary:
    def setup_method(self):
        import gemini_client
        gemini_client._batch_cache.clear()

    def _make_fake_mega_with_summary(self):
        return {
            "emotional": {"score": 85, "reason": "Neutral tone"},
            "author":    {"score": 75, "reason": "Named journalist"},
            "content":   {"score": 80, "reason": "Factual content"},
            "mdm":       {"classification": "Valid", "reason": "Accurate"},
            "factual":   {"core_claim": "Test claim", "score": 80, "reason": "Confirmed"},
            "final_score": 82,
            "verdict_subtext": "Reliable reporting.",
            "neutral_summary": (
                "The article reports on a government housing policy.\n\n"
                "Evidence cited includes Statistics Canada data.\n\n"
                "Context: homelessness has risen 8% since 2020.\n\n"
                "The article does not include independent expert verification.\n\n"
                "This is a straightforward policy announcement with limited external sourcing."
            ),
        }

    def test_neutral_summary_stored_in_cache(self):
        """neutral_summary is stored in batch cache when AI returns it."""
        from gemini_client import prime_mega_cache, get_batch_result
        import gemini_client, hashlib

        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega_with_summary()):
            prime_mega_cache("article text", "headline", "John Doe")

        cache_key = hashlib.md5(("article text"[:3000] + "headline").encode()).hexdigest()
        cached = gemini_client._batch_cache.get(cache_key)
        assert cached is not None
        assert "neutral_summary" in cached
        assert "housing policy" in cached["neutral_summary"]

    def test_neutral_summary_in_scorer_result(self):
        """scorer.run_all() passes neutral_summary through to the result dict."""
        import scorer, gemini_client, hashlib

        fake_mega = self._make_fake_mega_with_summary()
        cache_key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        gemini_client._batch_cache[cache_key] = fake_mega

        with patch("gemini_client.call_gemini", return_value=fake_mega):
            result = scorer.run_all(FAKE_ARTICLE)

        assert "neutral_summary" in result
        assert len(result["neutral_summary"]) > 0

    def test_neutral_summary_empty_when_ai_fails(self):
        """When AI call fails, neutral_summary is empty string (not missing)."""
        import scorer, gemini_client
        gemini_client._batch_cache.clear()

        with patch("gemini_client.call_gemini", return_value=None):
            result = scorer.run_all(FAKE_ARTICLE)

        assert "neutral_summary" in result
        assert result["neutral_summary"] == ""

    def test_neutral_summary_has_multiple_paragraphs(self):
        """The summary contains paragraph breaks (\\n\\n separators)."""
        from gemini_client import prime_mega_cache, get_batch_result
        import gemini_client, hashlib

        with patch("gemini_client.call_gemini", return_value=self._make_fake_mega_with_summary()):
            prime_mega_cache("article text", "headline", "John Doe")

        cache_key = hashlib.md5(("article text"[:3000] + "headline").encode()).hexdigest()
        summary = gemini_client._batch_cache[cache_key]["neutral_summary"]
        paragraphs = [p for p in summary.split("\n\n") if p.strip()]
        assert len(paragraphs) >= 4

    def test_neutral_summary_missing_from_ai_response_gracefully_handled(self):
        """If AI returns valid JSON without neutral_summary, scorer still works."""
        import scorer, gemini_client, hashlib

        # Mega response without neutral_summary key
        fake_mega_no_summary = {
            "emotional": {"score": 85, "reason": "Neutral"},
            "author":    {"score": 75, "reason": "Named"},
            "content":   {"score": 80, "reason": "Factual"},
            "mdm":       {"classification": "Valid", "reason": "Accurate"},
            "factual":   {"core_claim": "Claim", "score": 80, "reason": "Confirmed"},
            "final_score": 82,
            "verdict_subtext": "Reliable.",
        }
        cache_key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        gemini_client._batch_cache[cache_key] = fake_mega_no_summary

        with patch("gemini_client.call_gemini", return_value=fake_mega_no_summary):
            result = scorer.run_all(FAKE_ARTICLE)

        assert result["neutral_summary"] == ""
        assert result["final_score"] > 0  # Rest of analysis still works


# ═══════════════════════════════════════════════════════════════════════════════
# CRITERION 1 — Domain (rule-based, no Gemini)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriterion1Domain:
    def setup_method(self):
        from analyzers import criterion1_domain
        self.c1 = criterion1_domain

    def test_tld_gc_ca_scores_high(self):
        score, _ = self.c1._get_tld_score("canada.gc.ca")
        assert score >= 90

    def test_tld_xyz_scores_low(self):
        score, _ = self.c1._get_tld_score("fakenews.xyz")
        assert score <= 20

    def test_tld_com_scores_neutral(self):
        score, _ = self.c1._get_tld_score("example.com")
        assert 30 <= score <= 80

    def test_typosquatting_detected(self):
        score, reason = self.c1._get_typosquatting_score("cbcnews.ca")
        assert score < 50
        assert len(reason) > 0

    def test_no_typosquatting_on_legit_domain(self):
        score, _ = self.c1._get_typosquatting_score("openai.com")
        assert score >= 70

    def test_contact_pages_present(self):
        html = '<a href="/about">About</a><a href="/contact">Contact</a><a href="/privacy">Privacy</a>'
        score, _ = self.c1._get_contact_score(html)
        assert score >= 70

    def test_contact_pages_missing(self):
        score, _ = self.c1._get_contact_score("<html><body>nothing</body></html>")
        assert score < 50

    def test_analyze_returns_score_and_reason(self):
        with patch("analyzers.criterion1_domain._get_domain_age_score", return_value=(70, "ok")):
            result = self.c1.analyze("cbc.ca", "")
        assert "score" in result
        assert "reason" in result
        assert 0 <= result["score"] <= 100


# ═══════════════════════════════════════════════════════════════════════════════
# CRITERION 2 — Emotional (rule-based parts)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriterion2Emotional:
    def setup_method(self):
        from analyzers import criterion2_emotional
        self.c2 = criterion2_emotional

    def test_caps_heavy_scores_low(self):
        score, _ = self.c2._score_caps_ratio("THE GOVERNMENT IS HIDING TRUTH FROM ALL CITIZENS NOW")
        assert score < 50

    def test_caps_normal_scores_high(self):
        score, _ = self.c2._score_caps_ratio("The government announced a new policy today.")
        assert score >= 70

    def test_exclamation_heavy_scores_low(self):
        score, _ = self.c2._score_exclamation_density("This is SHOCKING!!! You won't believe it!!! Share now!!!")
        assert score < 50

    def test_exclamation_none_scores_high(self):
        score, _ = self.c2._score_exclamation_density("The prime minister announced a new fiscal policy.")
        assert score >= 80

    def test_clickbait_detected(self):
        score, reason = self.c2._score_clickbait(
            "You won't believe what they're hiding", "shocking truth exposed"
        )
        assert score < 50

    def test_no_clickbait_scores_high(self):
        score, _ = self.c2._score_clickbait(
            "Federal budget released", "Government announces fiscal plan"
        )
        assert score >= 80

    def test_analyze_uses_batch_cache(self):
        """analyze() should use batch cache result, not call Gemini directly."""
        import gemini_client
        gemini_client._batch_cache.clear()

        fake_batch = {
            "emotional": {"score": 88, "reason": "Very neutral"},
            "author":    {"score": 70, "reason": "ok"},
            "content":   {"score": 70, "reason": "ok"},
            "mdm":       {"classification": "Valid", "reason": "ok"},
        }
        with patch("gemini_client.call_gemini", return_value=fake_batch):
            from gemini_client import prime_batch_cache
            prime_batch_cache(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "Jane Doe")

        with patch("gemini_client.call_gemini") as mock_direct:
            result = self.c2.analyze(FAKE_ARTICLE)

        mock_direct.assert_not_called()  # Should read from cache, not call Gemini
        assert "score" in result


# ═══════════════════════════════════════════════════════════════════════════════
# CRITERION 4 — Author (rule-based parts)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriterion4Author:
    def setup_method(self):
        from analyzers import criterion4_author
        self.c4 = criterion4_author

    def test_named_author_scores_high(self):
        score, _ = self.c4._score_byline(["Jane Doe"])
        assert score >= 80

    def test_no_author_scores_low(self):
        score, _ = self.c4._score_byline([])
        assert score <= 20

    def test_generic_byline_scores_low(self):
        score, _ = self.c4._score_byline(["Staff"])
        assert score <= 30

    def test_citations_detected(self):
        score, _ = self.c4._score_source_citations(
            "According to Statistics Canada, the data shows research found. In a statement."
        )
        assert score >= 70

    def test_no_citations_scores_low(self):
        score, _ = self.c4._score_source_citations("This is just an opinion piece with no sources.")
        assert score <= 20


# ═══════════════════════════════════════════════════════════════════════════════
# CRITERION 5 — Content (rule-based parts)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriterion5Content:
    def setup_method(self):
        from analyzers import criterion5_content
        self.c5 = criterion5_content

    def test_marquee_scores_low(self):
        score, reason = self.c5._check_design_markers("<html><marquee>BREAKING</marquee></html>")
        assert score < 70
        assert "marquee" in reason.lower()

    def test_clean_html_scores_high(self):
        score, _ = self.c5._check_design_markers("<html><body><article><p>News</p></article></body></html>")
        assert score >= 70

    def test_empty_html_returns_neutral(self):
        score, _ = self.c5._check_design_markers("")
        assert score == 60

    def test_image_flag_detects_images(self):
        flag = self.c5._flag_images("<img src='a.jpg'/><img src='b.jpg'/>")
        assert "2" in flag and "image" in flag.lower()

    def test_image_flag_empty_on_no_images(self):
        flag = self.c5._flag_images("<html><body><p>no images</p></body></html>")
        assert flag == ""


# ═══════════════════════════════════════════════════════════════════════════════
# CRITERION 6 — MDM (cache path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriterion6MDM:
    def setup_method(self):
        import gemini_client
        gemini_client._batch_cache.clear()
        from analyzers import criterion6_mdm
        self.c6 = criterion6_mdm

    def test_valid_classification_scores_100(self):
        assert self.c6.MDM_SCORES["Valid"] == 100

    def test_disinformation_scores_10(self):
        assert self.c6.MDM_SCORES["Disinformation"] == 10

    def test_analyze_uses_batch_cache(self):
        """analyze() should use batch cache, not call Gemini directly."""
        fake_batch = {
            "emotional": {"score": 70, "reason": "ok"},
            "author":    {"score": 70, "reason": "ok"},
            "content":   {"score": 70, "reason": "ok"},
            "mdm":       {"classification": "Disinformation", "reason": "clearly false"},
            "factual":   {"core_claim": "claim", "score": 20, "reason": "false"},
            "final_score": 15,
            "verdict_subtext": "Disinformation detected.",
        }
        with patch("gemini_client.call_gemini", return_value=fake_batch):
            from gemini_client import prime_batch_cache
            prime_batch_cache(FAKE_CLICKBAIT_ARTICLE["text"], FAKE_CLICKBAIT_ARTICLE["title"], "")

        with patch("gemini_client.call_gemini") as mock_direct:
            result = self.c6.analyze(FAKE_CLICKBAIT_ARTICLE)

        mock_direct.assert_not_called()
        assert result["classification"] == "Disinformation"
        assert result["score"] == 10

    def test_no_text_returns_unsustainable(self):
        result = self.c6.analyze({"text": "", "title": ""})
        assert result["classification"] == "Unsustainable"
        assert result["score"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# SCORER — weighted math and trusted source boost
# ═══════════════════════════════════════════════════════════════════════════════

class TestScorer:
    def setup_method(self):
        import scorer
        self.scorer = scorer

    def test_weights_sum_to_one(self):
        total = sum(self.scorer.WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_trusted_domain_detection(self):
        assert self.scorer._is_trusted("cbc.ca") is True
        assert self.scorer._is_trusted("www.canada.ca") is True
        assert self.scorer._is_trusted("fakenews.xyz") is False
        assert self.scorer._is_trusted("theglobeandmail.com") is True

    def test_trusted_source_boost_author(self):
        results = {
            "domain":    {"score": 90, "reason": "ok"},
            "emotional": {"score": 50, "reason": "ok"},
            "factual":   {"score": 80, "reason": "ok", "core_claim": ""},
            "author":    {"score": 20, "reason": "no byline"},
            "content":   {"score": 50, "reason": "ok"},
            "mdm":       {"score": 50, "reason": "ok", "classification": "Unsustainable"},
        }
        boosted = self.scorer._apply_trusted_source_boost(results, "cbc.ca")
        assert boosted["author"]["score"] >= 70

    def test_trusted_source_boost_mdm(self):
        results = {
            "domain":    {"score": 90, "reason": "ok"},
            "emotional": {"score": 50, "reason": "ok"},
            "factual":   {"score": 80, "reason": "ok", "core_claim": ""},
            "author":    {"score": 80, "reason": "ok"},
            "content":   {"score": 50, "reason": "ok"},
            "mdm":       {"score": 50, "reason": "ok", "classification": "Unsustainable"},
        }
        boosted = self.scorer._apply_trusted_source_boost(results, "canada.ca")
        assert boosted["mdm"]["classification"] == "Valid"
        assert boosted["mdm"]["score"] >= 85

    def test_no_boost_for_unknown_domain(self):
        results = {
            "domain":    {"score": 90, "reason": "ok"},
            "emotional": {"score": 50, "reason": "ok"},
            "factual":   {"score": 80, "reason": "ok", "core_claim": ""},
            "author":    {"score": 20, "reason": "no byline"},
            "content":   {"score": 50, "reason": "ok"},
            "mdm":       {"score": 50, "reason": "ok", "classification": "Unsustainable"},
        }
        boosted = self.scorer._apply_trusted_source_boost(results, "fakenews.xyz")
        assert boosted["author"]["score"] == 20  # Not boosted

    def test_weighted_score_calculation(self):
        """Verify weighted math is correct."""
        results = {
            "domain":    {"score": 100},
            "emotional": {"score": 100},
            "factual":   {"score": 100},
            "author":    {"score": 100},
            "content":   {"score": 100},
            "mdm":       {"score": 100},
        }
        score = sum(results[k]["score"] * self.scorer.WEIGHTS[k] for k in self.scorer.WEIGHTS)
        assert int(round(score)) == 100

    def test_run_criterion_safely_handles_exception(self):
        def bad_func():
            raise ValueError("simulated crash")

        result = self.scorer._run_criterion_safely("test", bad_func)
        assert result["score"] == 50
        assert result.get("error") is True


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES — input validation (no real Gemini/ElevenLabs calls)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlaskRoutes:
    def setup_method(self):
        # Mock heavy dependencies before importing app
        with patch.dict("sys.modules", {
            "backboard_client": MagicMock(orchestrator=MagicMock(run=MagicMock(return_value=None))),
        }):
            import app as flask_app
            flask_app.app.config["TESTING"] = True
            self.client = flask_app.app.test_client()
            self.app = flask_app

    def test_homepage_returns_200(self):
        resp = self.client.get("/")
        assert resp.status_code == 200

    def test_analyze_missing_body_returns_error(self):
        # Empty body causes Flask to fail JSON parsing → 400 or 500 depending on version
        resp = self.client.post("/analyze",
                                data="",
                                content_type="application/json")
        assert resp.status_code in (400, 500)

    def test_analyze_empty_input_returns_400(self):
        resp = self.client.post("/analyze",
                                data=json.dumps({"mode": "url", "input": "   "}),
                                content_type="application/json")
        assert resp.status_code == 400

    def test_history_returns_list(self):
        resp = self.client.get("/history")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_speak_no_key_returns_503(self):
        original = self.app.ELEVENLABS_API_KEY
        self.app.ELEVENLABS_API_KEY = None
        resp = self.client.post("/speak",
                                data=json.dumps({"text": "hello"}),
                                content_type="application/json")
        self.app.ELEVENLABS_API_KEY = original
        assert resp.status_code == 503

    def test_speak_summary_text_no_key_returns_503(self):
        """Summary TTS uses the same /speak route — 503 without API key."""
        original = self.app.ELEVENLABS_API_KEY
        self.app.ELEVENLABS_API_KEY = None
        summary_text = (
            "Israel struck fuel storage facilities in Tehran on Thursday.\n\n"
            "The Israeli military confirmed the strikes via official statement.\n\n"
            "Iranian President Pezeshkian condemned the attacks."
        )
        resp = self.client.post("/speak",
                                data=json.dumps({"text": summary_text}),
                                content_type="application/json")
        self.app.ELEVENLABS_API_KEY = original
        assert resp.status_code == 503

    def test_speak_empty_text_handled(self):
        """Empty text to /speak returns 400 or 503 (not 500 crash)."""
        original = self.app.ELEVENLABS_API_KEY
        self.app.ELEVENLABS_API_KEY = None
        resp = self.client.post("/speak",
                                data=json.dumps({"text": ""}),
                                content_type="application/json")
        self.app.ELEVENLABS_API_KEY = original
        assert resp.status_code in (400, 503)

    def test_speak_accepts_long_summary_text(self):
        """Long summary text (multi-paragraph) doesn't cause /speak to error before TTS."""
        original = self.app.ELEVENLABS_API_KEY
        self.app.ELEVENLABS_API_KEY = None
        long_text = "Para. " * 200  # ~1200 chars — typical summary length
        resp = self.client.post("/speak",
                                data=json.dumps({"text": long_text}),
                                content_type="application/json")
        self.app.ELEVENLABS_API_KEY = original
        # Without key → 503. The point is it doesn't 500 before even hitting ElevenLabs.
        assert resp.status_code == 503

    def test_explain_no_key_returns_503(self):
        original = self.app.ELEVENLABS_API_KEY
        self.app.ELEVENLABS_API_KEY = None
        resp = self.client.post("/explain",
                                data=json.dumps({"question_type": "why_flagged", "verdict_data": {}}),
                                content_type="application/json")
        self.app.ELEVENLABS_API_KEY = original
        assert resp.status_code == 503

    def test_history_deque_stores_entries(self):
        """History deque correctly stores and caps at maxlen=20."""
        import app as flask_app
        import datetime as dt
        flask_app._analysis_history.clear()
        for i in range(3):
            flask_app._analysis_history.appendleft({
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "url": f"https://cbc.ca/test/{i}",
                "title": f"Article {i}",
                "verdict": "Likely Credible",
                "verdict_class": "v-good",
                "final_score": 78,
                "mdm_classification": "Valid",
            })
        assert len(flask_app._analysis_history) == 3
        assert flask_app._analysis_history[0]["title"] == "Article 2"  # most recent first
        flask_app._analysis_history.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE CONSISTENCY — weighted math always wins over AI final_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreConsistency:
    """Verify that the final score always comes from weighted math, not AI."""

    def setup_method(self):
        import gemini_client
        gemini_client._batch_cache.clear()

    def _make_mega_with_bad_final_score(self):
        """Simulates what Groq did: criteria average ~83 but final_score=58."""
        return {
            "emotional": {"score": 82, "reason": "Neutral tone"},
            "author":    {"score": 90, "reason": "Named journalist"},
            "content":   {"score": 72, "reason": "Factual content"},
            "mdm":       {"classification": "Valid", "reason": "Accurate reporting"},
            "factual":   {"core_claim": "Israel struck fuel storage in Tehran", "score": 76, "reason": "AP confirmed"},
            "final_score": 58,  # Groq's inconsistent value — should be ignored
            "verdict_subtext": "Reliable war reporting.",
            "neutral_summary": "Para1.\n\nPara2.\n\nPara3.\n\nPara4.\n\nPara5.",
        }

    def test_scorer_ignores_ai_final_score(self):
        """scorer.run_all() uses weighted math, not the AI's final_score field."""
        import scorer, gemini_client, hashlib

        fake_mega = self._make_mega_with_bad_final_score()
        cache_key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        gemini_client._batch_cache[cache_key] = fake_mega

        with patch("gemini_client.call_gemini", return_value=fake_mega):
            result = scorer.run_all(FAKE_ARTICLE)

        assert result["final_score"] != 58

    def test_backboard_ignores_ai_final_score(self):
        """backboard_client _build_final_result() uses weighted math."""
        import gemini_client, hashlib
        from backboard_client import BackboardOrchestrator

        fake_mega = self._make_mega_with_bad_final_score()
        cache_key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        gemini_client._batch_cache[cache_key] = fake_mega

        analysis = {
            "emotional": fake_mega["emotional"],
            "author":    fake_mega["author"],
            "content":   fake_mega["content"],
            "mdm":       fake_mega["mdm"],
            "factual":   fake_mega["factual"],
        }
        domain_result = {"score": 86, "reason": "High credibility domain"}
        fact_result   = {"score": 76, "reason": "AP confirmed", "core_claim": "Israel struck Tehran"}
        article_data  = dict(FAKE_ARTICLE, domain="theglobeandmail.com")

        orch = BackboardOrchestrator.__new__(BackboardOrchestrator)
        orch._local_result_cache = {}
        result = orch._build_final_result(article_data, domain_result, analysis, fact_result)

        assert result["final_score"] != 58
        assert result["final_score"] > 70

    def test_mdm_classification_uses_post_boost_value(self):
        """mdm_classification in result reflects trusted-source boost, not raw AI value."""
        import gemini_client, hashlib
        from backboard_client import BackboardOrchestrator

        fake_mega = self._make_mega_with_bad_final_score()
        fake_mega["mdm"]["classification"] = "Misinformation"  # Groq got it wrong

        cache_key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        gemini_client._batch_cache[cache_key] = fake_mega

        analysis = {
            "emotional": fake_mega["emotional"],
            "author":    fake_mega["author"],
            "content":   fake_mega["content"],
            "mdm":       fake_mega["mdm"],
            "factual":   fake_mega["factual"],
        }
        domain_result = {"score": 86, "reason": "High credibility"}
        fact_result   = {"score": 76, "reason": "Confirmed", "core_claim": "Test"}
        article_data  = dict(FAKE_ARTICLE, domain="theglobeandmail.com")

        orch = BackboardOrchestrator.__new__(BackboardOrchestrator)
        orch._local_result_cache = {}
        result = orch._build_final_result(article_data, domain_result, analysis, fact_result)

        # Trusted-source boost should override Misinformation → Valid
        assert result["mdm_classification"] == "Valid"


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — live Groq API (skipped if no key)
# ═══════════════════════════════════════════════════════════════════════════════

import pytest

@pytest.mark.integration
class TestGroqIntegration:
    """
    Live integration tests against the Groq API.
    Run with: python -m pytest tests/ -m integration -v
    Skipped automatically if GROQ_API_KEY is not set.
    """

    @pytest.fixture(autouse=True)
    def require_groq(self):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("GROQ_API_KEY"):
            pytest.skip("GROQ_API_KEY not set")

    def setup_method(self):
        import gemini_client
        gemini_client._batch_cache.clear()
        self._orig_clients = gemini_client._clients[:]
        gemini_client._clients = []  # Force Groq path

    def teardown_method(self):
        import gemini_client
        gemini_client._clients = self._orig_clients

    def test_groq_returns_valid_json(self):
        """Groq responds to a simple JSON prompt."""
        import gemini_client
        result = gemini_client.call_gemini(
            'Return JSON with key "ok" set to true: {"ok": true}'
        )
        assert result is not None
        assert result.get("ok") is True

    def test_groq_mega_cache_primes_successfully(self):
        """prime_mega_cache() populates all required keys via Groq."""
        from gemini_client import prime_mega_cache, get_batch_result
        success = prime_mega_cache(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "Jane Doe")
        assert success is True
        assert get_batch_result(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "emotional") is not None
        assert get_batch_result(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "factual") is not None

    def test_groq_neutral_summary_generated(self):
        """Groq generates a neutral_summary with multiple paragraphs."""
        import gemini_client, hashlib
        from gemini_client import prime_mega_cache

        prime_mega_cache(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "Jane Doe")
        key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        root = gemini_client._batch_cache.get(key)

        assert root is not None
        summary = root.get("neutral_summary", "")
        assert len(summary) > 100
        paragraphs = [p for p in summary.split("\n\n") if p.strip()]
        assert len(paragraphs) >= 3

    def test_groq_mdm_valid_for_credible_source(self):
        """Groq classifies a clear government article as Valid or Unsustainable."""
        import gemini_client, hashlib
        from gemini_client import prime_mega_cache

        gov_article = dict(
            FAKE_ARTICLE,
            title="Statistics Canada releases 2024 population census data",
            text=(
                "Statistics Canada today published the 2024 national census results. "
                "Canada's population grew to 42.1 million, up 5.4% since 2021. "
                "The census was conducted online and by mail between May and August 2024. "
                "Chief Statistician Anil Arora said response rates were the highest in two decades."
            ),
        )
        prime_mega_cache(gov_article["text"], gov_article["title"], "Stats Canada")
        key = hashlib.md5((gov_article["text"][:3000] + gov_article["title"]).encode()).hexdigest()
        root = gemini_client._batch_cache.get(key)
        assert root.get("mdm", {}).get("classification") in ("Valid", "Unsustainable")

    def test_groq_emotional_high_for_neutral_article(self):
        """Neutral government-style article scores 60+ on emotional."""
        import gemini_client, hashlib
        from gemini_client import prime_mega_cache

        prime_mega_cache(FAKE_ARTICLE["text"], FAKE_ARTICLE["title"], "Jane Doe")
        key = hashlib.md5((FAKE_ARTICLE["text"][:3000] + FAKE_ARTICLE["title"]).encode()).hexdigest()
        root = gemini_client._batch_cache.get(key)
        assert root.get("emotional", {}).get("score", 0) >= 60

    def test_groq_emotional_low_for_clickbait(self):
        """Clickbait article scores below 60 on emotional."""
        import gemini_client, hashlib
        from gemini_client import prime_mega_cache

        prime_mega_cache(
            FAKE_CLICKBAIT_ARTICLE["text"],
            FAKE_CLICKBAIT_ARTICLE["title"], ""
        )
        key = hashlib.md5((FAKE_CLICKBAIT_ARTICLE["text"][:3000] + FAKE_CLICKBAIT_ARTICLE["title"]).encode()).hexdigest()
        root = gemini_client._batch_cache.get(key)
        assert root.get("emotional", {}).get("score", 100) < 60


# ═══════════════════════════════════════════════════════════════════════════════
# FRONTEND HTML STRUCTURE — static analysis of rendered HTML
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendHTML:
    """
    Parses the HTML returned by GET / and verifies the element structure
    that script.js depends on.  Fast, no real API calls needed.
    """

    def setup_method(self):
        from unittest.mock import patch, MagicMock
        with patch.dict("sys.modules", {
            "backboard_client": MagicMock(
                orchestrator=MagicMock(run=MagicMock(return_value=None))
            ),
        }):
            import app as flask_app
            flask_app.app.config["TESTING"] = True
            self.client = flask_app.app.test_client()

        resp = self.client.get("/")
        assert resp.status_code == 200
        from bs4 import BeautifulSoup
        self.soup = BeautifulSoup(resp.data, "html.parser")

    def test_landing_section_present(self):
        """Landing section must exist as the default visible section."""
        assert self.soup.find(id="landing-section") is not None

    def test_input_section_starts_hidden(self):
        """Analyzer input section must be hidden until the user navigates to it."""
        section = self.soup.find(id="input-section")
        assert section is not None
        style = section.get("style", "")
        assert "display:none" in style.replace(" ", "")

    def test_loading_section_starts_hidden(self):
        section = self.soup.find(id="loading-section")
        assert section is not None
        style = section.get("style", "")
        assert "display:none" in style.replace(" ", "")

    def test_results_section_starts_hidden(self):
        section = self.soup.find(id="results-section")
        assert section is not None
        style = section.get("style", "")
        assert "display:none" in style.replace(" ", "")

    def test_required_element_ids_present(self):
        """All IDs that script.js references must exist in the rendered HTML."""
        required_ids = [
            "verdict-banner", "result-verdict-title", "result-score",
            "result-mdm-badge", "result-verdict-subtext",
            "criteria-list", "neutral-summary-section", "neutral-summary-body",
            "cache-badge", "core-claim-section", "core-claim-text",
            "url-input", "text-input", "analyze-btn",
            "tab-url", "tab-text", "input-url-wrapper", "input-text-wrapper",
            "speak-btn", "stop-btn", "followup-buttons",
            "summary-speak-btn", "summary-stop-btn", "summary-toggle-btn",
            "lc-domain", "lc-emotional", "lc-factual",
            "lc-author", "lc-content", "lc-mdm",
            "loading-checklist", "history-container", "history-list",
            "result-article-title",
        ]
        missing = [id_ for id_ in required_ids if self.soup.find(id=id_) is None]
        assert missing == [], f"Missing element IDs: {missing}"

    def test_onclick_functions_defined_in_script(self):
        """Every function referenced in an onclick= attribute must be defined in script.js."""
        import re
        # Collect all onclick values from the HTML
        onclick_values = [
            tag.get("onclick", "")
            for tag in self.soup.find_all(True)
            if tag.get("onclick")
        ]
        # Extract bare function names like foo() or foo('bar')
        called = set()
        for v in onclick_values:
            match = re.match(r"([a-zA-Z_]\w*)\s*\(", v)
            if match:
                called.add(match.group(1))

        # Read script.js and find all top-level function definitions (sync + async)
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "script.js"
        )
        with open(script_path) as f:
            script_src = f.read()
        defined = set(re.findall(r"^(?:async\s+)?function\s+(\w+)\s*\(", script_src, re.MULTILINE))

        missing = called - defined
        assert missing == set(), f"onclick functions not defined in script.js: {missing}"


# ═══════════════════════════════════════════════════════════════════════════════
# FRONTEND CSS — static analysis of style.css
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendCSS:
    """
    Reads style.css as plain text and verifies design-system invariants.
    """

    def setup_method(self):
        import re
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "style.css"
        )
        with open(css_path) as f:
            self.css = f.read()
        self.re = re

    def _root_vars(self):
        """Return the set of CSS variable names defined inside :root { ... }."""
        m = self.re.search(r":root\s*\{([^}]+)\}", self.css)
        if not m:
            return set()
        return set(self.re.findall(r"(--.+?):", m.group(1)))

    def test_no_undefined_css_variables(self):
        """Every var(--foo) used in style.css must be declared in :root.
        Exception: single-letter properties like --w are inline element parameters
        set via style="" attributes, not :root declarations."""
        used = set(self.re.findall(r"var\((--[\w-]+)", self.css))
        defined = self._root_vars()
        # Exclude single-character inline parameters (e.g. --w used as animation target)
        inline_params = {v for v in used if len(v) <= 3}
        undefined = (used - defined) - inline_params
        assert undefined == set(), f"CSS variables used but never defined in :root: {undefined}"

    def test_bg_light_not_referenced(self):
        """Bug #1: --bg-light was undefined; confirm it is no longer referenced."""
        assert "--bg-light" not in self.css

    def test_text_heading_not_referenced(self):
        """Bug #1: --text-heading was undefined; confirm it is no longer referenced."""
        assert "--text-heading" not in self.css

    def test_demo_bars_have_staggered_delays(self):
        """Bug #2: demo card bars must have 4 distinct staggered animation-delay values."""
        delays = self.re.findall(
            r"lp-demo-bar-row:nth-child\(\d\).*?animation-delay:\s*([\d.]+s)",
            self.css, self.re.DOTALL
        )
        assert len(delays) == 4, f"Expected 4 staggered bar delays, found: {delays}"
        # All four delays must be different
        assert len(set(delays)) == 4, f"Bar delays are not all distinct: {delays}"

    def test_progress_fill_transition_under_one_second(self):
        """Bug #3: progress-fill transition must be < 1s so results don't feel laggy."""
        m = self.re.search(r"\.progress-fill\s*\{[^}]*transition:[^;]*?([\d.]+)s", self.css)
        assert m is not None, "Could not find .progress-fill transition duration"
        duration = float(m.group(1))
        assert duration < 1.0, f"progress-fill transition is {duration}s — should be < 1s"
