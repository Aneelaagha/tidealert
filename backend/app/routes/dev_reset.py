"""DEV ONLY: the demo conductor's Reset (frontend/src/dev/scene2.ts). This router is mounted by app.main only when the API was started
with TIDEALERT_DEV_RESET=1, so in any other run the route does not exist (it is not in the write-route inventory either, because that
inventory describes the running app). It deletes the needs entries made by "Demo Operator" and the pledges offered by "Test Donor" on
one run, and nothing else: see app.services.needs.reset_demo_rows."""
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.services import needs

router = APIRouter(tags=["dev"])


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# Read once, when the API starts: the commit the running server's code was loaded from. The Full Demo's pre-flight compares it with
# the commit now checked out, so a server started before a checkout or a commit is caught before the demo, not during it.
BUILD = {"sha": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain", "--untracked-files=no", "backend"))}


@router.get("/needs/dev-build")
def dev_build():
    return BUILD


class DemoReset(BaseModel):
    run_id: uuid.UUID


@router.post("/needs/dev-reset")
def dev_reset(body: DemoReset, db: Session = Depends(get_db)):
    run = db.get(Run, body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    out = needs.reset_demo_rows(db, run)
    db.commit()
    return out
