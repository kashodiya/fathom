# AI Research Agent

## What It Does
Given a research topic, the agent searches YouTube and Google, finds relevant videos, extracts their metadata and transcripts, and synthesizes a research report using an AWS Bedrock LLM.

## Constraints
- No Google/YouTube login
- No Google or YouTube APIs
- Stealth scraping: runs inside a real Chrome browser session to mimic organic traffic

## Architecture
Two components that communicate via a job queue:

**Web App (localhost)** — the agent brain
- Accepts a research topic from the user
- Runs an agent loop powered by AWS Bedrock
- Manages a job queue (REST API)
- Renders the final research report

**Chrome Extension** — the stealth scraping hands
- Polls the job queue for pending jobs
- Executes each job inside a real Chrome tab (background, not active)
- Posts results back to the queue
- No AI logic — just dumb tools

## Agent Tools
**Chrome Extension** (handles all Google/YouTube — stealth via real browser session):
- `search_youtube(query)` → list of video URLs + snippets
- `search_google(query)` → list of URLs + snippets
- `get_video_metadata(url)` → title, description, channel, publish date, views
- `get_transcript(url)` → timestamped transcript text

**crawl4ai** (handles all other web pages — runs locally via Playwright):
- `scrape_page(url)` → clean markdown content from any non-Google/YouTube URL

## Research Settings (per research session)
- **Brief** — free-text description of what to research, the angle, and desired outcome. May include an optional freshness hint (e.g. "focus on sources from the last 3 months")
- **Seed URLs** — optional list of URLs the agent must scrape first, before doing its own searches (anchors the research to known authoritative sources)
- **Sources** — choose one or both:
  - `Web Search` — Google search + scrape web pages
  - `YouTube` — YouTube search + extract transcripts
- **Parallelism** — how many jobs the extension runs concurrently (default: 1, max: 5)

## Agent Loop
1. User submits a brief + optional seed URLs + sources config
2. Agent scrapes seed URLs first (if any) — these are always included
3. Agent reads the brief and plans its searches (what to search on Google, what to search on YouTube)
4. Agent issues search jobs based on selected sources → extension returns results
5. Agent selects which URLs are worth scraping based on the brief
6. Agent issues scrape jobs (metadata + transcript for videos, page content for web pages)
7. Agent may issue follow-up searches based on what it finds (iterative research)
8. Agent notes publication date on each source — flags anything older than 1 year as potentially stale
9. Agent synthesizes all gathered content → returns structured report

## Job Queue
- Backed by SQLite `jobs` table — no separate queue infrastructure
- Schema: `id, research_id, type, payload, status, result, created_at, updated_at`
- Status flow: `pending → running → done | failed`
- Extension polls `GET /jobs/next` every ~2 seconds, posts result to `POST /jobs/:id/result`
- Jobs processed sequentially (stealth) or max 2 concurrent

## Queue Visibility
**Frontend:**
- Live job status panel on each research page
- Polls `GET /jobs?research_id=x` every 2 seconds while research is active
- Each job displayed as a row: type, target URL, status (color-coded)
  - Grey = pending, Blue = running, Green = done, Red = failed

**Backend:**
- Python `logging` module → `logs/app.log`
- Every job state transition logged: `[INFO] job 42 (get_transcript) → running`
- Every agent decision logged: `[INFO] agent selected 5 videos for deep scrape`
- Errors logged with full traceback
- FastAPI access logs enabled

## Traceability
Every claim in the report must be traceable back to its source.

- Agent cites source IDs inline when synthesizing the report (e.g. `[src-1]`, `[src-2]`)
- `sources` table records every scraped URL: type, title, scraped_at, file_path
- Report footer includes a full reference list: source ID, title, URL, type, date scraped
- UI shows a **Sources** tab alongside the report — click any source to view its raw content
- Sources are also linked from the report inline (clickable in UI, footnotes in PDF export)

## Research Management
Each research session is a folder tracked as a **git repository**. Every refresh is a commit — giving a full audit trail of what changed and why.

