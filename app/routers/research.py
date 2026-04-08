import os
import re
import git
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel
from app.db import get_db
from app.agent.loop import run_agent, run_agent_refresh

router = APIRouter(prefix="/research", tags=["research"])

RESEARCH_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "research")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60]


def init_research_repo(folder: str, brief: str):
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.join(folder, "sources"), exist_ok=True)
    repo = git.Repo.init(folder)
    gitignore = os.path.join(folder, ".gitignore")
    with open(gitignore, "w") as f:
        f.write("*.tmp\n")
    repo.index.add([".gitignore"])
    repo.index.commit(f"Init: {brief}")
    return repo


class ResearchCreate(BaseModel):
    brief: str
    sources_config: str = "both"   # "web", "youtube", "both"
    parallelism: int = 1
    seed_urls: list[str] = []
    template: str = ""


@router.post("")
async def create_research(body: ResearchCreate, background_tasks: BackgroundTasks, db=Depends(get_db)):
    slug = slugify(body.brief)
    folder = os.path.join(RESEARCH_DIR, slug)
    async with db.execute("SELECT id FROM research WHERE slug = ?", (slug,)) as cur:
        existing = await cur.fetchone()
    if existing:
        raise HTTPException(400, f"Research '{slug}' already exists")
    # Clean up stale folder left by a failed previous deletion
    if os.path.exists(folder):
        import shutil
        shutil.rmtree(folder)

    import json as _json
    async with db.execute(
        "INSERT INTO research (slug, brief, sources_config, parallelism, seed_urls, template) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (slug, body.brief, body.sources_config, body.parallelism, _json.dumps(body.seed_urls), body.template),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()
    research_id = row[0]

    init_research_repo(folder, body.brief)

    # Start agent in background
    background_tasks.add_task(run_agent, research_id, slug, body.brief, body.sources_config, body.template)

    return {"id": research_id, "slug": slug, "brief": body.brief, "status": "pending"}


@router.get("")
async def list_research(db=Depends(get_db)):
    async with db.execute(
        "SELECT id, slug, brief, status, sources_config, parallelism, created_at, updated_at FROM research ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/{slug}")
async def get_research(slug: str, db=Depends(get_db)):
    async with db.execute("SELECT * FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")

    research = dict(row)

    report_path = os.path.join(RESEARCH_DIR, slug, "report.md")
    research["report"] = open(report_path).read() if os.path.exists(report_path) else None

    return research


@router.get("/{slug}/sources")
async def get_sources(slug: str, db=Depends(get_db)):
    async with db.execute("SELECT id FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")
    async with db.execute(
        "SELECT id, type, url, title, snippet, file_path, scraped_at FROM sources WHERE research_id = ? ORDER BY id ASC",
        (row["id"],),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/{slug}/jobs")
async def get_research_jobs(slug: str, db=Depends(get_db)):
    async with db.execute("SELECT id FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")
    import json as _json
    async with db.execute(
        "SELECT id, type, payload, status, created_at, updated_at FROM jobs WHERE research_id = ? ORDER BY id ASC",
        (row["id"],),
    ) as cur:
        rows = await cur.fetchall()
    jobs = []
    for r in rows:
        j = dict(r)
        j["payload"] = _json.loads(j["payload"])
        jobs.append(j)
    return jobs


class RefreshRequest(BaseModel):
    aspect: str = ""   # empty = full refresh


@router.post("/{slug}/stop")
async def stop_research(slug: str, db=Depends(get_db)):
    async with db.execute("SELECT id, status FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")
    if row["status"] != "running":
        raise HTTPException(400, "Research is not running")
    await db.execute(
        "UPDATE research SET stop_requested = 1, updated_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    await db.commit()
    return {"slug": slug, "status": "stopping"}


@router.post("/{slug}/refresh")
async def refresh_research(slug: str, body: RefreshRequest, background_tasks: BackgroundTasks, db=Depends(get_db)):
    async with db.execute("SELECT id, brief, sources_config, status, template FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")
    if row["status"] == "running":
        raise HTTPException(400, "Research is already running")

    aspect = body.aspect.strip() or None
    await db.execute(
        "UPDATE research SET status = 'pending', refresh_aspect = ?, updated_at = datetime('now') WHERE slug = ?",
        (aspect, slug),
    )
    await db.commit()

    background_tasks.add_task(
        run_agent_refresh,
        row["id"], slug, row["brief"], row["sources_config"], aspect, row["template"] or "",
    )
    return {"slug": slug, "status": "pending", "aspect": aspect}


@router.get("/{slug}/history")
async def get_history(slug: str):
    folder = os.path.join(RESEARCH_DIR, slug)
    if not os.path.exists(folder):
        raise HTTPException(404, "Research not found")
    try:
        repo = git.Repo(folder)
        commits = []
        for c in repo.iter_commits():
            commits.append({
                "hash":    c.hexsha[:8],
                "message": c.message.strip(),
                "date":    c.committed_datetime.isoformat(),
            })
        return commits
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{slug}/history/{commit_hash}")
async def get_diff(slug: str, commit_hash: str):
    folder = os.path.join(RESEARCH_DIR, slug)
    if not os.path.exists(folder):
        raise HTTPException(404, "Research not found")
    try:
        repo  = git.Repo(folder)
        commit = repo.commit(commit_hash)
        if commit.parents:
            diff = repo.git.diff(commit.parents[0].hexsha, commit.hexsha)
        else:
            diff = repo.git.show(commit.hexsha, "--", "report.md", format="")
        return {"hash": commit_hash, "message": commit.message.strip(), "diff": diff}
    except Exception as e:
        raise HTTPException(500, str(e))


def _resolve_sources(content: str, src_map: dict) -> str:
    """Replace [src-N] tags with markdown links using a {id: {url, title}} map."""
    import re as _re
    def replace_inline(m):
        src = src_map.get(int(m.group(1)))
        if src:
            return f"[{m.group(1)}]({src['url']})"
        return m.group(0)
    content = _re.sub(r'\[src-(\d+)\]', replace_inline, content)
    # Make bare URLs in table cells clickable
    content = _re.sub(r'(\|\s*)(https?://[^\s|]+)(\s*\|)', lambda m: f"{m.group(1)}[{m.group(2)}]({m.group(2)}){m.group(3)}", content)
    return content


@router.get("/{slug}/export")
async def export_research(slug: str, format: str = "md", db=Depends(get_db)):
    report_path = os.path.join(RESEARCH_DIR, slug, "report.md")
    if not os.path.exists(report_path):
        raise HTTPException(404, "Report not found")

    content = open(report_path, encoding="utf-8").read()

    # Build source map for link resolution
    async with db.execute("SELECT id FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    src_map = {}
    if row:
        async with db.execute("SELECT id, url, title FROM sources WHERE research_id = ?", (row["id"],)) as cur:
            for s in await cur.fetchall():
                src_map[s["id"]] = {"url": s["url"], "title": s["title"] or s["url"]}

    if format == "md":
        return Response(
            _resolve_sources(content, src_map),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
        )

    if format == "txt":
        import re as _re
        txt = _re.sub(r'\[src-\d+\]', '', content)
        txt = _re.sub(r'#{1,6}\s+', '', txt)
        txt = _re.sub(r'\*\*(.+?)\*\*', r'\1', txt)
        txt = _re.sub(r'\*(.+?)\*', r'\1', txt)
        txt = _re.sub(r'\[(.+?)\]\(.+?\)', r'\1', txt)
        txt = _re.sub(r'`(.+?)`', r'\1', txt)
        txt = _re.sub(r'\|[-: ]+\|[-: ]+\|[-: ]+\|', '', txt)
        return Response(
            txt,
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{slug}.txt"'},
        )

    if format == "pdf":
        try:
            pdf_bytes = await _generate_pdf(_resolve_sources(content, src_map), slug)
            return Response(
                pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{slug}.pdf"'},
            )
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {e}")

    raise HTTPException(400, "format must be md, txt, or pdf")


def _generate_pdf_sync(report_md: str) -> bytes:
    import markdown as md_lib
    from playwright.sync_api import sync_playwright

    html_body = md_lib.markdown(report_md, extensions=["tables", "fenced_code"])
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body {{ font-family: Georgia, serif; max-width: 750px; margin: 40px auto; line-height: 1.7; color: #222; font-size: 14px; }}
  h1 {{ font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 2em; }}
  h3 {{ font-size: 1.1em; margin-top: 1.5em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; table-layout: fixed; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; word-break: break-word; overflow-wrap: break-word; }}
  th {{ background: #f5f5f5; }}
  td:first-child, th:first-child {{ width: 80px; text-align: center; }}
  code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
  a {{ color: #1565c0; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 1.5em 0; }}
</style></head><body>{html_body}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page    = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        pdf = page.pdf(format="A4", margin={"top": "40px", "bottom": "40px", "left": "40px", "right": "40px"})
        browser.close()
    return pdf


async def _generate_pdf(report_md: str, title: str) -> bytes:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_pdf_sync, report_md)


@router.delete("/{slug}")
async def delete_research(slug: str, db=Depends(get_db)):
    async with db.execute("SELECT id FROM research WHERE slug = ?", (slug,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Research not found")

    research_id = row["id"]
    await db.execute("DELETE FROM sources WHERE research_id = ?", (research_id,))
    await db.execute("DELETE FROM jobs WHERE research_id = ?", (research_id,))
    await db.execute("DELETE FROM research WHERE id = ?", (research_id,))
    await db.commit()

    import shutil, stat
    folder = os.path.join(RESEARCH_DIR, slug)
    if os.path.exists(folder):
        def _handle_readonly(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(folder, onerror=_handle_readonly)

    return {"deleted": slug}
