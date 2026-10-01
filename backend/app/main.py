import os

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routes import copilot, households, map, tasks, zones

app = FastAPI(title="TideAlert API")
# /map/zones is ~5 MB of GeoJSON for a Harvey run, ~650 kB gzipped.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(households.router)
app.include_router(zones.router)
app.include_router(map.router)
app.include_router(tasks.router)
app.include_router(copilot.router)


# The map page (frontend/index.html + map.js): static files that read the API above.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/health")
def health_check():
    return {"status": "ok"}
