from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Tuple

class Persistence(ABC):
    @abstractmethod
    def apply_schema(self, schema_sql_path: str) -> None: ...

    @abstractmethod
    def create_run(self, run_id: str, request: Dict[str, Any]) -> None: ...

    @abstractmethod
    def set_run_status(self, run_id: str, status: str, error: Optional[str] = None, finished: bool = False) -> None: ...

    @abstractmethod
    def add_event(self, run_id: str, ev_type: str, payload: Dict[str, Any]) -> int: ...

    @abstractmethod
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
    ) -> None: ...

    @abstractmethod
    def insert_point(self, run_id: str, method_id: str, step: int, t: float, error_b: float, error_a: float) -> None: ...

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def get_methods(self, run_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def fetch_events_since(self, run_id: str, since_id: int, limit: int = 200) -> List[Tuple[int, str, Dict[str, Any]]]: ...

    @abstractmethod
    def fetch_points_for_run(self, run_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def cleanup_old_runs(self, ttl_seconds: int) -> None: ...
