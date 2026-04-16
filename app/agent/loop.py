import asyncio
import hashlib
import json
import logging
import os
import re
import aiosqlite
import git

from datetime import date
from app.agent.prompts import get_system_prompt, get_refresh_user_message
from app.agent.tools import TOOL_DEFINITIONS
from app.scraper import scrape_page
from app.db import DB_PATH
from app.llm_client import get_llm_client
from app.config import get_model_id, JOB_POLL_INTERVAL, JOB_TIMEOUT

logger = logging.getLogger(__name__)

RESEARCH_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "research")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_update_research_status(research_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE research SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, research_id),
        )
        await db.commit()


async def db_clear_stop_flag(research_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE research SET stop_requested = 0 WHERE id = ?", (research_id,)
        )
        await db.commit()


async def db_create_job(research_id: int, job_type: str, payload: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT INTO jobs (research_id, type, payload) VALUES (?, ?, ?) RETURNING id",
            (research_id, job_type, json.dumps(payload)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    logger.info(f"job {row[0]} ({job_type}) created")
    return row[0]


async def db_wait_for_job(job_id: int) -> dict:
    """Poll DB until job is done or failed. Returns result dict."""
    elapsed = 0
    while elapsed < JOB_TIMEOUT:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, result FROM jobs WHERE id = ?", (job_id,)
            ) as cur:
                row = await cur.fetchone()
        if row and row["status"] in ("done", "failed"):
            result = json.loads(row["result"]) if row["result"] else {}
            if row["status"] == "failed":
                logger.warning(f"job {job_id} failed: {result.get('error')}")
            return result
        await asyncio.sleep(JOB_POLL_INTERVAL)
        elapsed += JOB_POLL_INTERVAL
    raise TimeoutError(f"job {job_id} timed out after {JOB_TIMEOUT}s")


async def db_is_stop_requested(research_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT stop_requested FROM research WHERE id = ?", (research_id,)
        ) as cur:
            row = await cur.fetchone()
    return bool(row and row["stop_requested"])


async def db_update_job(job_id: int, status: str, result: dict = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET status = ?, result = ?, updated_at = datetime('now') WHERE id = ?",
            (status, json.dumps(result or {}), job_id),
        )
        await db.commit()


async def db_add_source(research_id: int, src_type: str, url: str, title: str, snippet: str, file_path: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT INTO sources (research_id, type, url, title, snippet, file_path, scraped_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now')) RETURNING id",
            (research_id, src_type, url, title, snippet, file_path),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return row[0]


# ── File helpers ──────────────────────────────────────────────────────────────

def research_folder(slug: str) -> str:
    return os.path.join(RESEARCH_DIR, slug)


def write_source_file(slug: str, filename: str, content: str) -> str:
    path = os.path.join(research_folder(slug), "sources", filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def write_report_file(slug: str, content: str):
    path = os.path.join(research_folder(slug), "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def git_commit(slug: str, message: str):
    repo = git.Repo(research_folder(slug))
    repo.git.add(A=True)
    if repo.is_dirty(index=True):
        repo.index.commit(message)
        logger.info(f"git commit: {message}")


def url_to_filename(url: str, prefix: str) -> str:
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{prefix}-{h}.md"


def video_id_from_url(url: str) -> str:
    m = re.search(r"v=([^&]+)", url)
    return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:8]


# ── Tool execution ────────────────────────────────────────────────────────────

async def execute_tool(name: str, inputs: dict, research_id: int, slug: str, sources: list) -> str:
    """Execute a tool call and return a string result for the agent."""

    if name == "search_google":
        job_id = await db_create_job(research_id, "search_google", inputs)
        result = await db_wait_for_job(job_id)
        results = result.get("results", [])
        logger.info(f"search_google '{inputs['query']}' → {len(results)} results")
        return json.dumps(results)

    elif name == "search_youtube":
        job_id = await db_create_job(research_id, "search_youtube", inputs)
        result = await db_wait_for_job(job_id)
        results = result.get("results", [])
        logger.info(f"search_youtube '{inputs['query']}' → {len(results)} results")
        return json.dumps(results)

    elif name == "get_video_metadata":
        job_id = await db_create_job(research_id, "get_video_metadata", inputs)
        result = await db_wait_for_job(job_id)
        # Save as source file
        vid_id = video_id_from_url(inputs["url"])
        filename = f"yt-{vid_id}.md"
        content = f"# {result.get('title', 'Unknown')}\n\n"
        content += f"**Channel:** {result.get('channel', '')}\n"
        content += f"**Views:** {result.get('views', '')}\n"
        content += f"**Upload Date:** {result.get('upload_date', '')}\n"
        content += f"**URL:** {inputs['url']}\n\n"
        content += f"## Description\n\n{result.get('description', '')}\n"
        file_path = write_source_file(slug, filename, content)
        src_id = await db_add_source(research_id, "youtube", inputs["url"], result.get("title", ""), result.get("description", "")[:200], file_path)
        src_tag = f"[src-{src_id}]"
        sources.append({"id": src_id, "tag": src_tag, "type": "youtube", "url": inputs["url"], "title": result.get("title", "")})
        logger.info(f"video metadata saved as {src_tag}: {result.get('title')}")
        return json.dumps({**result, "source_id": src_tag})

    elif name == "get_transcript":
        job_id = await db_create_job(research_id, "get_transcript", inputs)
        result = await db_wait_for_job(job_id)
        segments = result.get("segments", [])
        if not segments:
            return json.dumps({"error": result.get("error", "no transcript"), "source_id": None})
        # Append transcript to existing source file (clean prose, no timestamps)
        vid_id = video_id_from_url(inputs["url"])
        filename = f"yt-{vid_id}.md"
        clean_text = " ".join(s["text"] for s in segments)
        src_path = os.path.join(research_folder(slug), "sources", filename)
        with open(src_path, "a", encoding="utf-8") as f:
            f.write(f"\n## Transcript\n\n{clean_text}\n")
        # Truncate for agent context (first 1500 chars, with timestamps for navigation)
        preview_lines = "\n".join(f"[{s['time']}] {s['text']}" for s in segments)
        preview = preview_lines[:1500] + ("..." if len(preview_lines) > 1500 else "")
        logger.info(f"transcript saved: {len(segments)} segments for {inputs['url']}")
        return json.dumps({"segments": len(segments), "preview": preview})

    elif name == "scrape_page":
        job_id = await db_create_job(research_id, "scrape_page", inputs)
        try:
            result = await asyncio.wait_for(scrape_page(inputs["url"]), timeout=30)
        except asyncio.TimeoutError:
            await db_update_job(job_id, "failed", {"error": "timeout"})
            logger.warning(f"scrape_page timeout: {inputs['url']}")
            return json.dumps({"error": "scrape timed out"})
        if result.get("error") or not result.get("content"):
            await db_update_job(job_id, "failed", {"error": result.get("error", "empty content")})
            return json.dumps({"error": result.get("error", "empty content")})
        filename = url_to_filename(inputs["url"], "web")
        content = f"# {result.get('title', inputs['url'])}\n\n**URL:** {inputs['url']}\n\n{result['content']}"
        file_path = write_source_file(slug, filename, content)
        src_id = await db_add_source(research_id, "web", inputs["url"], result.get("title", ""), result["content"][:200], file_path)
        src_tag = f"[src-{src_id}]"
        sources.append({"id": src_id, "tag": src_tag, "type": "web", "url": inputs["url"], "title": result.get("title", "")})
        await db_update_job(job_id, "done", {"title": result.get("title", ""), "source_id": src_tag})
        logger.info(f"web page saved as {src_tag}: {result.get('title')}")
        # Truncate for agent context (first 1500 chars)
        preview = result["content"][:1500] + ("..." if len(result["content"]) > 1500 else "")
        return json.dumps({"source_id": src_tag, "title": result.get("title"), "content": preview})

    elif name == "write_report":
        return "__WRITE_REPORT__"

    return json.dumps({"error": f"unknown tool: {name}"})


# ── LLM client ────────────────────────────────────────────────────────────────
# (Moved to app/llm_client.py)


# ── Main agent loop ───────────────────────────────────────────────────────────

def _source_instructions(sources_config: str) -> str:
    return {
        "web":     "Use search_google and scrape_page only (no YouTube).",
        "youtube": "Use search_youtube, get_video_metadata, get_transcript only (no Google/web).",
        "both":    "Use all available tools — Google search, YouTube search, web scraping, and video transcripts.",
    }.get(sources_config, "Use all available tools.")


async def _run_loop(research_id: int, slug: str, brief: str, messages: list, is_refresh: bool, aspect: str | None, template: str = ""):
    """Shared LLM agent loop. Called by both run_agent and run_agent_refresh."""
    llm_client = get_llm_client()
    model_id = get_model_id()
    sources = []
    max_iterations = 20
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"[agent] iteration {iteration} — calling LLM ({model_id})")

        llm_job_id = await db_create_job(research_id, "bedrock_call", {"model": model_id, "iteration": iteration})
        await db_update_job(llm_job_id, "running")
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: llm_client.converse(
                    system=[{"text": get_system_prompt(template)}],
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=8192,
                    temperature=0.3,
                )),
                timeout=180,
            )
        except asyncio.TimeoutError:
            logger.error(f"[agent] LLM timeout after 180s on iteration {iteration}")
            await db_update_job(llm_job_id, "failed", {"error": "timeout"})
            await db_update_research_status(research_id, "failed")
            return
        except Exception as e:
            logger.error(f"[agent] LLM error: {e}")
            await db_update_job(llm_job_id, "failed", {"error": str(e)})
            await db_update_research_status(research_id, "failed")
            return

        output_message = response["output"]["message"]
        messages.append(output_message)
        stop_reason = response["stopReason"]

        tool_use_blocks = [b["toolUse"] for b in output_message["content"] if "toolUse" in b]
        await db_update_job(llm_job_id, "done", {"stop_reason": stop_reason, "tool_calls": [b["name"] for b in tool_use_blocks]})
        logger.info(f"[agent] stop_reason={stop_reason}, tool_calls={[b['name'] for b in tool_use_blocks]}")

        if stop_reason == "end_turn":
            text = "\n\n".join(b["text"] for b in output_message["content"] if "text" in b)
            if text:
                write_report_file(slug, text)
                label = f"Refresh {date.today()}" if is_refresh else f"Research complete"
                git_commit(slug, f"{label}: {brief[:60]}")
                logger.info("[agent] report written (end_turn fallback)")
            break

        if stop_reason not in ("tool_use", "max_tokens"):
            logger.warning(f"[agent] unexpected stop_reason: {stop_reason}")
            break

        if stop_reason == "max_tokens" and not tool_use_blocks:
            logger.warning("[agent] max_tokens hit with no tool calls — forcing report write")
            text = "\n\n".join(b["text"] for b in output_message["content"] if "text" in b)
            if text:
                write_report_file(slug, text)
                git_commit(slug, f"Research complete (max_tokens): {brief[:60]}")
            await db_update_research_status(research_id, "done")
            return

        tool_results = []
        report_content = None
        commit_summary = ""

        for block in output_message["content"]:
            if "toolUse" not in block:
                continue
            tool_name   = block["toolUse"]["name"]
            tool_inputs = block["toolUse"]["input"]
            tool_use_id = block["toolUse"]["toolUseId"]
            logger.info(f"[agent] tool call: {tool_name}({json.dumps(tool_inputs)[:100]})")

            result_str = await execute_tool(tool_name, tool_inputs, research_id, slug, sources)

            if result_str == "__WRITE_REPORT__":
                report_content  = tool_inputs.get("content", "")
                commit_summary  = tool_inputs.get("commit_summary", "")
                tool_results.append({"toolResult": {"toolUseId": tool_use_id, "content": [{"text": "Report saved successfully."}]}})
            else:
                tool_results.append({"toolResult": {"toolUseId": tool_use_id, "content": [{"text": result_str}]}})

        if not tool_results:
            logger.warning("[agent] no tool results to send back — breaking")
            break

        messages.append({"role": "user", "content": tool_results})

        if len(sources) >= 10:
            logger.info(f"[agent] {len(sources)} sources gathered — nudging to finalize")
            messages.append({"role": "user", "content": [{"text": f"You have now gathered {len(sources)} sources which is sufficient. Please call write_report now to finalize your research report."}]})

        if report_content:
            write_report_file(slug, report_content)
            if is_refresh:
                aspect_label = f"partial: {aspect[:40]}" if aspect else "full refresh"
                commit_msg = f"Refresh {date.today()} ({aspect_label})\n\n{commit_summary}" if commit_summary else f"Refresh {date.today()} ({aspect_label})"
            else:
                commit_msg = f"Research complete: {brief[:60]}\n\n{len(sources)} sources collected."
            git_commit(slug, commit_msg)
            logger.info(f"[agent] research complete. {len(sources)} sources.")
            await db_update_research_status(research_id, "done")
            return

        # Check for stop request between iterations
        if await db_is_stop_requested(research_id):
            logger.info(f"[agent] stop requested for research {research_id} — forcing synthesis")
            await _force_synthesis(llm_client, research_id, slug, brief, messages, sources, reason="stopped", template=template)
            return

    logger.warning(f"[agent] max iterations reached for research {research_id} — forcing final synthesis")
    await _force_synthesis(llm_client, research_id, slug, brief, messages, sources, reason="max_iterations", template=template)


async def _force_synthesis(llm_client, research_id: int, slug: str, brief: str, messages: list, sources: list, reason: str, template: str = ""):
    """Force a final LLM call to write a report from whatever has been gathered."""
    model_id = get_model_id()
    note = "stopped by user" if reason == "stopped" else "max iterations reached"
    prompt = (
        "The user has requested to stop research early. Using all the information you have gathered so far, "
        "call write_report now to produce the best possible report. Do not search for more information."
        if reason == "stopped" else
        "You have reached the maximum number of research iterations. Using all the information you have gathered so far, "
        "call write_report now to produce the best possible report. Do not search for more information."
    )
    llm_job_id = await db_create_job(research_id, "bedrock_call", {"model": model_id, "iteration": reason})
    try:
        messages.append({"role": "user", "content": [{"text": prompt}]})
        response = llm_client.converse(
            system=[{"text": get_system_prompt(template)}],
            messages=messages,
            tools=TOOL_DEFINITIONS,
            max_tokens=8192,
            temperature=0.3,
        )
        output_message = response["output"]["message"]
        await db_update_job(llm_job_id, "done", {"stop_reason": response["stopReason"], "note": note})
        for block in output_message["content"]:
            if "toolUse" in block and block["toolUse"]["name"] == "write_report":
                write_report_file(slug, block["toolUse"]["input"].get("content", ""))
                git_commit(slug, f"Research complete ({reason}): {brief[:60]}\n\n{len(sources)} sources collected.")
                logger.info(f"[agent] forced synthesis report written ({reason})")
                break
        else:
            text = "\n\n".join(b["text"] for b in output_message["content"] if "text" in b)
            if text:
                write_report_file(slug, text)
                git_commit(slug, f"Research complete (fallback): {brief[:60]}")
                logger.info("[agent] fallback text report written")
    except Exception as e:
        logger.error(f"[agent] forced synthesis error: {e}")
        await db_update_job(llm_job_id, "failed", {"error": str(e)})
    await db_update_research_status(research_id, "done")


async def run_agent(research_id: int, slug: str, brief: str, sources_config: str, template: str = ""):
    logger.info(f"[agent] starting research: '{brief}' (id={research_id})")
    await db_clear_stop_flag(research_id)
    await db_update_research_status(research_id, "running")
    src_instr = _source_instructions(sources_config)
    messages = [{"role": "user", "content": [{"text": f"## Research Brief\n\n{brief}\n\n## Sources\n{src_instr}\n\nPlan your searches based on this brief and begin research now."}]}]
    await _run_loop(research_id, slug, brief, messages, is_refresh=False, aspect=None, template=template)


async def run_agent_refresh(research_id: int, slug: str, brief: str, sources_config: str, aspect: str | None = None, template: str = ""):
    logger.info(f"[agent] refreshing research: '{brief}' (id={research_id}, aspect={aspect!r})")

    # Read previous report
    report_path = os.path.join(research_folder(slug), "report.md")
    previous_report = open(report_path, encoding="utf-8").read() if os.path.exists(report_path) else ""

    # Full refresh: wipe old sources so the report is built fresh.
    # Partial refresh: keep existing sources — the agent only adds new ones for the specified aspect.
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM jobs WHERE research_id = ? AND status != 'running'", (research_id,))
        if not aspect:
            await db.execute("DELETE FROM sources WHERE research_id = ?", (research_id,))
        await db.commit()

    if not aspect:
        sources_dir = os.path.join(research_folder(slug), "sources")
        if os.path.exists(sources_dir):
            import shutil
            shutil.rmtree(sources_dir)
            os.makedirs(sources_dir)

    await db_clear_stop_flag(research_id)
    await db_update_research_status(research_id, "running")

    src_instr = _source_instructions(sources_config)
    user_msg  = get_refresh_user_message(brief, src_instr, previous_report, aspect)
    messages  = [{"role": "user", "content": [{"text": user_msg}]}]
    await _run_loop(research_id, slug, brief, messages, is_refresh=True, aspect=aspect, template=template)
