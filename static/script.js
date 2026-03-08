/*
 * script.js — Verity Frontend Logic
 * ====================================
 * Handles all browser-side behaviour:
 *   - Tab switching (URL / Text)
 *   - Sending requests to Flask backend (/analyze)
 *   - Animating the loading checklist
 *   - Rendering verdict + criteria breakdown
 *   - ElevenLabs voice playback with Stop button
 *
 * IMPORTANT — ELEMENT ID MAP (must match index.html exactly):
 *   input-section            — wraps hero + input card
 *   loading-section          — animated checklist
 *   results-section          — verdict + breakdown
 *   tab-url / tab-text       — input mode tabs
 *   url-input / text-input   — the actual inputs
 *   analyze-btn              — the big green button
 *   lc-domain .. lc-mdm     — loading checklist items
 *   result-article-title     — article headline display
 *   verdict-banner           — coloured verdict card
 *   result-verdict-title     — "Highly Credible" etc.
 *   result-score             — the big number
 *   result-mdm-badge         — MDM classification pill
 *   result-verdict-subtext   — one-line description
 *   core-claim-section       — wrapper (hidden if no claim)
 *   core-claim-text          — the claim text
 *   criteria-list            — ul of criterion rows
 *   speak-btn / stop-btn     — ElevenLabs controls
 */

// ── Global state ─────────────────────────────────────────────────
let currentMode = "url";        // "url" or "text"
let lastResult = null;          // stored for voice readout
let currentAudio = null;        // currently-playing Audio object (verdict/follow-up)
let summaryAudio = null;        // currently-playing Audio object (summary)
let isPlayingExplain = false;   // true while a follow-up is playing

// ── Criterion icons (matched to key names from scorer.py) ────────
const CRITERION_ICONS = {
  "domain": "🏛️",
  "emotional": "💬",
  "factual": "🔍",
  "author": "✍️",
  "content": "📄",
  "mdm": "🇨🇦",
};

// ── Small helper: safely get element (returns null gracefully) ────
function el(id) {
  return document.getElementById(id);
}


// ══════════════════════════════════════════════════════════════════
// TAB SWITCHING
// ══════════════════════════════════════════════════════════════════
function switchTab(mode) {
  currentMode = mode;
  ["url", "text"].forEach(m => {
    const tab = el("tab-" + m);
    const wrapper = el("input-" + m + "-wrapper");
    if (tab) tab.classList.toggle("active", m === mode);
    if (tab) tab.setAttribute("aria-selected", m === mode);
    if (wrapper) wrapper.style.display = (m === mode) ? "block" : "none";
  });
}


// ══════════════════════════════════════════════════════════════════
// SECTION VISIBILITY
// ══════════════════════════════════════════════════════════════════
function showSection(id) {
  const displayType = { "loading-section": "flex" };
  ["landing-section", "input-section", "loading-section", "results-section"].forEach(s => {
    const section = el(s);
    if (section) section.style.display = (s === id) ? (displayType[s] || "block") : "none";
  });
}

// Show the analyzer tool (from landing page CTA or header button)
function showAnalyzer() {
  showSection("input-section");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// Go back to the landing page (logo click)
function goToLanding() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (summaryAudio) { summaryAudio.pause(); summaryAudio = null; }
  lastResult = null;
  isPlayingExplain = false;
  showSection("landing-section");
  window.scrollTo({ top: 0, behavior: "smooth" });
  // Trigger demo bar animations again
  setTimeout(() => {
    document.querySelectorAll(".lp-demo-fill").forEach(bar => {
      bar.style.animation = "none";
      bar.offsetHeight; // reflow
      bar.style.animation = "";
    });
  }, 100);
}


// ══════════════════════════════════════════════════════════════════
// LOADING CHECKLIST ANIMATION
// ══════════════════════════════════════════════════════════════════
function animateLoadingChecklist() {
  const ids = ["lc-domain", "lc-emotional", "lc-factual", "lc-author", "lc-content", "lc-mdm"];
  ids.forEach(id => { const e = el(id); if (e) e.classList.remove("done"); });
  const delays = [900, 1800, 3000, 4000, 4900, 5700];
  ids.forEach((id, i) => setTimeout(() => {
    const e = el(id); if (e) e.classList.add("done");
  }, delays[i]));
}


