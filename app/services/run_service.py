# app/services/run_service.py
import time
import math
from typing import Any, Dict, List

from pyteda.models import Lorenz96
from pyteda.background import Background
from pyteda.observation import Observation
from pyteda.simulation import Simulation
from pyteda.analysis.analysis_factory import AnalysisFactory
from pyteda.analysis.registry import ANALYSIS_REGISTRY

from app.persistence.base import Persistence
from app.config import EMIT_PARTIAL_EVERY_N_STEPS

# Methods that need the physical model injected into the Analysis constructor
LOCAL_METHODS_NEED_MODEL = {
    "letkf",
    "lenkf",
    "enkf-b-loc",
    "enkf-modified-cholesky",
    "enkf-shrinkage-precision",
}


def _series_stats(err: List[float]) -> Dict[str, float]:
    """Simple summary stats + true RMSE for a scalar error time series."""
    if not err:
        return {"final": float("nan"), "mean": float("nan"), "min": float("nan"), "rmse": float("nan")}
    n = len(err)
    mean = sum(err) / n
    rmse = math.sqrt(sum((e * e) for e in err) / n)
    return {"final": float(err[-1]), "mean": float(mean), "min": float(min(err)), "rmse": float(rmse)}


def run_worker(p: Persistence, run_id: str, req_dict: Dict[str, Any]) -> None:
    """
    Executes a run synchronously (called from a thread).
    Persists: runs, methods, events (SSE), and points (CSV).
    """
    try:
        p.set_run_status(run_id, "running")
        p.add_event(run_id, "run_started", {"type": "run_started", "run_id": run_id, "ts": time.time()})

        # -------------------------
        # Parse request
        # -------------------------
        ensemble_size = int(req_dict["ensemble_size"])
        m = int(req_dict["m"])
        std_obs = float(req_dict["std_obs"])
        obs_freq = float(req_dict["obs_freq"])
        end_time = float(req_dict["end_time"])
        inf_fact = float(req_dict["inf_fact"])
        n = int(req_dict["lorenz96_n"])
        F = float(req_dict["lorenz96_F"])
        methods = req_dict.get("methods", []) or []

        # -------------------------
        # Build model + observation
        # -------------------------
        model = Lorenz96(n=n, F=F)
        observation = Observation(m=m, std_obs=std_obs)

        # -------------------------
        # Run methods sequentially
        # -------------------------
        for ms in methods:
            method_name = ms["name"]
            method_id = ms["id"]
            label = ms.get("label", method_name)
            params = ms.get("params", {}) or {}

            if method_name not in ANALYSIS_REGISTRY:
                raise ValueError(f"Unknown method: {method_name}")

            p.upsert_method(run_id, method_id, method_name, label, params, status="running")
            p.add_event(
                run_id,
                "method_started",
                {
                    "type": "method_started",
                    "run_id": run_id,
                    "method_id": method_id,
                    "name": method_name,
                    "label": label,
                    "params": params,
                    "ts": time.time(),
                },
            )

            # -------------------------
            # Background / Analysis / Simulation
            # -------------------------
            background = Background(model=model, ensemble_size=ensemble_size)

            # CRITICAL FIX:
            # Some Background implementations lazily create internal ensemble (e.g., background.Xb)
            # only when get_initial_ensemble() is called. Without this, assimilation can fail.
            _ = background.get_initial_ensemble()

            analysis_kwargs = dict(params)
            if method_name in LOCAL_METHODS_NEED_MODEL:
                analysis_kwargs["model"] = model

            analysis = AnalysisFactory(method=method_name, **analysis_kwargs).create_analysis()

            sim = Simulation(
                model,
                background,
                analysis,
                observation,
                params={"obs_freq": obs_freq, "end_time": end_time, "inf_fact": inf_fact},
                log_level=None,
            )

            # -------------------------
            # Streaming loop
            # -------------------------
            t0 = time.time()
            error_a: List[float] = []
            error_b: List[float] = []

            xtk = model.get_initial_condition()
            T = [0.0, obs_freq]
            t = 0.0
            step = 0

            while t <= end_time + 1e-12:
                # generate observation at truth state
                observation.generate_observation(xtk)

                # assimilation step (updates background/analysis internals)
                Xak = analysis.perform_assimilation(background, observation)

                # optional inflation
                if inf_fact and inf_fact > 0:
                    analysis.inflate_ensemble(inf_fact)

                # states
                xak = analysis.get_analysis_state()
                xbk = background.get_background_state()

                # errors
                ea = float(sim.relative_error(xtk, xak))
                eb = float(sim.relative_error(xtk, xbk))

                error_a.append(ea)
                error_b.append(eb)

                # persist point for CSV
                p.insert_point(run_id, method_id, step, float(t), eb, ea)

                # stream partial event
                if EMIT_PARTIAL_EVERY_N_STEPS > 0 and (step % EMIT_PARTIAL_EVERY_N_STEPS == 0):
                    p.add_event(
                        run_id,
                        "partial",
                        {
                            "type": "partial",
                            "run_id": run_id,
                            "method_id": method_id,
                            "name": method_name,
                            "label": label,
                            "step": step,
                            "t": float(t),
                            "error_a": ea,
                            "error_b": eb,
                            "ts": time.time(),
                        },
                    )

                # forecast to next time
                _ = background.forecast_step(Xak, time=[0.0, obs_freq])
                xtk = model.propagate(xtk, T)

                # increment
                t = round(t + obs_freq, 10)
                step += 1

            runtime = time.time() - t0

            # -------------------------
            # Metrics + completion
            # -------------------------
            stats_a = _series_stats(error_a)
            stats_b = _series_stats(error_b)

            metrics = {
                "final": stats_a["final"],
                "mean": stats_a["mean"],
                "min": stats_a["min"],
                "rmse_a": stats_a["rmse"],
                "rmse_b": stats_b["rmse"],
                "background_final": stats_b["final"],
                "background_mean": stats_b["mean"],
                "background_min": stats_b["min"],
            }

            p.upsert_method(
                run_id,
                method_id,
                method_name,
                label,
                params,
                status="completed",
                metrics=metrics,
                runtime_sec=runtime,
            )
            p.add_event(
                run_id,
                "method_completed",
                {
                    "type": "method_completed",
                    "run_id": run_id,
                    "method_id": method_id,
                    "name": method_name,
                    "label": label,
                    "metrics": metrics,
                    "runtime_sec": runtime,
                    "ts": time.time(),
                },
            )

        # Run done
        p.set_run_status(run_id, "completed", finished=True)
        p.add_event(run_id, "run_completed", {"type": "run_completed", "run_id": run_id, "ts": time.time()})

    except Exception as e:
        # Mark failed and emit failure event
        p.set_run_status(run_id, "failed", error=str(e), finished=True)
        p.add_event(run_id, "run_failed", {"type": "run_failed", "run_id": run_id, "error": str(e), "ts": time.time()})