**Actions per research project:**
- **View** — report + sources tab (full traceability)
- **Refresh** — re-run the agent, commit changes with an agent-written summary
- **Update** — edit the topic or add follow-up questions and re-run
- **Delete** — remove the project folder and all its data
- **Export** — download the report as PDF, Markdown, or plain text (sources included)

**Refresh & Change Tracking:**
- **Full refresh** — re-run the whole research with the same brief and seed URLs
- **Partial refresh** — user specifies an aspect to refresh (e.g. "refresh the pricing section only"); agent reads existing report, searches only for that aspect, updates only that section
- After each refresh the agent writes a structured commit message:
  ```
  Refresh 2026-04-12: pricing section updated

  What changed:
  - Cursor raised Pro price from $20 to $25/month [new src-22]
  - Windsurf added free tier [new src-23]
  - GitHub Copilot enterprise pricing unchanged

  Stale sources removed:
  - [src-4] getdx.com (published Jan 2025, outdated)

  New sources added:
  - [src-22] cursor.com/pricing (April 2026)
  - [src-23] windsurf.ai/blog/free-tier (April 2026)
  ```
- Each research folder is a git repo, initialized on first run
- `gitpython` used for all git operations

**History tab (per research project):**
- Lists all past refreshes (date + commit message)
- Click any refresh → shows full diff of what changed (added/removed lines)
- Rendered using `diff2html` in the UI

**Research list view (home screen):**
- Shows all past research projects (topic, date, last refreshed, source count)
- Searchable/filterable

## DB Schema Updates
- `research` table gains: `seed_urls TEXT` (JSON array of URLs), `refresh_aspect TEXT` (null = full refresh)
- `sources` table gains: `published_date TEXT`, `is_stale INTEGER` (0/1)

## Storage Layout
```
research/
├── db.sqlite                  ← all structured data (projects, sources, job queue)
└── {topic-slug}/
    ├── report.md              ← final synthesized report
    └── sources/
        ├── yt-{video-id}.md   ← transcript + metadata
        └── web-{hash}.md      ← scraped page content
```

## Stack
- **Server:** Python, FastAPI (async, built-in /docs)
- **UI:** Single `index.html` — Vue 3 + Vuetify 3.12.5 + VueRouter via CDN (no build step)
- **LLM:** AWS Bedrock (IAM role auth, no keys needed)
- **Storage:** SQLite for structured data, Markdown files for content
- **Extension:** Chrome Manifest V3, background service worker
- **Web scraping:** crawl4ai (local, Playwright-based)
- **Change tracking:** gitpython + diff2html

---

## Implementation Phases

### Phase 1 — Project Skeleton & DB `[x]`
- Folder structure, FastAPI app, SQLite schema, DB init
- gitpython: init repo on research folder creation
- ✅ Verify: server starts, `/docs` loads, DB file created

### Phase 2 — Chrome Extension + Job Queue `[x]`
- Extension polls `/jobs/next`, executes a hardcoded test job, posts result back
- No real scraping yet — just the plumbing
- ✅ Verify: create test job via `/docs`, watch extension pick it up and return result

### Phase 3 — Extension Scrapers `[x]`
- Implement all four tools: YouTube search, Google search, video metadata, transcript
- ✅ Verify: trigger each tool manually via `/docs`, check returned data

### Phase 4 — crawl4ai Integration `[x]`
- Wire up `scrape_page` on the Python side
- ✅ Verify: give it a URL, get back clean markdown

### Phase 5 — Bedrock Agent Loop `[x]`
- Agent takes a topic, plans jobs, processes results, iterates, writes report
- Source citation inline (`[src-1]` etc.), reference list at end
- ✅ Verify: run a real research topic end-to-end, check report + sources

### Phase 6 — UI `[x]`
- `index.html`: research list, new research form, report view, sources tab, live job status panel
- ✅ Verify: full flow visible in browser, job status updates in real time

### Phase 7 — Research Management `[ ]`
- Refresh (re-run + git commit with agent summary), update, delete
- History tab with diff view (diff2html)
- Export: PDF, Markdown, plain text
- ✅ Verify: refresh a research, view diff, export PDF