// ══════════════════════════════════════════════════════════════════
// MAIN ANALYSIS FUNCTION
// ══════════════════════════════════════════════════════════════════
async function runAnalysis() {
  const input = currentMode === "url"
    ? (el("url-input") || {}).value || ""
    : (el("text-input") || {}).value || "";

  if (!input.trim()) {
    alert("Please enter a URL or article text first.");
    return;
  }

  const btn = el("analyze-btn");
  if (btn) btn.disabled = true;

  showSection("loading-section");
  animateLoadingChecklist();

  try {
    const response = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: currentMode, input: input.trim() }),
    });

    const data = await response.json();

    if (!response.ok || data.error) {
      showSection("input-section");
      showError(data.error || "Analysis failed. Please try again.");
      return;
    }

    lastResult = data;
    renderResults(data);
    showSection("results-section");
    showFollowUpButtons();
    loadHistory();  // Refresh history sidebar with the new result

  } catch (err) {
    showSection("input-section");
    showError("Network error — is the Flask server running? (" + err.message + ")");
  } finally {
    if (btn) btn.disabled = false;
  }
}


// ══════════════════════════════════════════════════════════════════
// RENDER RESULTS
// ALL getElementById calls use the el() helper which returns null
// safely — no crash if an element is missing.
// ══════════════════════════════════════════════════════════════════
function renderResults(data) {

  // ── Cache badge (from Backboard memory) ──────────────────────
  const cacheBadge = el("cache-badge");
  if (cacheBadge) cacheBadge.style.display = data.from_cache ? "block" : "none";

  // ── Article title ────────────────────────────────────────────
  const titleEl = el("result-article-title");
  if (titleEl) {
    if (data.article_title) {
      titleEl.textContent = "\u201C" + data.article_title + "\u201D";
      titleEl.style.display = "block";
    } else {
      titleEl.style.display = "none";
    }
  }

  // ── Verdict banner class (controls colour) ───────────────────
  const vc = data.verdict_class || "v-uncertain";
  const banner = el("verdict-banner");
  if (banner) banner.className = "verdict-banner " + vc;

  // ── Undeterminable notice ─────────────────────────────────────
  const undeterminableNotice = el("undeterminable-notice");
  if (undeterminableNotice) {
    if (data.is_undeterminable) {
      undeterminableNotice.style.display = "block";
    } else {
      undeterminableNotice.style.display = "none";
    }
  }

  // ── Verdict fields ────────────────────────────────────────────
  setText("result-verdict-title", data.verdict || "");
  // Score is animated by the gauge — initialise to 0, animateGauge counts it up
  const scoreEl = el("result-score");
  if (scoreEl) scoreEl.textContent = "0";
  setText("result-mdm-badge", "Classified as: " + (data.mdm_classification || "Unknown"));
  setText("result-verdict-subtext", data.verdict_subtext || "");

  // Animate the semicircular gauge after a short delay (lets the section paint first)
  setTimeout(() => animateGauge(data.final_score || 0, vc, data.is_undeterminable), 120);

  // ── Core claim ────────────────────────────────────────────────
  const claimSection = el("core-claim-section");
  const claimText = el("core-claim-text");
  if (claimSection) {
    if (data.core_claim) {
      if (claimText) claimText.textContent = data.core_claim;
      claimSection.style.display = "block";
    } else {
      claimSection.style.display = "none";
    }
  }

  // ── Criteria rows ─────────────────────────────────────────────
  const list = el("criteria-list");
  if (list) {
    list.innerHTML = "";
    (data.criteria || []).forEach(c => {
      const score = c.score || 0;
      const tier = score >= 72 ? "score-high" : score >= 45 ? "score-mid" : "score-low";
      const icon = CRITERION_ICONS[c.key] || "📊";

      const badgeText = data.is_undeterminable ? "N/A / 100" : (score + "/100");

      const row = document.createElement("div");
      row.className = "criterion-row " + tier;
      row.innerHTML =
        '<div class="criterion-top">' +
        '<div class="criterion-left">' +
        '<div class="criterion-icon">' + icon + '</div>' +
        '<span class="criterion-label">' + esc(c.label) + '</span>' +
        '<span class="criterion-weight">(' + (c.weight || "") + ')</span>' +
        '</div>' +
        '<span class="criterion-score-badge">' + badgeText + '</span>' +
        '</div>' +
        '<div class="progress-track">' +
        '<div class="progress-fill" data-width="' + score + '%" style="width:0%"></div>' +
        '</div>' +
        '<div class="criterion-reason">' + esc(c.reason) + '</div>';
      list.appendChild(row);
    });
  }

  // Animate progress bars after a tick (lets browser paint first)
  setTimeout(() => {
    document.querySelectorAll(".progress-fill").forEach(bar => {
      bar.style.width = bar.dataset.width;
    });
  }, 80);

  // ── Neutral summary ───────────────────────────────────────────
  const summarySection = el("neutral-summary-section");
  const summaryBody = el("neutral-summary-body");
  if (summarySection && summaryBody) {
    if (data.neutral_summary) {
      // Split on double newlines into paragraphs
      const paragraphs = data.neutral_summary.split(/\n\n+/).filter(p => p.trim());
      summaryBody.innerHTML = paragraphs.map(p => "<p>" + esc(p.trim()) + "</p>").join("");
      summarySection.style.display = "block";
      // Reset toggle to "expanded" state on each new result
      summaryBody.style.display = "block";
      const toggleBtn = el("summary-toggle-btn");
      if (toggleBtn) toggleBtn.textContent = "Hide";
    } else {
      summarySection.style.display = "none";
    }
  }

  // ── Reset voice buttons ───────────────────────────────────────
  const stopBtn = el("stop-btn");
  const speakBtn = el("speak-btn");
  if (stopBtn) stopBtn.style.display = "none";
  if (speakBtn) speakBtn.disabled = false;
}


