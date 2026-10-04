"""Copilot API: questions about a run as of a time, answered from the database (app.services.copilot)."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import copilot, copilot_tools, map_state

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Ask(BaseModel):
    run_id: uuid.UUID
    question: str = ""
    intent: Optional[str] = None  # one of copilot.INTENTS; routed from the question if omitted
    at: Optional[datetime] = None  # the map's slider time; default: end of the run's window (now if live)
    zone_id: Optional[uuid.UUID] = None  # the selected zone
    case_id: Optional[uuid.UUID] = None  # the selected Case


@router.get("/status")
def status():
    return {**copilot.model_status(), "intents": copilot.INTENTS}


@router.post("/ask")
def ask(body: Ask, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None  # the direct peer: no proxy headers are trusted
    try:
        return copilot.ask(db, body.run_id, body.question, body.intent, body.at, body.zone_id, body.case_id, ip)
    except copilot_tools.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (copilot.CopilotInputError, map_state.TimeOutOfWindow) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
