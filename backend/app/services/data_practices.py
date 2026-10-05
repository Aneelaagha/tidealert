"""What the system does with data, stated from the code and the database rather than written by hand.

GET /data-practices reports it and the page's Data & ethics panel shows it. Every flag is computed: consent from
the households table's columns, authentication from the routes' dependencies, exposed fields from the routes'
response models. Each known gap names its source, and tests/test_data_practices.py pins each one to it, so a
gap line can't outlive (or be missing for) the condition it describes.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Household, Responder
from app.services import copilot, copilot_model, map_state
from app.services.data_policy import PERSONAL_FIELDS, RESPONSE_SCAN, WRITE_ROUTES, flatten_routes, is_secured, model_fields

TILE_HOST = "tile.openstreetmap.org"  # the basemap the page loads (frontend/src/components/ZoneMap.tsx)
EXTERNAL_MODEL_RULE = ("A copilot tool result that touches any real household is never sent to an external model: "
                       "that question is answered from a fixed template instead.")


def consent_collected() -> bool:
    """True only if the households table can record consent. It can't: there is no intake flow behind one."""
    return any("consent" in c.name for c in Household.__table__.columns)


def authentication(routes) -> bool:
    return any(is_secured(r.dependant) for r in routes)


def exposed_personal_fields(routes) -> list[str]:
    declared = set().union(*(model_fields(r.response_model) for r in routes))
    return sorted(declared & PERSONAL_FIELDS)


def _counts(db: Session, model) -> dict:
    synthetic = model.is_synthetic if model is Household else model.run_id.is_not(None)
    total = db.scalar(select(func.count()).select_from(model))
    fake = db.scalar(select(func.count()).select_from(model).where(synthetic))
    return {"total": total, "real": total - fake, "synthetic": fake}


def known_gaps(routes) -> list[dict]:
    """Each gap with its source. `when` is the live condition that makes it a gap; only true ones are listed."""
    from app.services.isolation_engine import RAIN_DRIVER_VALIDATED  # imported here: it pulls in the terrain stack
    gaps = [
        {"id": "consent", "when": not consent_collected(), "source": "flag: consent_collected (households table columns)",
         "text": "Consent is not collected. There is no intake flow, so the system holds no consent records; nothing "
                 "here implies one exists."},
        {"id": "authentication", "when": not authentication(routes), "source": "flag: authentication (route dependencies)",
         "text": "There is no login. Anyone who can reach the API can read it, take the task actions and enter "
                 "needs on the needs board; the operator name on an action or entry is free text."},
        {"id": "free_text_notes", "when": True, "source": "code: backend/app/services/needs.py (MAX_NOTE) and backend/app/routes/tasks.py",
         "text": "Notes on a task action or an entered need are free text. The personal-data scan checks field "
                 "names, so a person's details typed into a note would not be caught; the page says not to."},
        {"id": "tiles", "when": True, "source": f"code: frontend/src/components/ZoneMap.tsx loads {TILE_HOST}",
         "text": f"Map tiles come from OpenStreetMap's public server ({TILE_HOST}), so it learns which area is "
                 "being viewed."},
        {"id": "retention", "when": True, "source": "code: no retention or deletion process exists in backend/ or scripts/",
         "text": "There is no data retention or deletion policy."},
        {"id": "case_status_history", "when": True, "source": "doc: docs/api/map.md (Case status has no history)",
         "text": "Case status has no history: a Case shows its current status even when the slider is set earlier."},
        {"id": "confidence", "when": True, "source": "code: app.services.map_state.CONFIDENCE_CAVEAT",
         "text": map_state.CONFIDENCE_CAVEAT},
        {"id": "rain_driver", "when": not RAIN_DRIVER_VALIDATED,
         "source": "flag: app.services.isolation_engine.RAIN_DRIVER_VALIDATED",
         "text": "Flooding from rain alone is not modelled: the rain driver could not be validated and is switched "
                 "off, so only river flooding opens isolation Cases."},
        {"id": "response_scan", "when": True, "source": "code: app.services.data_policy.RESPONSE_SCAN",
         "text": RESPONSE_SCAN["limitation"]},
    ]
    return [{k: g[k] for k in ("id", "text", "source")} for g in gaps if g["when"]]


def report(db: Session, app_routes) -> dict:
    routes = list(flatten_routes(app_routes))
    status = copilot.model_status()
    return {
        "households": _counts(db, Household),
        "responders": _counts(db, Responder),
        "household_fields_stored": [c.name for c in Household.__table__.columns],
        "personal_fields": sorted(PERSONAL_FIELDS),
        "personal_fields_exposed": exposed_personal_fields(routes),
        "write_routes": [f"{m} {p}" for m, p in sorted(WRITE_ROUTES)],
        "consent_collected": consent_collected(),
        "authentication": authentication(routes),
        "response_scan": RESPONSE_SCAN,
        "copilot": {"mode": status["mode"], "reason": status["reason"], "model": copilot_model.MODEL,
                    "external_model_rule": EXTERNAL_MODEL_RULE},
        "known_gaps": known_gaps(routes),
    }