// ══════════════════════════════════════════════════════════════════
// SCORE GAUGE — animated semicircular arc
// ══════════════════════════════════════════════════════════════════
function animateGauge(score, verdictClass, isUndeterminable = false) {
  const fillEl  = el("gauge-fill");
  const dotEl   = el("gauge-dot");
  const scoreEl = el("result-score");
  if (!fillEl || !dotEl || !scoreEl) return;

  // Remove any previous landed state
  fillEl.classList.remove("landed");
  dotEl.classList.remove("landed");

  // Colour per verdict tier
  const COLOURS = {
    "v-excellent": "#22f088",
    "v-good":      "#22f088",
    "v-uncertain": "#f0c050",
    "v-suspicious":"#ff8b4d",
    "v-bad":       "#ff5a5a",
    "v-undeterminable": "#9ca3af",
  };
  const colour = COLOURS[verdictClass] || "#22f088";

  // Apply colour to arc and dot
  fillEl.style.stroke = colour;
  dotEl.style.fill    = colour;

  // Start fully hidden
  const pathLen = fillEl.getTotalLength ? fillEl.getTotalLength() : 295.31;
  fillEl.style.strokeDasharray  = `${pathLen} ${pathLen}`;
  fillEl.style.strokeDashoffset = pathLen;

  // Position dot at the arc's start point
  const startPt = fillEl.getPointAtLength ? fillEl.getPointAtLength(0) : { x: 16, y: 126 };
  dotEl.setAttribute("cx", startPt.x);
  dotEl.setAttribute("cy", startPt.y);

  if (isUndeterminable) {
    scoreEl.textContent = "N/A";
    fillEl.style.display = "none";
    dotEl.style.display = "none";
    return; // Skip animation entirely
  } else {
    fillEl.style.display = "";
    dotEl.style.display = "";
  }

  const target  = (score / 100) * pathLen;
  const DURATION = 1300; // ms
  const startTime = performance.now();

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function tick(now) {
    const elapsed  = now - startTime;
    const progress = Math.min(elapsed / DURATION, 1);
    const eased    = easeOutCubic(progress);

    // Animate arc fill
    fillEl.style.strokeDashoffset = pathLen - eased * target;

    // Move glowing dot along the arc
    const traveled = eased * target;
    if (fillEl.getPointAtLength && traveled > 0) {
      const pt = fillEl.getPointAtLength(traveled);
      dotEl.setAttribute("cx", pt.x);
      dotEl.setAttribute("cy", pt.y);
    }

    // Count up the score number
    scoreEl.textContent = Math.round(eased * score);

    if (progress < 1) {
      requestAnimationFrame(tick);
    } else {
      // Final state — snap to exact value and trigger idle animations
      scoreEl.textContent = score;
      fillEl.classList.add("landed");
      dotEl.classList.add("landed");
    }
  }

  requestAnimationFrame(tick);
}


