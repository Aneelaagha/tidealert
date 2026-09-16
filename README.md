# TideAlert

Backend foundation for TideAlert: a FastAPI + PostGIS service for tracking
flood-affected households, zones, and relief needs. This is the base
scaffold only — models, schemas, basic CRUD routes, and a working database
connection. No algorithm logic (silence scoring, risk calculation, etc.) is
implemented yet; that will live in `backend/app/services/`

## Project layout

```
tidealert/
├── backend/
│   └── app/
│       ├── main.py            # FastAPI app entrypoint
│       ├── database.py        # SQLAlchemy engine/session for PostgreSQL + PostGIS
│       ├── models/            # SQLAlchemy 2.0 models (Household, Zone, ZoneNeed)
│       ├── schemas/           # Pydantic Create/Read/Update schemas
│       ├── routes/            # FastAPI routers (CRUD for households, zones)
│       ├── services/          # (empty) algorithm logic goes here later
│       └── data/              # (empty, gitignored) cached data pulls
├── frontend/                  # placeholder
├── notebooks/                 # placeholder for Jupyter validation work
├── docs/
│   ├── algorithms/             # placeholder, one doc per algorithm
│   └── data-sources/           # placeholder, data sources + access methods
├── scripts/                   # placeholder for one-off data scripts
├── alembic/                   # migrations
├── docker-compose.yml         # local PostGIS
└── requirements.txt
```

## Prerequisites

- Python 3.11+
- Docker (for local PostGIS)

## Setup

1. Copy the env file and adjust if needed:

   ```bash
   cp .env.example .env
   ```

2. Create a virtualenv and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   Note: `shapely` is included alongside the requested dependencies — it's
   what GeoAlchemy2 uses to convert between GeoJSON (used in the API) and
   PostGIS geometry columns.

3. Start PostgreSQL + PostGIS:

   ```bash
   docker compose up -d
   ```

4. Run migrations:

   ```bash
   alembic upgrade head
   ```

5. Run the API:

   ```bash
   uvicorn app.main:app --reload --app-dir backend
   ```

6. Check it's alive: http://localhost:8000/health, docs at
   http://localhost:8000/docs.

## Database

`DATABASE_URL` (see `.env.example`) points at the PostGIS container started
by `docker-compose.yml`. `backend/app/database.py` reads it via
`python-dotenv` and exposes a `get_db` FastAPI dependency backed by a
SQLAlchemy `sessionmaker`.

## Migrations

Alembic is configured in `alembic/env.py` to:

- import `backend/app` so model metadata is discoverable,
- read `DATABASE_URL` from the environment,
- use `geoalchemy2.alembic_helpers` (`include_object`, `render_item`,
  `writer`) so autogenerate handles PostGIS geometry columns and the spatial
  index GeoAlchemy2 creates alongside them correctly.

Generate a migration after changing models:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Geometry format

`Zone.boundary` is stored as a PostGIS `POLYGON` (SRID 4326). Over the API
it is accepted/returned as GeoJSON, e.g.:

```json
{
  "type": "Polygon",
  "coordinates": [[[lon, lat], [lon, lat], [lon, lat], [lon, lat]]]
}
```

## Status

Foundation only: models, Pydantic schemas, CRUD routes for households and
zones, Alembic migrations, and the docker-compose PostGIS setup. No
algorithm/service logic yet.
