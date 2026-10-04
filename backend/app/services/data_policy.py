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
