# LEARN-DA — PyTEDA Web Backend (Lorenz-96 + Streaming + Postgres)

<p align="center">
  <img src="static/aml-cs.png" width="800"/>
</p>

A FastAPI backend + lightweight frontend for running **data assimilation benchmarks** on **Lorenz-96**, comparing multiple DA methods (EnKF / ETKF / LETKF / etc.), streaming progress in real time via **Server-Sent Events (SSE)**, and persisting runs/results in **PostgreSQL**.

---

## What’s in this repo

```

LEARN-DA/
app/
main.py                  # FastAPI app + routes
config.py                # env-based configuration
persistence/
postgres.py            # PostgresPersistence implementation
schema.sql             # DB schema
services/
run_service.py         # run_worker() for executing a run
templates/
index.html               # frontend entry (served at "/")
static/
css/app.css              # frontend styles
js/app.js                # frontend logic (calls API + SSE)
aml-cs.jpg               # optional image asset
Dockerfile
docker-compose.yml
requirements.txt
README.md

````

---

## Key features

- **Create benchmark runs** (Lorenz-96) with configurable parameters
- Compare multiple DA methods in one run (each one an “instance” with its own params)
- **Real-time progress streaming** via **SSE**:
  - run events, method progress, completion/failure
- **CSV export** of results (long format)
- **Auto-generated API spec** (OpenAPI):
  - Swagger UI, ReDoc, and JSON spec

---

## Requirements

- Python 3.10+ (recommended)
- PostgreSQL 13+ (or Docker)
- (Optional) Docker + docker compose

---

## Configuration

This app reads configuration from environment variables (see `app/config.py`).

Create a `.env` file in the project root (same level as `Dockerfile`) like:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/teda
EVENT_TTL_SECONDS=86400
CLEANUP_INTERVAL_SECONDS=60
EVENTS_FETCH_LIMIT=500
KEEPALIVE_SECONDS=10
POLL_INTERVAL_SECONDS=0.5
````

> `DATABASE_URL` is required.

---

## Run locally (Python)

### 1) Create and activate a virtualenv

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Start Postgres

If Postgres is not already running locally, use Docker:

```bash
docker run --name teda-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=teda \
  -p 5432:5432 \
  -d postgres:15
```

### 4) Run the API

From repo root:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

* Frontend: `http://localhost:8000/`
* Swagger UI: `http://localhost:8000/docs`
* OpenAPI JSON (the API spec): `http://localhost:8000/openapi.json`
* ReDoc: `http://localhost:8000/redoc`

---

## Run with Docker Compose

If `docker-compose.yml` is configured for the API + Postgres, run:

```bash
docker compose up --build
```

Then open:

* `http://localhost:8000/`
* `http://localhost:8000/docs`

> If the compose file exposes different ports, adjust accordingly.

---

## API Documentation (OpenAPI)

FastAPI generates the full API specification automatically:

* **Swagger UI**: `/docs`
* **OpenAPI JSON spec**: `/openapi.json`
* **ReDoc**: `/redoc`

If we ever want to “freeze” the spec into a file:

```bash
curl http://localhost:8000/openapi.json > openapi.json
```

---

## API Overview

### `GET /`

Serves the frontend (`templates/index.html`).

### `GET /api/methods`

Returns the list of methods registered in `ANALYSIS_REGISTRY` plus UI metadata:

* defaults
* parameter schema
* help text
* which methods require a model instance (local methods)

### `POST /api/runs`

Creates a new run and starts execution in a background thread.

**Example request**

```json
{
  "model": "lorenz96",
  "ensemble_size": 20,
  "m": 32,
  "std_obs": 0.01,
  "obs_freq": 0.1,
  "end_time": 10.0,
  "inf_fact": 1.04,
  "lorenz96_n": 40,
  "lorenz96_F": 8.0,
  "methods": [
    { "id": "m1", "name": "enkf", "label": "EnKF", "params": {} },
    { "id": "m2", "name": "letkf", "label": "LETKF (r=2)", "params": { "r": 2 } }
  ]
}
```

**Example response**

```json
{ "run_id": "....", "status": "queued" }
```

### `GET /api/runs/{run_id}/events?since=0`

Server-Sent Events stream for real-time updates.

* `since` is the last received event id (client can reconnect safely).
* Response is `text/event-stream`.

**Example (JS)**

```js
const es = new EventSource(`/api/runs/${runId}/events?since=0`);
es.addEventListener("run_created", (e) => console.log(JSON.parse(e.data)));
es.addEventListener("run_completed", () => es.close());
```

### `GET /api/runs/{run_id}/csv`

Downloads results as CSV (long format). Useful for plotting externally.

### `GET /api/runs/{run_id}`

Returns run metadata + methods used.

---

## Database notes

On startup, the API ensures the schema exists by applying:

* `app/persistence/schema.sql`

A cleanup thread periodically deletes old runs (TTL) along with related records.

---

## Development tips

### Hot reload

Use:

```bash
uvicorn app.main:app --reload
```

### Common issues

**1) “run not found”**

* The run_id is wrong or the DB was reset.
* Check that `DATABASE_URL` points to the same DB instance.

**2) SSE doesn’t update**

* Make sure the frontend is connecting to `/api/runs/{run_id}/events`.
* Some reverse proxies buffer SSE; if deploying behind Nginx, disable buffering for SSE endpoints.

**3) No CSV yet**

* `/api/runs/{run_id}/csv` returns an error if point data hasn’t been persisted yet.
* Wait for progress events or `run_completed`.

---

## License

See `LICENSE`.


