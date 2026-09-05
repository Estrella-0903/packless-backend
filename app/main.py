from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import analyze, materials, redesign


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

if not FRONTEND_INDEX.is_file():
    raise RuntimeError(
        f"Frontend entry file not found: {FRONTEND_INDEX}. "
        "Ensure frontend/index.html is included in the deployment."
    )


app = FastAPI(
    title="PackLess AI Backend",
    version="0.1.0",
    description="Mock API MVP for packaging analysis and redesign.",
)

# Development only. Replace "*" with the deployed frontend origin(s) in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router)
app.include_router(redesign.router)
app.include_router(materials.router)

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


@app.get("/", include_in_schema=False)
async def serve_frontend() -> FileResponse:
    return FileResponse(FRONTEND_INDEX)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "healthy"}
