from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.api import app

dashboard = Path(__file__).resolve().parents[1] / "frontend" / "dist"
app.mount("/", StaticFiles(directory=dashboard, html=True), name="dashboard")
