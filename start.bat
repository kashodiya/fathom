@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
