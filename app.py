from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Literal
from uuid import uuid4
import threading
import time
import json
import queue
import csv
import io
import math
from inspect import signature, Parameter

from pyteda.models import Lorenz96
from pyteda.background import Background
from pyteda.observation import Observation
from pyteda.simulation import Simulation
from pyteda.analysis.analysis_factory import AnalysisFactory
from pyteda.analysis.registry import ANALYSIS_REGISTRY

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="TEDA Web Backend (Lorenz96 + Streaming + CSV + Method Params)")
app.mount("/static", StaticFiles(directory="static"), name="static")

RUNS: Dict[str, Dict[str, Any]] = {}
RUN_QUEUES: Dict[str, "queue.Queue[dict]"] = {}

# Methods that need model injected
LOCAL_METHODS_NEED_MODEL = {
    "letkf", "lenkf", "enkf-b-loc", "enkf-modified-cholesky", "enkf-shrinkage-precision"
}

# Minimal help text (front can render it in Help section)
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
        "Local ETKF (LETKF): ETKF performed locally with a localization radius r; "
        "typically a strong baseline for larger systems. "
        "Reference: Hunt, Kostelich & Szunyogh (2007) — local ensemble transform Kalman filter."
    ),
    "lenkf": (
        "Local EnKF (LEnKF): EnKF variant with spatial localization controlled by radius r. "
        "Reference: Ott et al. (2004) — A local ensemble Kalman filter for atmospheric DA."
    ),
    "enkf-b-loc": (
        "EnKF with B-localization: applies a decorrelation/localization matrix to background covariance "
        "(radius r). Reference: Greybush et al. (2011) — localization techniques."
    ),
    "enkf-modified-cholesky": (
        "EnKF using precision (inverse covariance) estimation via Modified Cholesky decomposition "
        "(radius r / neighborhood size). "
        "Reference: Niño-Ruiz, Sandu & Deng (2018) — Modified Cholesky for inverse covariance estimation."
    ),
    "enkf-shrinkage-precision": (
        "EnKF using shrinkage-based precision estimation (blends a target precision with a pseudo-inverse "
        "background estimate; radius r / neighborhood size). "
        "Reference: Niño-Ruiz & Sandu (2015) — shrinkage covariance matrix estimation."
    ),
}

# Manual defaults for known params
METHOD_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "letkf": {"r": 1},
    "lenkf": {"r": 1},
    "enkf-b-loc": {"r": 1},
    "enkf-modified-cholesky": {"r": 1},
    "enkf-shrinkage-precision": {"r": 1},
}

# Manual schema (minimum viable) for UI autogen
METHOD_SCHEMA: Dict[str, Dict[str, Dict[str, Any]]] = {
    "letkf": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "lenkf": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "enkf-b-loc": {"r": {"type": "int", "min": 1, "step": 1, "label": "Localization radius (r)"}},
    "enkf-modified-cholesky": {"r": {"type": "int", "min": 1, "step": 1, "label": "Neighborhood size (r)"}},
    "enkf-shrinkage-precision": {"r": {"type": "int", "min": 1, "step": 1, "label": "Neighborhood size (r)"}},
    # If later you expose alpha/rtol/etc, add them here.
}

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class MethodSpec(BaseModel):
    """
    Represents a single method *instance* to run.
    method_id makes duplicates possible (e.g., letkf r=1 vs letkf r=2).
    """
    id: str = Field(..., description="Unique id for this method instance")
    name: str = Field(..., description="Method name (must be registered in ANALYSIS_REGISTRY)")
    label: str = Field(..., description="Display label for UI/plots (e.g., 'letkf • r=2')")
    params: Dict[str, Any] = Field(default_factory=dict, description="Method parameters (e.g., {'r':2})")

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
    methods: List[MethodSpec] = Field(
        default_factory=lambda: [
            MethodSpec(id="m1", name="letkf", label="letkf • r=1", params={"r": 1})
        ]
    )

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def qput(run_id: str, event: Dict[str, Any]) -> None:
    if run_id in RUN_QUEUES:
        RUN_QUEUES[run_id].put(event)

