import asyncio
import logging
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

logger = logging.getLogger(__name__)


def _scrape_sync(url: str) -> dict:
    """Run crawl4ai in a fresh event loop (Windows: uvicorn's loop doesn't support subprocesses)."""
    async def _do():
        config = CrawlerRunConfig(
            word_count_threshold=10,
            exclude_external_links=False,
            remove_overlay_elements=True,
            wait_until="domcontentloaded",
            page_timeout=20000,  # 20s max per page
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
            if not result.success:
                return {"url": url, "error": result.error_message, "content": ""}
            return {
                "url": url,
                "title": result.metadata.get("title", "") if result.metadata else "",
                "content": result.markdown or "",
            }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_do())
    finally:
        loop.close()


async def scrape_page(url: str) -> dict:
    """Scrape a web page using crawl4ai, returns clean markdown content."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _scrape_sync, url)
    except Exception as e:
        logger.error(f"scrape_page failed for {url}: {e}")
        return {"url": url, "error": str(e), "content": ""}
