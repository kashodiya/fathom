import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "research", "db.sqlite")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS research (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                slug        TEXT    NOT NULL UNIQUE,
                brief       TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                sources_config TEXT NOT NULL DEFAULT 'both',
                parallelism INTEGER NOT NULL DEFAULT 1,
                seed_urls   TEXT    NOT NULL DEFAULT '[]',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                research_id INTEGER NOT NULL REFERENCES research(id),
                type        TEXT    NOT NULL,
                payload     TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                result      TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                research_id INTEGER NOT NULL REFERENCES research(id),
                type        TEXT    NOT NULL,
                url         TEXT    NOT NULL,
                title       TEXT,
                snippet     TEXT,
                file_path   TEXT,
                scraped_at  TEXT
            );
        """)
        await db.commit()

        # On startup, any research left in 'running' state lost its background task — reset it
        await db.execute("UPDATE research SET status = 'done' WHERE status = 'running'")
        await db.execute("UPDATE jobs SET status = 'failed' WHERE status IN ('pending', 'running') AND type = 'bedrock_call'")
        await db.commit()

        # Migrations — safe to run repeatedly (ALTER TABLE ignores if column exists via try/except)
        for migration in [
            "ALTER TABLE research ADD COLUMN refresh_aspect TEXT",
            "ALTER TABLE research ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE research RENAME COLUMN topic TO brief",
        ]:
            try:
                await db.execute(migration)
                await db.commit()
            except Exception:
                pass