def _series_stats(err: List[float]) -> Dict[str, float]:
    """
    Compute simple stats + true RMSE over a time series of scalar errors.
    """
    if not err:
        return {"final": float("nan"), "mean": float("nan"), "min": float("nan"), "rmse": float("nan")}

    n = len(err)
    mean = sum(err) / n
    rmse = math.sqrt(sum((e * e) for e in err) / n)

    return {
        "final": float(err[-1]),
        "mean": float(mean),
        "min": float(min(err)),
        "rmse": float(rmse),
    }

def _infer_schema_from_signature(cls) -> Dict[str, Dict[str, Any]]:
    """
    Infer param schema from __init__ signature when possible.
    Excludes model/self/kwargs. Only simple scalars are handled.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        sig = signature(cls.__init__)
        for name, p in sig.parameters.items():
            if name in ("self", "model", "kwargs"):
                continue
            if p.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue

            default = None if p.default is Parameter.empty else p.default

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
        for name, p in sig.parameters.items():
            if name in ("self", "model", "kwargs"):
                continue
            if p.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
                continue
            if p.default is not Parameter.empty:
                out[name] = p.default
    except Exception:
        pass
    return out

# -----------------------------------------------------------------------------
# Worker: streaming per method instance (method_id)
# -----------------------------------------------------------------------------
def run_worker(run_id: str, req: RunRequest) -> None:
    try:
        RUNS[run_id]["status"] = "running"
        qput(run_id, {"type": "run_started", "run_id": run_id, "ts": time.time()})

        model = Lorenz96(n=req.lorenz96_n, F=req.lorenz96_F)
        observation = Observation(m=req.m, std_obs=req.std_obs)

        # Run each method instance sequentially (can parallelize later)
        for ms in req.methods:
            method_name = ms.name
            method_id = ms.id
            label = ms.label

            if method_name not in ANALYSIS_REGISTRY:
                raise ValueError(f"Unknown method: {method_name}")

            RUNS[run_id]["methods"][method_id] = {
                "method_id": method_id,
                "name": method_name,
                "label": label,
                "status": "running",
                "params": ms.params,
                "error_a": [],
                "error_b": [],
                "t": [],
                "metrics": None,
                "runtime_sec": None,
            }

            qput(run_id, {
                "type": "method_started",
                "run_id": run_id,
                "method_id": method_id,
                "name": method_name,
                "label": label,
                "params": ms.params,
                "ts": time.time()
            })

            background = Background(model=model, ensemble_size=req.ensemble_size)

            analysis_kwargs = dict(ms.params or {})
            if method_name in LOCAL_METHODS_NEED_MODEL:
                analysis_kwargs["model"] = model

            analysis = AnalysisFactory(method=method_name, **analysis_kwargs).create_analysis()

            params = {"obs_freq": req.obs_freq, "end_time": req.end_time, "inf_fact": req.inf_fact}
            sim = Simulation(model, background, analysis, observation, params=params, log_level=None)

            # Manual loop to stream partials
            t0 = time.time()
            error_a: List[float] = []
            error_b: List[float] = []
            times: List[float] = []

            xtk = model.get_initial_condition()
            Xbk = background.get_initial_ensemble()
            T = [0.0, req.obs_freq]
            t = 0.0

            while t <= req.end_time + 1e-12:
                observation.generate_observation(xtk)
                Xak = analysis.perform_assimilation(background, observation)

                if req.inf_fact and req.inf_fact > 0:
                    analysis.inflate_ensemble(req.inf_fact)

                xak = analysis.get_analysis_state()
                xbk = background.get_background_state()

                ea = float(sim.relative_error(xtk, xak))
                eb = float(sim.relative_error(xtk, xbk))

                error_a.append(ea)
                error_b.append(eb)
                times.append(float(t))

                # persist in RUNS
                md = RUNS[run_id]["methods"][method_id]
                md["error_a"].append(ea)
                md["error_b"].append(eb)
                md["t"].append(float(t))

                qput(run_id, {
                    "type": "partial",
                    "run_id": run_id,
                    "method_id": method_id,
                    "name": method_name,
                    "label": label,
                    "step": len(error_a) - 1,
                    "t": float(t),
                    "error_a": ea,
                    "error_b": eb,
                    "ts": time.time()
                })

                Xbk = background.forecast_step(Xak, time=[0.0, req.obs_freq])
                xtk = model.propagate(xtk, T)
                t = round(t + req.obs_freq, 10)

            runtime = time.time() - t0

            stats_a = _series_stats(error_a)
            stats_b = _series_stats(error_b)

            metrics = {
                # keep existing table fields for analysis (so UI doesn't break)
                "final": stats_a["final"],
                "mean": stats_a["mean"],
                "min": stats_a["min"],

                # NEW: true RMSEs for polar/radar
                "rmse_a": stats_a["rmse"],
                "rmse_b": stats_b["rmse"],

                # optional: background summary too
                "background_final": stats_b["final"],
                "background_mean": stats_b["mean"],
                "background_min": stats_b["min"],
            }

            RUNS[run_id]["methods"][method_id].update({
                "status": "completed",
                "metrics": metrics,
                "runtime_sec": runtime,
            })

            qput(run_id, {
                "type": "method_completed",
                "run_id": run_id,
                "method_id": method_id,
                "name": method_name,
                "label": label,
                "metrics": metrics,
                "runtime_sec": runtime,
                "ts": time.time()
            })

        RUNS[run_id]["status"] = "completed"
        qput(run_id, {"type": "run_completed", "run_id": run_id, "ts": time.time()})

    except Exception as e:
        RUNS[run_id]["status"] = "failed"
        RUNS[run_id]["error"] = str(e)
        qput(run_id, {"type": "run_failed", "run_id": run_id, "error": str(e), "ts": time.time()})


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/methods")
def list_methods():
    methods = sorted(list(ANALYSIS_REGISTRY.keys()))

    defaults: Dict[str, Dict[str, Any]] = {}
    schema: Dict[str, Dict[str, Dict[str, Any]]] = {}
    helptext: Dict[str, str] = {}

    for m in methods:
        # defaults: manual first
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
    seen_ids = set()
    for ms in req.methods:
        if ms.id in seen_ids:
            return JSONResponse(status_code=400, content={"error": f"Duplicate method instance id: {ms.id}"})
        seen_ids.add(ms.id)

        if ms.name not in ANALYSIS_REGISTRY:
            return JSONResponse(status_code=400, content={"error": f"Unknown method: {ms.name}"})

    run_id = str(uuid4())
    RUN_QUEUES[run_id] = queue.Queue()
    RUNS[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "created_at": time.time(),
        "request": req.model_dump(),
        "methods": {},     # keyed by method_id
        "error": None
    }

    qput(run_id, {
        "type": "run_created",
        "run_id": run_id,
        "request": RUNS[run_id]["request"],
        "ts": time.time()
    })

    t = threading.Thread(target=run_worker, args=(run_id, req), daemon=True)
    t.start()

    return {"run_id": run_id, "status": "queued"}

@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str):
    if run_id not in RUN_QUEUES:
        return JSONResponse(status_code=404, content={"error": "run not found"})

    def event_stream():
        yield "event: hello\ndata: {}\n\n"
        last_keepalive = time.time()

        while True:
            try:
                ev = RUN_QUEUES[run_id].get(timeout=0.8)
                yield f"event: {ev.get('type','message')}\ndata: {json.dumps(ev)}\n\n"

                if ev.get("type") in ("run_completed", "run_failed"):
                    break

            except queue.Empty:
                if time.time() - last_keepalive > 10:
                    yield "event: keepalive\ndata: {}\n\n"
                    last_keepalive = time.time()

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/api/runs/{run_id}/csv")
def download_run_csv(run_id: str):
    if run_id not in RUNS:
        return JSONResponse(status_code=404, content={"error": "run not found"})

    run = RUNS[run_id]
    methods = run.get("methods", {})
    if not methods:
        return JSONResponse(status_code=400, content={"error": "no method data yet"})

    buf = io.StringIO()
    w = csv.writer(buf)

    # long format, includes method instance id + label
    w.writerow(["run_id", "method_id", "name", "label", "step", "t", "error_b", "error_a"])

    for method_id, md in methods.items():
        eb = md.get("error_b", [])
        ea = md.get("error_a", [])
        tt = md.get("t", [])
        n = min(len(eb), len(ea), len(tt))

        for i in range(n):
            w.writerow([
                run_id,
                method_id,
                md.get("name", ""),
                md.get("label", ""),
                i,
                tt[i],
                eb[i],
                ea[i],
            ])

    content = buf.getvalue().encode("utf-8")
    filename = f"teda_run_{run_id[:8]}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in RUNS:
        return JSONResponse(status_code=404, content={"error": "run not found"})
    return RUNS[run_id]