// ══════════════════════════════════════════════════════════════════
// ELEVENLABS VOICE — Play
// ══════════════════════════════════════════════════════════════════
async function readVerdictAloud() {
  if (!lastResult) return;

  const speakBtn = el("speak-btn");
  const stopBtn = el("stop-btn");

  if (speakBtn) { speakBtn.disabled = true; speakBtn.textContent = "Generating audio…"; }

  // Pick the weakest criterion to highlight in the readout
  const criteria = lastResult.criteria || [];
  const weakest = criteria.length
    ? criteria.reduce((min, c) => c.score < min.score ? c : min, criteria[0])
    : null;

  const speechText =
    "Verity analysis complete. " +
    (lastResult.is_undeterminable 
      ? "This content has a credibility score of Not Applicable and is rated " 
      : "This content scored " + lastResult.final_score + " out of 100 and is rated ") +
    lastResult.verdict + ". " +
    (lastResult.verdict_subtext || "") + " " +
    "It has been classified as " + lastResult.mdm_classification +
    " under the Canadian Centre for Cyber Security framework. " +
    (weakest
      ? "The area of most concern is " + weakest.label +
      ", which scored " + weakest.score + " out of 100. " + weakest.reason + " "
      : ""
    ) +
    "Always verify information with multiple trusted sources before sharing.";

  try {
    const response = await fetch("/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: speechText }),
    });

    if (!response.ok) throw new Error("Speech generation failed (HTTP " + response.status + ")");

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    if (currentAudio) { currentAudio.pause(); currentAudio = null; }

    currentAudio = new Audio(audioUrl);
    if (stopBtn) stopBtn.style.display = "inline-block";
    if (speakBtn) speakBtn.textContent = "🔊 Playing…";

    currentAudio.play();
    currentAudio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      currentAudio = null;
      if (stopBtn) stopBtn.style.display = "none";
      if (speakBtn) { speakBtn.textContent = "🔊 Read Verdict Aloud"; speakBtn.disabled = false; }
    };

  } catch (err) {
    if (speakBtn) { speakBtn.textContent = "🔊 Read Verdict Aloud"; speakBtn.disabled = false; }
    if (stopBtn) stopBtn.style.display = "none";
    alert("Voice unavailable: " + err.message);
  }
}


// ══════════════════════════════════════════════════════════════════
// ELEVENLABS VOICE — Stop
// ══════════════════════════════════════════════════════════════════
function stopAudio() {
  if (currentAudio) {
    currentAudio.onended = null;  // prevent double-cleanup via dispatch
    currentAudio.pause();
    currentAudio = null;
    const stopBtn = el("stop-btn");
    const speakBtn = el("speak-btn");
    if (stopBtn) stopBtn.style.display = "none";
    if (speakBtn) { speakBtn.textContent = "\uD83D\uDD0A Read Verdict Aloud"; speakBtn.disabled = false; }
  }
}


