import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.household import Household
from app.schemas.household import HouseholdCreate, HouseholdRead, HouseholdUpdate

router = APIRouter(prefix="/households", tags=["households"])


@router.post("/", response_model=HouseholdRead, status_code=201)
def create_household(household_in: HouseholdCreate, db: Session = Depends(get_db)):
    household = Household(**household_in.model_dump())
    db.add(household)
    db.commit()
    db.refresh(household)
    return household


@router.get("/", response_model=List[HouseholdRead])
def list_households(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Household).offset(skip).limit(limit).all()


@router.get("/{household_id}", response_model=HouseholdRead)
def get_household(household_id: uuid.UUID, db: Session = Depends(get_db)):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return household


@router.patch("/{household_id}", response_model=HouseholdRead)
def update_household(
    household_id: uuid.UUID, household_in: HouseholdUpdate, db: Session = Depends(get_db)
):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")

    for field, value in household_in.model_dump(exclude_unset=True).items():
        setattr(household, field, value)

    db.commit()
    db.refresh(household)
    return household


@router.delete("/{household_id}", status_code=204)
def delete_household(household_id: uuid.UUID, db: Session = Depends(get_db)):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")

    db.delete(household)
    db.commit()
