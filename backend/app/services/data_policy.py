"""What the API may return about people, and which routes may write. Enforced by tests/test_data_policy.py.

- PERSONAL_FIELDS: per-person fields the database stores that no route may return, in a response model or in an
  actual response. The map works at zone level; Case sentences and counts never carry these.
- WRITE_ROUTES: every route allowed to change data. A new write route fails the test until it is reviewed and
  added here. Zones in particular are written only by the engines (scripts), never through the API, so nothing
  outside an engine can mark a zone "safe".
"""

# Household fields (app.models.household) and the responder's phone (app.models.responder).
PERSONAL_FIELDS = frozenset({
    "contact_phone", "phone", "has_disability", "income_bracket", "age_bracket", "primary_language",
    "latitude", "longitude",
})

WRITE_ROUTES = frozenset({
    ("POST", "/tasks/{task_id}/assign"),
    ("POST", "/tasks/{task_id}/status"),
    ("POST", "/tasks/{task_id}/clear-verify"),
    ("POST", "/cases/{case_id}/tasks"),
    ("POST", "/copilot/ask"),  # reads only; POST because the question has a body
})

# How the policy is checked, stated wherever it is reported (tests/test_data_policy.py, GET /data-practices, the
# page's Data & ethics panel).
RESPONSE_SCAN = {
    "method": "name-based",
    "limitation": ("The API is checked for per-person fields by name: every route's response model, and real "
                   "responses from every read route. A person's details returned under a different key (for "
                   "example coordinates inside an unrelated geometry, or a phone number inside free text) would "
                   "not be caught."),
}


# ---------------------------------------------------------------- route inspection (shared with the policy test)
def flatten_routes(routes):
    """Every APIRoute, including those inside include_router()'s wrappers (FastAPI 0.14x keeps them wrapped)."""
    from fastapi.routing import APIRoute
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            assert not getattr(r.include_context, "prefix", ""), "an include_router prefix: join it to the paths"
            yield from flatten_routes(r.original_router.routes)


def model_fields(annotation, seen=None) -> set:
    """Every field name reachable from a model, through lists, optionals and nested models."""
    import typing
    from pydantic import BaseModel
    seen = seen if seen is not None else set()
    names: set = set()
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return names
        seen.add(annotation)
        for name, field in annotation.model_fields.items():
            names.add(name)
            names |= model_fields(field.annotation, seen)
        return names
    for arg in typing.get_args(annotation):
        names |= model_fields(arg, seen)
    return names


def is_secured(dependant) -> bool:
    """Does a route (or any dependency of it) require a FastAPI security scheme (a login, a token, a key)?"""
    from fastapi.security.base import SecurityBase
    return isinstance(dependant.call, SecurityBase) or any(is_secured(d) for d in dependant.dependencies)
