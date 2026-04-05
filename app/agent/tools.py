TOOL_DEFINITIONS = [
    {
        "toolSpec": {
            "name": "search_google",
            "description": "Search Google for a query. Returns a list of URLs, titles and snippets.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }}
        }
    },
    {
        "toolSpec": {
            "name": "search_youtube",
            "description": "Search YouTube for a query. Returns a list of video URLs, titles and channels.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }}
        }
    },
    {
        "toolSpec": {
            "name": "get_video_metadata",
            "description": "Get metadata for a YouTube video (title, description, channel, views, upload date).",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }}
        }
    },
    {
        "toolSpec": {
            "name": "get_transcript",
            "description": "Get the full transcript of a YouTube video with timestamps.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }}
        }
    },
    {
        "toolSpec": {
            "name": "scrape_page",
            "description": "Scrape the full text content of any web page (articles, blogs, docs). Do NOT use for YouTube or Google URLs.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }}
        }
    },
    {
        "toolSpec": {
            "name": "write_report",
            "description": "Finalize and save the research report. Call this when you have gathered sufficient information. The content should be the complete Markdown report.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The full Markdown report"},
                    "commit_summary": {"type": "string", "description": "For refreshes only: a structured summary of what changed (new findings, removed stale sources, updated facts). Leave empty for initial research."}
                },
                "required": ["content"]
            }}
        }
    },
]
