# TideAlert

Backend for TideAlert: a FastAPI + PostGIS service for tracking
flood-affected households, zones, and relief needs. It has models, schemas,
basic CRUD routes, and the first engine: the isolation engine, which works out
when street blocks lose every road route out during a flood, from a single
USGS gauge ID. See [docs/algorithms/isolation-engine.md](docs/algorithms/isolation-engine.md).

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
│       ├── services/          # engines and data services (isolation engine, ingest, terrain, ...)
│       └── data/              # (empty, gitignored) cached data pulls
├── frontend/                  # placeholder
├── notebooks/                 # placeholder for Jupyter validation work
├── docs/
│   ├── algorithms/             # one doc per algorithm (isolation-engine.md)
│   └── data-sources/           # placeholder, data sources + access methods
├── scripts/                   # pipelines and data pulls (run_isolation_pipeline.py, pull_nfip_claims.py)
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

## Isolation engine

```bash
.venv/bin/python scripts/run_isolation_pipeline.py 08074500
```

The USGS gauge ID is the only site input; the event window defaults to
Hurricane Harvey. Downloads are cached under `backend/app/data/usgs-<site>/`.
Method, current validated result and known limitations are in
[docs/algorithms/isolation-engine.md](docs/algorithms/isolation-engine.md).

## Status

Models, Pydantic schemas, CRUD routes for households and zones, Alembic
migrations, the docker-compose PostGIS setup (host port 5433), and the
isolation engine (river driver only; the rain driver is not yet validated),
which opens Cases for confirmed-isolated zones, and the silence engine's
per-household response baseline (statistics only, tested on synthetic data;
see [docs/algorithms/silence-engine.md](docs/algorithms/silence-engine.md)).
A case matcher sweeps both engines every 15 minutes (Harvey replay only for
now; [docs/algorithms/case-matcher.md](docs/algorithms/case-matcher.md)), and
`notebooks/nfip_validation.ipynb` checks the resulting Cases against NFIP
claims and FEMA's floodplain map.
