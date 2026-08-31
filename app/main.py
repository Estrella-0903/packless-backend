from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analyze, materials, redesign


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


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "PackLess AI Backend"}


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "healthy"}
