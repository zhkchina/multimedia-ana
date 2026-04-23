from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.settings import Settings


STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
FINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELED}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_runtime_dirs(settings: Settings) -> None:
    for path in (
        settings.data_root,
        settings.service_root,
        settings.output_dir,
        settings.logs_dir,
        settings.runtime_dir,
        settings.cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    initialize_task_store(settings)


def _connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(settings.tasks_db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize_task_store(settings: Settings) -> None:
    with _connect(settings) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                request_id TEXT,
                result_json TEXT,
                error_json TEXT,
                worker_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_expires_at ON tasks(expires_at)")


def _json_loads_or_none(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    result = {
        "id": row["task_id"],
        "task_id": row["task_id"],
        "service": row["service"],
        "status": row["status"],
        "request": _json_loads_or_none(row["request_json"]) or {},
        "request_id": row["request_id"],
        "result": _json_loads_or_none(row["result_json"]),
        "error": _json_loads_or_none(row["error_json"]),
        "worker_id": row["worker_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
    }
    return result


def delete_expired_tasks(settings: Settings) -> None:
    with _connect(settings) as conn:
        conn.execute("DELETE FROM tasks WHERE expires_at IS NOT NULL AND expires_at < ?", (now_iso(),))


def create_task(
    settings: Settings,
    *,
    request_payload: dict[str, Any],
    request_id: str | None = None,
) -> dict[str, Any]:
    delete_expired_tasks(settings)
    task_id = f"task_{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    created_at = now_iso()
    expires_at = (datetime.now().astimezone() + timedelta(hours=settings.task_result_ttl_hours)).isoformat(timespec="seconds")
    with _connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, service, status, request_json, request_id,
                result_json, error_json, worker_id,
                created_at, started_at, finished_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?)
            """,
            (
                task_id,
                settings.service_name,
                STATUS_QUEUED,
                json.dumps(request_payload, ensure_ascii=False),
                request_id,
                created_at,
                created_at,
                expires_at,
            ),
        )
    return get_task(settings, task_id)


def get_task(settings: Settings, task_id: str) -> dict[str, Any]:
    with _connect(settings) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        raise FileNotFoundError(task_id)
    return _row_to_task(row)


def list_queued_tasks(settings: Settings) -> list[dict[str, Any]]:
    with _connect(settings) as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC", (STATUS_QUEUED,)).fetchall()
    return [_row_to_task(row) for row in rows]


def count_queued_tasks(settings: Settings) -> int:
    with _connect(settings) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM tasks WHERE status = ?", (STATUS_QUEUED,)).fetchone()
    return int(row["count"]) if row is not None else 0


def claim_next_queued_task(settings: Settings, worker_id: str) -> dict[str, Any] | None:
    conn = _connect(settings)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT task_id, request_json FROM tasks WHERE status = ? ORDER BY created_at ASC LIMIT 1",
            (STATUS_QUEUED,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        updated_at = now_iso()
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status = ?, worker_id = ?, started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE task_id = ? AND status = ?
            """,
            (STATUS_RUNNING, worker_id, updated_at, updated_at, row["task_id"], STATUS_QUEUED),
        )
        conn.commit()
        if cursor.rowcount != 1:
            return None
        request_payload = json.loads(row["request_json"])
        request_payload["task_id"] = row["task_id"]
        request_payload["id"] = row["task_id"]
        return request_payload
    finally:
        conn.close()


def store_task_result(
    settings: Settings,
    task_id: str,
    *,
    result: dict[str, Any],
    worker_id: str | None = None,
) -> dict[str, Any]:
    finished_at = now_iso()
    with _connect(settings) as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, result_json = ?, error_json = NULL, worker_id = COALESCE(?, worker_id),
                finished_at = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (
                STATUS_SUCCEEDED,
                json.dumps(result, ensure_ascii=False),
                worker_id,
                finished_at,
                finished_at,
                task_id,
            ),
        )
    return get_task(settings, task_id)


def store_task_error(
    settings: Settings,
    task_id: str,
    *,
    error: dict[str, Any],
    worker_id: str | None = None,
    status: str = STATUS_FAILED,
) -> dict[str, Any]:
    finished_at = now_iso()
    with _connect(settings) as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, error_json = ?, worker_id = COALESCE(?, worker_id),
                finished_at = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (
                status,
                json.dumps(error, ensure_ascii=False),
                worker_id,
                finished_at,
                finished_at,
                task_id,
            ),
        )
    return get_task(settings, task_id)


def wait_for_task(settings: Settings, task_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        task = get_task(settings, task_id)
        if task["status"] in FINAL_STATUSES:
            return task
        if time.monotonic() >= deadline:
            return task
        time.sleep(settings.task_wait_poll_interval_seconds)


def write_worker_state(settings: Settings, payload: dict[str, Any]) -> None:
    settings.worker_state_file.write_text(
        json.dumps({"updated_at": now_iso(), **payload}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_worker_state(settings: Settings) -> dict[str, Any] | None:
    if not settings.worker_state_file.exists():
        return None
    return json.loads(settings.worker_state_file.read_text(encoding="utf-8"))