// ══════════════════════════════════════════════════════════════════
// SUMMARY VOICE — Read neutral summary aloud via ElevenLabs
// ══════════════════════════════════════════════════════════════════
async function readSummaryAloud() {
  if (!lastResult || !lastResult.neutral_summary) return;

  const speakBtn = el("summary-speak-btn");
  const stopBtn  = el("summary-stop-btn");

  if (speakBtn) { speakBtn.disabled = true; speakBtn.textContent = "Generating…"; }

  // Stop any other audio playing
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (summaryAudio) { summaryAudio.pause(); summaryAudio = null; }

  try {
    const response = await fetch("/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: lastResult.neutral_summary }),
    });

    if (!response.ok) throw new Error("Speech generation failed (HTTP " + response.status + ")");

    const audioBlob = await response.blob();
    const audioUrl  = URL.createObjectURL(audioBlob);

    summaryAudio = new Audio(audioUrl);
    if (stopBtn)  stopBtn.style.display  = "inline-block";
    if (speakBtn) speakBtn.textContent   = "🔊 Playing…";

    summaryAudio.play();
    summaryAudio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      summaryAudio = null;
      if (stopBtn)  stopBtn.style.display  = "none";
      if (speakBtn) { speakBtn.textContent = "🔊 Read"; speakBtn.disabled = false; }
    };

  } catch (err) {
    if (speakBtn) { speakBtn.textContent = "🔊 Read"; speakBtn.disabled = false; }
    if (stopBtn)  stopBtn.style.display  = "none";
    alert("Summary voice unavailable: " + err.message);
  }
}

function stopSummaryAudio() {
  if (summaryAudio) {
    summaryAudio.onended = null;  // prevent double-cleanup
    summaryAudio.pause();
    summaryAudio = null;
    const stopBtn = el("summary-stop-btn");
    const speakBtn = el("summary-speak-btn");
    if (stopBtn) stopBtn.style.display = "none";
    if (speakBtn) { speakBtn.textContent = "\uD83D\uDD0A Read"; speakBtn.disabled = false; }
  }
}


// ══════════════════════════════════════════════════════════════════
// RESET — called by logo click or "Analyze Another Article"
// ══════════════════════════════════════════════════════════════════
function resetToInput() {
  if (currentAudio) { currentAudio.onended = null; currentAudio.pause(); currentAudio = null; }
  if (summaryAudio) { summaryAudio.onended = null; summaryAudio.pause(); summaryAudio = null; }
  lastResult = null;
  isPlayingExplain = false;
  const ui = el("url-input"); if (ui) ui.value = "";
  const ti = el("text-input"); if (ti) ti.value = "";
  const followup = el("followup-buttons");
  if (followup) followup.style.display = "none";
  document.querySelectorAll(".error-banner").forEach(b => b.remove());
  // Clear loading checklist done-state for the next analysis
  ["lc-domain","lc-emotional","lc-factual","lc-author","lc-content","lc-mdm"]
    .forEach(id => { const e = el(id); if (e) e.classList.remove("done"); });
  showSection("input-section");
}


// ══════════════════════════════════════════════════════════════════
// ERROR DISPLAY
// ══════════════════════════════════════════════════════════════════
function showError(message) {
  document.querySelectorAll(".error-banner").forEach(b => b.remove());
  const banner = document.createElement("div");
  banner.className = "error-banner";
  banner.textContent = "⚠ " + message;
  const card = document.querySelector(".input-card");
  if (card) card.insertBefore(banner, card.firstChild);
  setTimeout(() => banner.remove(), 8000);
}


// ══════════════════════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════════════════════
// setText — null-safe version of el(id).textContent = val
function setText(id, val) {
  const e = el(id);
  if (e) e.textContent = val;
}

// esc — escape HTML to prevent XSS when injecting user content
function esc(str) {
  const d = document.createElement("div");
  d.textContent = str || "";
  return d.innerHTML;
}

