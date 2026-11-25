"""The isolated MKH V3 preview."""

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parent / "web"


async def home(request):
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


async def health(request):
    return JSONResponse({
        "status": "ok",
        "environment": "v3-preview",
        "commit": os.getenv("RENDER_GIT_COMMIT", "local"),
        "chat_ready": False,
        "public_web_research": False,
    })


async def sources(request):
    return JSONResponse({"sources": []})


app = Starlette(routes=[
    Route("/", home),
    Route("/api/health", health),
    Route("/api/sources", sources),
    Mount("/assets", app=StaticFiles(directory=WEB)),
])
