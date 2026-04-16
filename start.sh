#!/bin/bash
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
uv run uvicorn app.main:app --reload --reload-exclude research --reload-exclude logs --host 0.0.0.0 --port 9092
