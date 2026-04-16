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

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — modern Python package manager (install with `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Google Chrome with the Fathom extension installed
- **LLM Provider** (one of):
  - AWS credentials with Bedrock access (Claude Sonnet/Haiku 4.x in `us-east-1`)
  - OR Anthropic API key
  - OR OpenAI API key
  - OR any OpenAI-compatible API endpoint
- crawl4ai installed and Playwright browsers set up

## Setup

**1. Install Python dependencies**
```bash
uv sync
uv run playwright install
```

**2. Configure LLM provider**

Copy the example config and edit:
```bash
cp .env.example .env
```

Choose your LLM provider by editing `.env`:

**Option A: AWS Bedrock (default)**
```bash
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
LLM_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
```

**Option B: Anthropic API**
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_API_KEY=your_anthropic_api_key
LLM_MODEL_ID=claude-sonnet-4-20250514
```

**Option C: OpenAI**
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_openai_api_key
LLM_MODEL_ID=gpt-4o
```

**Option D: Local LLM (Ollama, etc.)**
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=dummy
LLM_MODEL_ID=llama3.2
```

**3. Install the Chrome extension**

- Open Chrome and go to `chrome://extensions`
- Enable **Developer mode**
- Click **Load unpacked** and select the `extension/` folder

**4. Start the server**
```bash
./start.sh    # Linux/Mac
start.bat     # Windows
```

Or directly:
```bash
uv run uvicorn app.main:app --reload --reload-exclude research --reload-exclude logs
```

**5. Open the app**

Go to `http://localhost:9092` in Chrome (must be Chrome — the extension only runs there).

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

## LLM Provider Setup

### AWS Bedrock
Fathom uses the AWS SDK with no hardcoded credentials. It works with:
- IAM roles (e.g. on EC2)
- AWS CLI configured credentials (`aws configure`)
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

Bedrock model access for **Claude models** must be enabled in the `us-east-1` region.

### Anthropic/OpenAI API
Set your API key in `.env`:
```bash
LLM_PROVIDER=openai
LLM_API_KEY=your_api_key
```

### Local LLM
Run a local LLM server (e.g., Ollama) with OpenAI-compatible API and configure the endpoint in `.env`.
