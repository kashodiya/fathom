const API = "http://localhost:8000";

let isProcessing = false;

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const randDelay = (min, max) => sleep(min + Math.random() * (max - min));

// ── Boot: start polling via alarms ────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: 0.1 }); // ~6s
  console.log("[agent] extension installed, polling started");
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: 0.1 });
  console.log("[agent] extension started, polling started");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "poll") poll();
});

// ── Poll for next job ─────────────────────────────────────────────────────────
async function poll() {
  if (isProcessing) return;

  let job;
  try {
    const res = await fetch(`${API}/jobs/next`);
    job = await res.json();
  } catch (e) {
    return; // Server not reachable — silently skip
  }

  if (!job) return;

  isProcessing = true;
  console.log(`[agent] picked up job ${job.id} (${job.type})`, job.payload);

  try {
    const result = await executeJob(job);
    await postResult(job.id, "done", result);
    console.log(`[agent] job ${job.id} done`, result);
  } catch (e) {
    console.error(`[agent] job ${job.id} failed:`, e.message);
    await postResult(job.id, "failed", { error: e.message });
  } finally {
    // Random pause after each job before accepting the next (3–8s)
    await randDelay(3000, 8000);
    isProcessing = false;
  }
}

// ── Post result back ──────────────────────────────────────────────────────────
async function postResult(jobId, status, result) {
  await fetch(`${API}/jobs/${jobId}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, result }),
  });
}

// ── Job router ────────────────────────────────────────────────────────────────
async function executeJob(job) {
  switch (job.type) {
    case "test":
      return { echo: job.payload, handled_by: "extension", timestamp: new Date().toISOString() };
    case "search_google":
      return scrapeInTab(
        `https://www.google.com/search?q=${encodeURIComponent(job.payload.query)}`,
        scrapeGoogleSearch
      );
    case "search_youtube":
      return scrapeInTab(
        `https://www.youtube.com/results?search_query=${encodeURIComponent(job.payload.query)}`,
        scrapeYouTubeSearch
      );
    case "get_video_metadata":
      return scrapeInTab(job.payload.url, scrapeVideoMetadata);
    case "get_transcript":
      return scrapeInTab(job.payload.url, scrapeTranscript);
    default:
      throw new Error(`Unknown job type: ${job.type}`);
  }
}

// ── Tab scraping helper ───────────────────────────────────────────────────────
// Opens a background tab, waits for load + human-like pause, injects scraper, closes tab.
function scrapeInTab(url, scraperFunc) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: false }, (tab) => {
      const listener = async (tabId, info) => {
        if (tabId !== tab.id || info.status !== "complete") return;
        chrome.tabs.onUpdated.removeListener(listener);

        // Human-like reading delay before scraping (2–5s)
        await randDelay(2000, 5000);

        chrome.scripting.executeScript(
          { target: { tabId: tab.id }, func: scraperFunc },
          (results) => {
            chrome.tabs.remove(tab.id);
            if (chrome.runtime.lastError)
              return reject(new Error(chrome.runtime.lastError.message));
            if (!results?.[0])
              return reject(new Error("No result from scraper"));
            resolve(results[0].result);
          }
        );
      };
      chrome.tabs.onUpdated.addListener(listener);
    });
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// Scraper functions — injected into tabs, NO closures, NO imports
// Each must be a plain self-contained function.
// ═════════════════════════════════════════════════════════════════════════════

// ── Google Search ─────────────────────────────────────────────────────────────
function scrapeGoogleSearch() {
  const seen = new Set();
  const results = [];
  document.querySelectorAll("div.g, div[data-hveid]").forEach((el) => {
    const titleEl   = el.querySelector("h3");
    const linkEl    = el.querySelector("a[href]");
    const snippetEl = el.querySelector("div.VwiC3b, div[data-sncf], span.aCOpRe");
    if (!titleEl || !linkEl) return;
    const href = linkEl.getAttribute("href");
    if (!href || href.startsWith("/search") || href.startsWith("#")) return;
    if (seen.has(href)) return;  // deduplicate
    seen.add(href);
    results.push({
      title:   titleEl.innerText.trim(),
      url:     href,
      snippet: snippetEl ? snippetEl.innerText.trim() : "",
    });
  });
  return { query: location.href, results: results.slice(0, 10) };
}

