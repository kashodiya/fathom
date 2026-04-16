"""
LLM Configuration

Supports two modes:
1. AWS Bedrock (default)
2. Custom OpenAI-compatible API endpoint

Environment variables (configure in .env file):
- LLM_PROVIDER: "bedrock" (default) or "openai"
- LLM_BASE_URL: Base URL for OpenAI-compatible API (e.g., "https://api.anthropic.com/v1")
- LLM_API_KEY: API key for custom endpoint
- LLM_MODEL_ID: Model ID to use
- AWS_REGION: AWS region for Bedrock (default: "us-east-1")
"""

import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# LLM Provider configuration
LLM_PROVIDER: Literal["bedrock", "openai"] = os.getenv("LLM_PROVIDER", "bedrock")

# AWS Bedrock settings
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# OpenAI-compatible API settings
OPENAI_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.anthropic.com/v1")
OPENAI_API_KEY = os.getenv("LLM_API_KEY", "")
OPENAI_MODEL = os.getenv("LLM_MODEL_ID", "claude-sonnet-4-20250514")

# Agent settings
MAX_SEARCH_ROUNDS = 3
JOB_POLL_INTERVAL = 3   # seconds between DB polls
JOB_TIMEOUT = 180       # seconds before giving up on a job

def get_model_id() -> str:
    """Get the appropriate model ID based on provider."""
    if LLM_PROVIDER == "bedrock":
        return BEDROCK_MODEL
    return OPENAI_MODEL

def validate_config():
    """Validate that required config is present."""
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is 'openai' but LLM_API_KEY is not set. "
                "Please set LLM_API_KEY environment variable."
            )
    elif LLM_PROVIDER not in ("bedrock", "openai"):
        raise ValueError(
            f"Invalid LLM_PROVIDER: {LLM_PROVIDER}. "
            "Must be 'bedrock' or 'openai'."
        )
