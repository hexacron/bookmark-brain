"""FastAPI app: chat UI + REST endpoints."""
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, config


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Bookmark Brain")

    static_dir = Path(__file__).parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"))

    class AskRequest(BaseModel):
        question: str
        include_archived: bool = False

    @app.post("/api/ask")
    def ask(req: AskRequest):
        from . import chat  # lazy: don't fail server startup if anthropic isn't installed
        if not req.question.strip():
            raise HTTPException(status_code=400, detail="empty question")
        with db.connect(db_path) as conn:
            result = chat.answer(conn, req.question, include_archived=req.include_archived)
        # Decode tags JSON for the client
        for c in result.get("citations", []):
            if c.get("tags"):
                try:
                    c["tags"] = json.loads(c["tags"])
                except (json.JSONDecodeError, TypeError):
                    c["tags"] = []
        return result

    class TouchRequest(BaseModel):
        bookmark_id: int

    @app.post("/api/touch")
    def touch(req: TouchRequest):
        with db.connect(db_path) as conn:
            db.touch(conn, req.bookmark_id)
        return {"ok": True}

    @app.get("/api/stats")
    def stats():
        with db.connect(db_path) as conn:
            return db.stats(conn)

    return app
