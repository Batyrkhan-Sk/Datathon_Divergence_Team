"""ASGI entry point. Run from the repo root (so `ml` is importable):

    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""
from .api import create_app

app = create_app()
