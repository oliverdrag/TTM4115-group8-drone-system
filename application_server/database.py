import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS drones (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    home_x INTEGER NOT NULL, home_y INTEGER NOT NULL,
    x INTEGER NOT NULL, y INTEGER NOT NULL,
    status TEXT NOT NULL, battery_state TEXT NOT NULL,
    medicine TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL, medicine TEXT NOT NULL,
    dest_x INTEGER NOT NULL, dest_y INTEGER NOT NULL,
    status TEXT NOT NULL, drone_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL, drone_id TEXT NOT NULL,
    route_out TEXT NOT NULL, route_home TEXT, status TEXT NOT NULL,
    created_at TEXT NOT NULL, completed_at TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (drone_id) REFERENCES drones(id)
);
CREATE TABLE IF NOT EXISTS grid_snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    width INTEGER NOT NULL, height INTEGER NOT NULL,
    zones_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def upsert_drone(self, drone: dict) -> None:
        self._exec(
            """INSERT INTO drones (id, name, home_x, home_y, x, y, status, battery_state, medicine)
               VALUES (:id, :name, :home_x, :home_y, :x, :y, :status, :battery_state, :medicine)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, home_x=excluded.home_x, home_y=excluded.home_y,
                 x=excluded.x, y=excluded.y, status=excluded.status,
                 battery_state=excluded.battery_state, medicine=excluded.medicine""",
            drone,
        )

    def list_drones(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM drones").fetchall()]

    def create_order(self, user_name: str, medicine: str, dest: tuple[int, int]) -> int:
        now = datetime.utcnow().isoformat()
        return int(self._exec(
            "INSERT INTO orders (user_name, medicine, dest_x, dest_y, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (user_name, medicine, dest[0], dest[1], now, now),
        ).lastrowid)

    def update_order(self, order_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE orders SET {cols} WHERE id=?", list(fields.values()) + [order_id])

    def get_order(self, order_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return dict(row) if row else None

    def list_active_orders(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM orders WHERE status NOT IN ('completed','cancelled','failed') ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_mission(self, order_id: int, drone_id: str, route_out: list[tuple[int, int]]) -> int:
        now = datetime.utcnow().isoformat()
        return int(self._exec(
            "INSERT INTO missions (order_id, drone_id, route_out, status, created_at) "
            "VALUES (?, ?, ?, 'dispatched', ?)",
            (order_id, drone_id, json.dumps(route_out), now),
        ).lastrowid)

    def update_mission(self, mission_id: int, **fields) -> None:
        if not fields:
            return
        if "route_home" in fields and isinstance(fields["route_home"], list):
            fields["route_home"] = json.dumps(fields["route_home"])
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE missions SET {cols} WHERE id=?", list(fields.values()) + [mission_id])

    def get_active_mission_for_drone(self, drone_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM missions WHERE drone_id=? AND status NOT IN ('completed','cancelled','failed') "
                "ORDER BY id DESC LIMIT 1",
                (drone_id,),
            ).fetchone()
        return dict(row) if row else None

    def save_grid_snapshot(self, width: int, height: int, zones_json: str) -> None:
        self._exec(
            """INSERT INTO grid_snapshot (id, width, height, zones_json, created_at)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 width=excluded.width, height=excluded.height,
                 zones_json=excluded.zones_json, created_at=excluded.created_at""",
            (width, height, zones_json, datetime.utcnow().isoformat()),
        )

    def load_grid_snapshot(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM grid_snapshot WHERE id=1").fetchone()
        return dict(row) if row else None
