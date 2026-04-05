import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_db
from app.scraper import scrape_page
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    research_id: int
    type: str
    payload: dict


class JobResult(BaseModel):
    result: dict
    status: str = "done"  # "done" or "failed"


@router.post("")
async def create_job(body: JobCreate, db=Depends(get_db)):
    async with db.execute(
        "INSERT INTO jobs (research_id, type, payload) VALUES (?, ?, ?) RETURNING id",
        (body.research_id, body.type, json.dumps(body.payload)),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()
    logger.info(f"job {row['id']} ({body.type}) created")
    return {"id": row["id"], "type": body.type, "status": "pending"}


@router.get("/next")
async def get_next_job(db=Depends(get_db)):
    """Extension polls this to get the next pending job (extension-handled types only)."""
    extension_types = ("test", "search_google", "search_youtube", "get_video_metadata", "get_transcript")
    async with db.execute(
        f"SELECT * FROM jobs WHERE status = 'pending' AND type IN ({','.join('?'*len(extension_types))}) ORDER BY created_at ASC LIMIT 1",
        extension_types,
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None

    await db.execute(
        "UPDATE jobs SET status = 'running', updated_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    await db.commit()
    logger.info(f"job {row['id']} ({row['type']}) → running")

    job = dict(row)
    job["payload"] = json.loads(job["payload"])
    return job


@router.post("/{job_id}/result")
async def post_job_result(job_id: int, body: JobResult, db=Depends(get_db)):
    """Extension posts result back after executing a job."""
    async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Job not found")

    await db.execute(
        "UPDATE jobs SET status = ?, result = ?, updated_at = datetime('now') WHERE id = ?",
        (body.status, json.dumps(body.result), job_id),
    )
    await db.commit()
    logger.info(f"job {job_id} ({row['type']}) → {body.status}")
    return {"id": job_id, "status": body.status}


@router.post("/scrape")
async def scrape_web_page(body: dict, db=Depends(get_db)):
    """Directly scrape a web page via crawl4ai (server-side, not extension)."""
    url = body.get("url")
    if not url:
        raise HTTPException(400, "url required")
    result = await scrape_page(url)
    return result


@router.get("")
async def list_jobs(research_id: int, db=Depends(get_db)):
    """Frontend polls this for live job status."""
    async with db.execute(
        "SELECT id, type, payload, status, result, created_at, updated_at FROM jobs WHERE research_id = ? ORDER BY created_at ASC",
        (research_id,),
    ) as cur:
        rows = await cur.fetchall()
    jobs = []
    for r in rows:
        j = dict(r)
        j["payload"] = json.loads(j["payload"])
        j["result"] = json.loads(j["result"]) if j["result"] else None
        jobs.append(j)
    return jobs
