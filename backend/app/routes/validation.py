"""The validation results shown in the product. See app.services.validation."""
from fastapi import APIRouter

from app.services import validation

router = APIRouter(tags=["validation"])


@router.get("/validation/harvey")
def harvey_validation():
    """The Harvey backtest's validation results, each read from its stored source and shown with its run, event window,
    file and (for the NFIP results) execution time, plus the limits of what they show."""
    return validation.harvey_backtest()
