# Fathom

An AI-powered web research agent that autonomously searches Google and YouTube, extracts content, and synthesizes comprehensive reports — with full source traceability and version history.

## What It Does

Give Fathom a research topic and it will:

1. Search Google and YouTube for relevant sources
2. Scrape web pages and extract YouTube transcripts
3. Use Claude (via AWS Bedrock) to synthesize findings into a structured report
4. Cite every claim with source IDs linked to the full source content
5. Track changes over time so you can refresh research and see what changed

## How It Works

Fathom has two components that work together:

**Backend (FastAPI)** — Runs the AI agent loop using AWS Bedrock (Claude Sonnet). Manages research projects, the job queue, source storage, and Git-based version history.

**Chrome Extension** — Acts as the scraping layer. It polls the job queue and executes search/scrape tasks by opening real Chrome tabs in the background. This avoids API keys and rate limits entirely.

```
User → FastAPI → Bedrock Agent → Job Queue → Chrome Extension → Google/YouTube
                                                                        ↓
User ← Report ← FastAPI ← Markdown + Sources ←────────────────────────┘
```

## Features

- **Dual-source research** — searches both Google and YouTube in a single session
- **Source traceability** — every claim is cited (`[src-1]`, `[src-2]`) and linked to full source content
- **Seed URLs** — optionally anchor research to specific authoritative sources the agent reads first
- **Research refresh** — re-run research to find updates; supports partial refresh (e.g. "update the pricing section only")
- **Version history** — each research project is a Git repo; refreshes create commits with agent-written change summaries
- **Diff viewer** — side-by-side diffs between any two versions of a report
- **Export** — download reports as Markdown, plain text, or PDF
- **Live activity monitor** — real-time panel showing searches, scrapes, and AI thinking as they happen

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | Vue 3 + Vuetify (CDN, no build step) |
| LLM | AWS Bedrock (Claude Sonnet 4.6) |
| Web scraping | crawl4ai (Playwright-based) |
| Extension | Chrome Manifest V3 |
| Database | SQLite |
| Report storage | Markdown files + Git (via GitPython) |
| Diff rendering | diff2html |

## Prerequisites

- Python 3.10+
- Google Chrome with the Fathom extension installed
- AWS credentials with Bedrock access (Claude Sonnet 4.6 in `us-east-1`)
- crawl4ai installed and Playwright browsers set up

## Setup

**1. Install Python dependencies**
```bash
pip install -r requirements.txt
playwright install
```

**2. Install the Chrome extension**

- Open Chrome and go to `chrome://extensions`
- Enable **Developer mode**
- Click **Load unpacked** and select the `extension/` folder

**3. Start the server**
```bash
start.bat
```

Or directly:
```bash
uvicorn app.main:app --reload --reload-exclude research --reload-exclude logs
```

**4. Open the app**

Go to `http://localhost:8000` in Chrome (must be Chrome — the extension only runs there).

## Usage

1. Click **New Research** and enter your topic
2. Optionally add seed URLs (sources the agent should read first)
3. Click **Start** and watch the live activity panel
4. Once complete, view the report, browse sources, or explore version history
5. Use **Refresh** later to update the research with new findings

## Research Folder

The `research/` folder is local-only (excluded from Git). Each project gets its own subfolder with:
- `report.md` — the generated report
- `sources/` — scraped content for each source
- A Git repo for version history

To share research on GitHub, move it to `research-public/` which is tracked.

## AWS Setup

Fathom uses the AWS SDK with no hardcoded credentials. It works with:
- IAM roles (e.g. on EC2)
- AWS CLI configured credentials (`aws configure`)
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

Bedrock model access for **Claude Sonnet 4.6** must be enabled in the `us-east-1` region.
