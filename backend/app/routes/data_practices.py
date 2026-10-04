"""GET /data-practices: what the system does with data, computed from the code and the database."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import data_practices

router = APIRouter(tags=["data practices"])


@router.get("/data-practices")
def get_data_practices(request: Request, db: Session = Depends(get_db)):
    return data_practices.report(db, request.app.routes)
