import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.case import CaseStatus, ConfidenceWord


class CaseBase(BaseModel):
    zone_id: uuid.UUID
    household_id: Optional[uuid.UUID] = None
    status: CaseStatus = CaseStatus.open
    inference_sentence: str
    source: Optional[str] = None
    confidence_word: ConfidenceWord
    task_id: Optional[uuid.UUID] = None
    outcome: Optional[str] = None
    validated: Optional[bool] = None
    escalated_at: Optional[datetime] = None


class CaseCreate(CaseBase):
    pass


class CaseUpdate(BaseModel):
    zone_id: Optional[uuid.UUID] = None
    household_id: Optional[uuid.UUID] = None
    status: Optional[CaseStatus] = None
    inference_sentence: Optional[str] = None
    source: Optional[str] = None
    confidence_word: Optional[ConfidenceWord] = None
    task_id: Optional[uuid.UUID] = None
    outcome: Optional[str] = None
    validated: Optional[bool] = None
    last_contribution_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None


class CaseRead(CaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    opened_at: datetime
    last_contribution_at: datetime
