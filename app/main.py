# app/main.py
import threading
import time
import json
import io
import csv
from typing import Dict, Any, List, Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from uuid import uuid4
from inspect import signature, Parameter

from pyteda.analysis.registry import ANALYSIS_REGISTRY

from app.config import (
    DATABASE_URL,
    EVENT_TTL_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    EVENTS_FETCH_LIMIT,
    KEEPALIVE_SECONDS,
    POLL_INTERVAL_SECONDS,
)

from app.persistence.postgres import PostgresPersistence
from app.services.run_service import run_worker

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="TEDA Web Backend (Lorenz96 + Streaming + Postgres)")
app.mount("/static", StaticFiles(directory="static"), name="static")

p = PostgresPersistence(DATABASE_URL)

# -----------------------------------------------------------------------------
# Method metadata for UI (so frontend can show tuneable params)
# -----------------------------------------------------------------------------
LOCAL_METHODS_NEED_MODEL = {
    "letkf", "lenkf", "enkf-b-loc", "enkf-modified-cholesky", "enkf-shrinkage-precision"
}

METHOD_HELP: Dict[str, str] = {
    "enkf": (
        "Ensemble Kalman Filter (stochastic, full covariance update). "
        "Reference: Evensen (2009) — Data Assimilation: The Ensemble Kalman Filter."
    ),
    "enkf-naive": (
        "Naive/efficient EnKF implementation (stochastic) designed to reduce computational cost. "
        "Reference: Niño-Ruiz, Sandu & Anderson (2015) — iterative Sherman–Morrison formula."
    ),
    "enkf-cholesky": (
        "EnKF implementation using a Cholesky solve (ensemble space formulation). "
        "Reference: Mandel (2006) — Efficient implementation of the EnKF."
    ),
    "ensrf": (
        "Ensemble Square Root Filter (deterministic square-root update; avoids perturbed obs). "
        "Reference: Tippett et al. (2003) — Ensemble square root filters."
    ),
    "etkf": (
        "Ensemble Transform Kalman Filter (deterministic transform in ensemble space). "
        "Reference: Bishop, Etherton & Majumdar (2001) — Adaptive sampling with the ETKF."
    ),
    "letkf": (
        "Local ETKF (LETKF): ETKF performed locally with a localization radius r. "
        "Reference: Hunt, Kostelich & Szunyogh (2007) — local ensemble transform Kalman filter."
    ),
    "lenkf": (
        "Local EnKF (LEnKF): EnKF variant with spatial localization controlled by radius r. "
        "Reference: Ott et al. (2004) — A local ensemble Kalman filter for atmospheric DA."
    ),
    "enkf-b-loc": (
        "EnKF with B-localization: applies localization to background covariance (radius r). "
        "Reference: Greybush et al. (2011) — localization techniques."
    ),
    "enkf-modified-cholesky": (
        "EnKF using precision (inverse covariance) estimation via Modified Cholesky (radius r / neighborhood). "
        "Reference: Niño-Ruiz, Sandu & Deng (2018)."
    ),
    "enkf-shrinkage-precision": (
        "EnKF using shrinkage-based precision estimation (radius r / neighborhood). "
        "Reference: Niño-Ruiz & Sandu (2015)."
    ),
}

METHOD_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "letkf": {"r": 1},
    "lenkf": {"r": 1},
    "enkf-b-loc": {"r": 1},
    "enkf-modified-cholesky": {"r": 1},
    "enkf-shrinkage-precision": {"r": 1},
}

METHOD_SCHEMA: Dict[str, Dict[str, Dict[str, Any]]] = {
    "letkf": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "lenkf": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "enkf-b-loc": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "enkf-modified-cholesky": {"r": {"type": "int", "min": 1, "step": 1, "label": "Neighborhood size (r)"}},
    "enkf-shrinkage-precision": {"r": {"type": "int", "min": 1, "step": 1, "label": "Neighborhood size (r)"}},
}


