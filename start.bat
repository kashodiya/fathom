@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
uv run uvicorn app.main:app --host 0.0.0.0 --port 9092