// ── YouTube Search ────────────────────────────────────────────────────────────
async function scrapeYouTubeSearch() {
  // Wait for results to render
  await new Promise(r => setTimeout(r, 3000));

  const results = [];
  document.querySelectorAll("ytd-video-renderer").forEach((el) => {
    const titleEl   = el.querySelector("#video-title");
    const channelEl = el.querySelector("#channel-name a, ytd-channel-name a");
    const metaSpans = el.querySelectorAll("#metadata-line span.inline-metadata-item");
    const descEl    = el.querySelector("yt-formatted-string#description-text");
    if (!titleEl) return;
    const href = titleEl.getAttribute("href");
    if (!href) return;
    results.push({
      title:   titleEl.innerText.trim(),
      url:     "https://www.youtube.com" + href,
      channel: channelEl ? channelEl.innerText.trim() : "",
      views:   metaSpans[0] ? metaSpans[0].innerText.trim() : "",
      date:    metaSpans[1] ? metaSpans[1].innerText.trim() : "",
      snippet: descEl    ? descEl.innerText.trim()    : "",
    });
  });
  return { query: location.href, results: results.slice(0, 10) };
}

// ── YouTube Video Metadata ────────────────────────────────────────────────────
async function scrapeVideoMetadata() {
  function waitFor(selector, timeout = 10000) {
    return new Promise((resolve, reject) => {
      const el = document.querySelector(selector);
      if (el && el.innerText.trim()) return resolve(el);
      const observer = new MutationObserver(() => {
        const found = document.querySelector(selector);
        if (found && found.innerText.trim()) { observer.disconnect(); resolve(found); }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => { observer.disconnect(); reject(new Error(`Timeout: ${selector}`)); }, timeout);
    });
  }

  // Wait for title to confirm page has rendered
  try { await waitFor("h1.ytd-watch-metadata, ytd-watch-metadata h1"); }
  catch (e) { /* proceed anyway */ }

  const get = (sels) => {
    for (const sel of sels) {
      const el = document.querySelector(sel);
      if (el?.innerText?.trim()) return el.innerText.trim();
    }
    return "";
  };

  return {
    url:         location.href,
    title:       get(["h1.ytd-watch-metadata yt-formatted-string", "ytd-watch-metadata h1 yt-formatted-string", "h1.style-scope yt-formatted-string"]),
    channel:     get(["ytd-video-owner-renderer ytd-channel-name a", "ytd-channel-name yt-formatted-string a", "#channel-name a"]),
    views:       get(["ytd-video-view-count-renderer span.view-count", "span.view-count"]),
    upload_date: get(["ytd-video-primary-info-renderer #info-strings yt-formatted-string", "#info-strings yt-formatted-string"]),
    description: get(["ytd-text-inline-expander yt-attributed-string span", "#description yt-formatted-string", "ytd-expander yt-formatted-string"]),
  };
}

// ── YouTube Transcript ────────────────────────────────────────────────────────
async function scrapeTranscript() {
  // YouTube embeds all page data in ytInitialPlayerResponse / ytInitialData on the page.
  // The timedtext API URL can be extracted from there — no UI interaction needed.

  // 1. Extract player response JSON from page source
  const scripts = Array.from(document.querySelectorAll("script"));
  let playerResponse = null;
  for (const s of scripts) {
    const m = s.textContent.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\});/s);
    if (m) { try { playerResponse = JSON.parse(m[1]); break; } catch {} }
  }

  if (!playerResponse) return { url: location.href, error: "ytInitialPlayerResponse not found", segments: [] };

  // 2. Find caption tracks
  const captionTracks =
    playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  if (!captionTracks.length) return { url: location.href, error: "no captions available", segments: [] };

  // Prefer English, fall back to first available
  const track = captionTracks.find(t => t.languageCode === "en") || captionTracks[0];

  // 3. Fetch transcript as JSON3 (more reliable than XML/VTT)
  const jsonUrl = track.baseUrl.replace(/&fmt=[^&]*/g, "") + "&fmt=json3";
  let data;
  try {
    const res = await fetch(jsonUrl);
    data = await res.json();
  } catch (e) {
    return { url: location.href, error: `fetch failed: ${e.message}`, segments: [] };
  }

  // 4. Parse JSON3 events into segments
  const segments = [];
  for (const event of data.events || []) {
    if (!event.segs) continue;
    const text = event.segs.map(s => s.utf8 || "").join("").replace(/\n/g, " ").trim();
    if (!text || text === "\n") continue;
    const ms   = event.tStartMs || 0;
    const mins = Math.floor(ms / 60000).toString().padStart(2, "0");
    const secs = Math.floor((ms % 60000) / 1000).toString().padStart(2, "0");
    segments.push({ time: `${mins}:${secs}`, text });
  }

  return { url: location.href, language: track.languageCode || "unknown", segments };
}
