from typing import Any, Dict, Optional, List, Tuple

import psycopg
from psycopg_pool import ConnectionPool

from .base import Persistence

class PostgresPersistence(Persistence):
    def __init__(self, dsn: str):
        self.pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=10, open=True)

    def apply_schema(self, schema_sql_path: str) -> None:
        with open(schema_sql_path, "r", encoding="utf-8") as f:
            sql = f.read()
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def create_run(self, run_id: str, request: Dict[str, Any]) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO runs(run_id, status, request_json) VALUES (%s, %s, %s)",
                    (run_id, "queued", psycopg.types.json.Jsonb(request)),
                )
            conn.commit()

    def set_run_status(self, run_id: str, status: str, error: Optional[str] = None, finished: bool = False) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                if finished:
                    cur.execute(
                        "UPDATE runs SET status=%s, error=%s, finished_at=NOW() WHERE run_id=%s",
                        (status, error, run_id),
                    )
                else:
                    cur.execute(
                        "UPDATE runs SET status=%s, error=%s WHERE run_id=%s",
                        (status, error, run_id),
                    )
            conn.commit()

    def add_event(self, run_id: str, ev_type: str, payload: Dict[str, Any]) -> int:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events(run_id, type, payload_json)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (run_id, ev_type, psycopg.types.json.Jsonb(payload)),
                )
                ev_id = cur.fetchone()[0]
            conn.commit()
        return int(ev_id)

    def upsert_method(
        self,
        run_id: str,
        method_id: str,
        name: str,
        label: str,
        params: Dict[str, Any],
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
        runtime_sec: Optional[float] = None,
    ) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO methods(run_id, method_id, name, label, params_json, status, metrics_json, runtime_sec)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id, method_id) DO UPDATE SET
                      status=EXCLUDED.status,
                      metrics_json=EXCLUDED.metrics_json,
                      runtime_sec=EXCLUDED.runtime_sec
                    """,
                    (
                        run_id,
                        method_id,
                        name,
                        label,
                        psycopg.types.json.Jsonb(params or {}),
                        status,
                        (psycopg.types.json.Jsonb(metrics) if metrics is not None else None),
                        runtime_sec,
                    ),
                )
            conn.commit()

    def insert_point(self, run_id: str, method_id: str, step: int, t: float, error_b: float, error_a: float) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO points(run_id, method_id, step, t, error_b, error_a)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id, method_id, step) DO UPDATE SET
                      t=EXCLUDED.t, error_b=EXCLUDED.error_b, error_a=EXCLUDED.error_a
                    """,
                    (run_id, method_id, int(step), float(t), float(error_b), float(error_a)),
                )
            conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, status, created_at, finished_at, request_json, error FROM runs WHERE run_id=%s",
                    (run_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "run_id": row[0],
                    "status": row[1],
                    "created_at": row[2].timestamp() if row[2] else None,
                    "finished_at": row[3].timestamp() if row[3] else None,
                    "request": row[4],
                    "error": row[5],
                }

    def get_methods(self, run_id: str) -> Dict[str, Any]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT method_id, name, label, params_json, status, metrics_json, runtime_sec
                    FROM methods WHERE run_id=%s ORDER BY method_id
                    """,
                    (run_id,),
                )
                out: Dict[str, Any] = {}
                for r in cur.fetchall():
                    out[r[0]] = {
                        "method_id": r[0],
                        "name": r[1],
                        "label": r[2],
                        "params": r[3] or {},
                        "status": r[4],
                        "metrics": r[5],
                        "runtime_sec": r[6],
                    }
                return out

    def fetch_events_since(self, run_id: str, since_id: int, limit: int = 200) -> List[Tuple[int, str, Dict[str, Any]]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, type, payload_json
                    FROM events
                    WHERE run_id=%s AND id > %s
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (run_id, int(since_id), int(limit)),
                )
                rows = cur.fetchall()
                return [(int(r[0]), r[1], r[2]) for r in rows]

    def fetch_points_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id, method_id, step, t, error_b, error_a
                    FROM points
                    WHERE run_id=%s
                    ORDER BY method_id, step
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "run_id": r[0],
                        "method_id": r[1],
                        "step": r[2],
                        "t": float(r[3]),
                        "error_b": float(r[4]),
                        "error_a": float(r[5]),
                    }
                    for r in rows
                ]

    def cleanup_old_runs(self, ttl_seconds: int) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM runs
                    WHERE finished_at IS NOT NULL
                      AND finished_at < (NOW() - (%s * INTERVAL '1 second'))
                    """,
                    (int(ttl_seconds),),
                )
            conn.commit()
