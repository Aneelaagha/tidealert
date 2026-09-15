from fastapi import FastAPI

from app.routes import households, zones

app = FastAPI(title="TideAlert API")

app.include_router(households.router)
app.include_router(zones.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