// ══════════════════════════════════════════════════════════════════
// ELEVENLABS FOLLOW-UP (conversational voice questions)
// ══════════════════════════════════════════════════════════════════
async function askFollowUp(questionType) {
  if (!lastResult || isPlayingExplain) return;

  isPlayingExplain = true;
  const stopBtn = el("stop-btn");
  if (stopBtn) stopBtn.style.display = "inline-block";

  // Dim the follow-up buttons while loading
  document.querySelectorAll(".followup-btn").forEach(b => {
    b.disabled = true;
    b.style.opacity = "0.5";
  });

  try {
    const response = await fetch("/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_type: questionType, verdict_data: lastResult }),
    });

    if (!response.ok) throw new Error("Explain failed (HTTP " + response.status + ")");

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);

    if (currentAudio) { currentAudio.pause(); currentAudio = null; }

    currentAudio = new Audio(audioUrl);
    currentAudio.play();
    currentAudio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      currentAudio = null;
      isPlayingExplain = false;
      if (stopBtn) stopBtn.style.display = "none";
      document.querySelectorAll(".followup-btn").forEach(b => {
        b.disabled = false;
        b.style.opacity = "1";
      });
    };
  } catch (err) {
    isPlayingExplain = false;
    if (stopBtn) stopBtn.style.display = "none";
    document.querySelectorAll(".followup-btn").forEach(b => {
      b.disabled = false;
      b.style.opacity = "1";
    });
    alert("Follow-up unavailable: " + err.message);
  }
}


// ══════════════════════════════════════════════════════════════════
// HISTORY — load and render recent analyses
// ══════════════════════════════════════════════════════════════════
async function loadHistory() {
  try {
    const response = await fetch("/history");
    if (!response.ok) return;
    const items = await response.json();
    if (!items || items.length === 0) return;

    const container = el("history-container");
    const list = el("history-list");
    if (!container || !list) return;

    list.innerHTML = "";
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "history-row";

      const scoreClass = item.final_score >= 72 ? "score-high"
                       : item.final_score >= 45 ? "score-mid"
                       : "score-low";

      const label = item.url
        ? item.url.replace(/^https?:\/\//, "").split("/")[0]
        : (item.title || "Pasted text");

      const scoreText = item.is_undeterminable ? "N/A" : (item.final_score + "/100");

      row.innerHTML =
        '<div class="history-row-inner">' +
        '<span class="history-domain">' + esc(label.substring(0, 40)) + (label.length > 40 ? "…" : "") + '</span>' +
        '<span class="history-verdict ' + esc(item.verdict_class) + '">' + esc(item.verdict) + '</span>' +
        '<span class="history-score ' + scoreClass + '">' + scoreText + '</span>' +
        '</div>';

      // Click re-fills the URL input and analyzes
      if (item.url) {
        row.style.cursor = "pointer";
        row.title = "Re-analyze: " + item.url;
        row.addEventListener("click", () => {
          switchTab("url");
          const urlInput = el("url-input");
          if (urlInput) urlInput.value = item.url;
          runAnalysis();
        });
      }

      list.appendChild(row);
    });

    container.style.display = "block";
  } catch (_) {
    // History is non-critical — silently ignore errors
  }
}


// ══════════════════════════════════════════════════════════════════
// NEUTRAL SUMMARY TOGGLE
// ══════════════════════════════════════════════════════════════════
function toggleSummary() {
  const body = el("neutral-summary-body");
  const btn = el("summary-toggle-btn");
  if (!body || !btn) return;
  const isVisible = body.style.display !== "none";
  body.style.display = isVisible ? "none" : "block";
  btn.textContent = isVisible ? "Show" : "Hide";
}


// ══════════════════════════════════════════════════════════════════
// Show follow-up buttons after verdict is rendered
// ══════════════════════════════════════════════════════════════════
function showFollowUpButtons() {
  const followup = el("followup-buttons");
  if (followup) followup.style.display = "block";
}


// Enter key on URL and text fields → analyze
document.addEventListener("DOMContentLoaded", () => {
  const urlInput = el("url-input");
  if (urlInput) urlInput.addEventListener("keydown", e => {
    if (e.key === "Enter") runAnalysis();
  });

  const textInput = el("text-input");
  if (textInput) textInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runAnalysis();
  });

  // Show landing page on initial load
  showSection("landing-section");

  // Load history (rendered when analyzer is shown)
  loadHistory();
});
