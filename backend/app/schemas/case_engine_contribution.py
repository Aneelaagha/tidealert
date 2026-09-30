import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.case_engine_contribution import ContributionDirection, Engine


class CaseEngineContributionBase(BaseModel):
    case_id: uuid.UUID
    engine: Engine
    rule_fragment: str
    engine_confidence: float
    direction: ContributionDirection = ContributionDirection.supports
    observed_at: datetime
    independent_sources: int = 1


class CaseEngineContributionCreate(CaseEngineContributionBase):
    pass


class CaseEngineContributionUpdate(BaseModel):
    case_id: Optional[uuid.UUID] = None
    engine: Optional[Engine] = None
    rule_fragment: Optional[str] = None
    engine_confidence: Optional[float] = None
    direction: Optional[ContributionDirection] = None
    observed_at: Optional[datetime] = None
    independent_sources: Optional[int] = None


class CaseEngineContributionRead(CaseEngineContributionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
