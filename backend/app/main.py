import os

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routes import copilot, data_practices, gauges, last_call, map, needs, relief, reports, tasks, validation, zones

app = FastAPI(title="TideAlert API")
# /map/zones is ~5 MB of GeoJSON for a Harvey run, ~650 kB gzipped.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(zones.router)
app.include_router(map.router)
app.include_router(tasks.router)
app.include_router(needs.router)
app.include_router(relief.router)
app.include_router(last_call.router)
app.include_router(reports.router)
app.include_router(validation.router)
app.include_router(gauges.router)
app.include_router(copilot.router)
app.include_router(data_practices.router)


# The page: the React app in frontend/, built to frontend/dist (`npm run build`), reading the API above.
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
else:
    @app.get("/ui/", include_in_schema=False, response_class=HTMLResponse)
    def ui_not_built():
        return ("<!doctype html><title>TideAlert</title><p>The page is not built yet. From <code>frontend/</code> run "
                "<code>npm install</code> then <code>npm run build</code>, and restart the API (or run "
                "<code>npm run dev</code> for the development server).</p>")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/health")
def health_check():
    return {"status": "ok"}
