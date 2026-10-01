from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.routes import households, map, zones

app = FastAPI(title="TideAlert API")
# /map/zones is ~5 MB of GeoJSON for a Harvey run, ~650 kB gzipped.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(households.router)
app.include_router(zones.router)
app.include_router(map.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