def _infer_schema_from_signature(cls) -> Dict[str, Dict[str, Any]]:
    """
    Infer param schema from __init__ signature when possible.
    Excludes: self, model, *args/**kwargs. Only simple scalar defaults are handled.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        sig = signature(cls.__init__)
        for name, p_ in sig.parameters.items():
            if name in ("self", "model", "kwargs"):
                continue
            if p_.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue

            default = None if p_.default is Parameter.empty else p_.default

            if isinstance(default, bool):
                out[name] = {"type": "bool", "label": name}
            elif isinstance(default, int):
                out[name] = {"type": "int", "min": None, "step": 1, "label": name}
            elif isinstance(default, float):
                out[name] = {"type": "float", "min": None, "step": 0.01, "label": name}
            else:
                out[name] = {"type": "str", "label": name}
    except Exception:
        pass
    return out


def _infer_defaults_from_signature(cls) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        sig = signature(cls.__init__)
        for name, p_ in sig.parameters.items():
            if name in ("self", "model", "kwargs"):
                continue
            if p_.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue
            if p_.default is not Parameter.empty:
                out[name] = p_.default
    except Exception:
        pass
    return out


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class MethodSpec(BaseModel):
    """
    Represents a single method instance to run.
    `id` must be unique within the run.
    """
    id: str = Field(..., description="Unique id for this method instance")
    name: str = Field(..., description="Method name (must be registered in ANALYSIS_REGISTRY)")
    label: str = Field(..., description="Display label for UI/plots")
    params: Dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    model: Literal["lorenz96"] = "lorenz96"

    # core
    ensemble_size: int = 20

    # observation
    m: int = 32
    std_obs: float = 0.01

    # simulation
    obs_freq: float = 0.1
    end_time: float = 10.0
    inf_fact: float = 1.04

    # model params
    lorenz96_n: int = 40
    lorenz96_F: float = 8.0

    # methods to compare (instances)
    methods: List[MethodSpec] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Startup
# -----------------------------------------------------------------------------
@app.on_event("startup")
def startup():
    # Ensure DB schema exists
    p.apply_schema("app/persistence/schema.sql")

    # Periodic cleanup: removes runs older than TTL (cascades events/methods/points)
    def _cleanup_loop():
        while True:
            time.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                p.cleanup_old_runs(EVENT_TTL_SECONDS)
            except Exception:
                # avoid crashing cleanup thread
                pass

    threading.Thread(target=_cleanup_loop, daemon=True).start()


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/methods")
def list_methods():
    """
    Frontend depends on:
      - methods
      - defaults
      - schema
      - help
      - requires_model
    """
    methods = sorted(list(ANALYSIS_REGISTRY.keys()))

    defaults: Dict[str, Dict[str, Any]] = {}
    schema: Dict[str, Dict[str, Dict[str, Any]]] = {}
    helptext: Dict[str, str] = {}

    for m in methods:
        # defaults: manual first, then inferred
        d = dict(METHOD_DEFAULTS.get(m, {}))
        inferred_defaults = _infer_defaults_from_signature(ANALYSIS_REGISTRY[m])
        for k, v in inferred_defaults.items():
            if k not in d and k not in ("model",):
                d[k] = v
        defaults[m] = d

        # schema: manual first else infer
        if m in METHOD_SCHEMA:
            schema[m] = METHOD_SCHEMA[m]
        else:
            schema[m] = _infer_schema_from_signature(ANALYSIS_REGISTRY[m])

        helptext[m] = METHOD_HELP.get(m, "")

    return {
        "methods": methods,
        "requires_model": sorted(list(LOCAL_METHODS_NEED_MODEL)),
        "defaults": defaults,
        "schema": schema,
        "help": helptext,
    }


@app.post("/api/runs")
def create_run(req: RunRequest):
    if req.model != "lorenz96":
        return JSONResponse(status_code=400, content={"error": "For now, only lorenz96 is enabled."})

    # validate method instances
    seen = set()
    for ms in req.methods:
        if ms.id in seen:
            return JSONResponse(status_code=400, content={"error": f"Duplicate method instance id: {ms.id}"})
        seen.add(ms.id)

        if ms.name not in ANALYSIS_REGISTRY:
            return JSONResponse(status_code=400, content={"error": f"Unknown method: {ms.name}"})

    run_id = str(uuid4())
    req_dict = req.model_dump()

    # persist run
    p.create_run(run_id, req_dict)
    p.add_event(
        run_id,
        "run_created",
        {"type": "run_created", "run_id": run_id, "request": req_dict, "ts": time.time()},
    )

    # fire worker (thread inside THIS process)
    t = threading.Thread(target=run_worker, args=(p, run_id, req_dict), daemon=True)
    t.start()

    return {"run_id": run_id, "status": "queued"}


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, since: int = 0):
    """
    Server-Sent Events stream.
    - Client can reconnect with ?since=<last_event_id>
    - We always include payload["_event_id"] for client bookkeeping.
    """
    run = p.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "run not found"})

    def event_stream():
        yield "event: hello\ndata: {}\n\n"
        last_keepalive = time.time()
        last_id = int(since)

        while True:
            rows = p.fetch_events_since(run_id, last_id, limit=EVENTS_FETCH_LIMIT)

            if rows:
                for (eid, etype, payload) in rows:
                    last_id = int(eid)
                    payload["_event_id"] = last_id
                    yield f"event: {etype}\ndata: {json.dumps(payload)}\n\n"

                    if etype in ("run_completed", "run_failed"):
                        yield "event: done\ndata: {}\n\n"
                        return

            else:
                # keepalive ping
                if time.time() - last_keepalive > KEEPALIVE_SECONDS:
                    yield "event: keepalive\ndata: {}\n\n"
                    last_keepalive = time.time()

                # If run already finished but no more events, end.
                run2 = p.get_run(run_id)
                if run2 and run2.get("status") in ("completed", "failed"):
                    yield "event: done\ndata: {}\n\n"
                    return

                time.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/csv")
def download_run_csv(run_id: str):
    run = p.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "run not found"})

    rows = p.fetch_points_for_run(run_id)
    if not rows:
        return JSONResponse(status_code=400, content={"error": "no point data yet"})

    methods = p.get_methods(run_id)

    buf = io.StringIO()
    w = csv.writer(buf)

    # long format
    w.writerow(["run_id", "method_id", "name", "label", "step", "t", "error_b", "error_a"])

    for r in rows:
        mid = r["method_id"]
        md = methods.get(mid, {})
        w.writerow(
            [
                r["run_id"],
                mid,
                md.get("name", ""),
                md.get("label", ""),
                r["step"],
                r["t"],
                r["error_b"],
                r["error_a"],
            ]
        )

    content = buf.getvalue().encode("utf-8")
    filename = f"teda_run_{run_id[:8]}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = p.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "run not found"})
    run["methods"] = p.get_methods(run_id)
    return run
