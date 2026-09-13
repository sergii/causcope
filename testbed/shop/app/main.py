from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, StrictInt

DB_PATH = Path(os.environ.get("DB_PATH", "/data/shop.db"))
BUSY_TIMEOUT_MS = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "150"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger("causcope.shop")

app = FastAPI(title="Causcope Shop Testbed", version="0.1.0")


class OrderItemIn(BaseModel):
    product_id: StrictInt
    quantity: StrictInt


class CreateOrderIn(BaseModel):
    items: list[OrderItemIn]


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return connection


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              price_cents INTEGER NOT NULL CHECK(price_cents >= 0)
            );

            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              status TEXT NOT NULL,
              total_cents INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS order_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_id INTEGER NOT NULL REFERENCES orders(id),
              product_id INTEGER NOT NULL REFERENCES products(id),
              quantity INTEGER NOT NULL CHECK(quantity > 0),
              unit_price_cents INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_id INTEGER NOT NULL REFERENCES orders(id),
              status TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scenario_lock (
              id INTEGER PRIMARY KEY CHECK(id = 1),
              touched_at TEXT
            );
            """
        )
        connection.executemany(
            "INSERT OR IGNORE INTO products(id, name, price_cents) VALUES (?, ?, ?)",
            [
                (1, "Mechanical Keyboard", 12900),
                (2, "USB-C Cable", 1900),
                (3, "Laptop Stand", 5900),
            ],
        )
        connection.execute(
            "INSERT OR IGNORE INTO scenario_lock(id, touched_at) VALUES (1, CURRENT_TIMESTAMP)"
        )
        connection.commit()
    finally:
        connection.close()


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.middleware("http")
async def log_request(request: Request, call_next: Any) -> Response:
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    client_platform = request.headers.get("x-client-platform", "unknown")
    app_version = request.headers.get("x-app-version", "unknown")
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    finally:
        LOGGER.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "client_platform": client_platform,
                    "app_version": app_version,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                sort_keys=True,
            )
        )


def locked_error(exc: sqlite3.OperationalError) -> HTTPException:
    LOGGER.warning(
        json.dumps(
            {
                "event": "sqlite_operational_error",
                "error": str(exc),
                "db_path": str(DB_PATH),
            },
            sort_keys=True,
        )
    )
    return HTTPException(status_code=503, detail="database temporarily unavailable")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products")
def products() -> list[dict[str, Any]]:
    connection = connect()
    try:
        rows = connection.execute(
            "SELECT id, name, price_cents FROM products ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


@app.post("/orders", status_code=201)
def create_order(payload: CreateOrderIn) -> dict[str, Any]:
    if not payload.items:
        raise HTTPException(status_code=422, detail="order must contain at least one item")
    if any(item.quantity <= 0 for item in payload.items):
        raise HTTPException(status_code=422, detail="quantity must be positive")

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        total_cents = 0
        resolved: list[tuple[int, int, int]] = []
        for item in payload.items:
            product = connection.execute(
                "SELECT id, price_cents FROM products WHERE id = ?", (item.product_id,)
            ).fetchone()
            if product is None:
                raise HTTPException(status_code=404, detail=f"product {item.product_id} not found")
            unit_price = int(product["price_cents"])
            total_cents += unit_price * item.quantity
            resolved.append((item.product_id, item.quantity, unit_price))

        cursor = connection.execute(
            "INSERT INTO orders(status, total_cents) VALUES ('created', ?)",
            (total_cents,),
        )
        order_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO order_items(order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, ?, ?)",
            [(order_id, product_id, quantity, price) for product_id, quantity, price in resolved],
        )
        connection.commit()
        return {"id": order_id, "status": "created", "total_cents": total_cents}
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if "locked" in str(exc).lower():
            raise locked_error(exc) from exc
        raise
    finally:
        connection.close()


@app.get("/orders/{order_id}")
def get_order(order_id: int) -> dict[str, Any]:
    connection = connect()
    try:
        order = connection.execute(
            "SELECT id, status, total_cents, created_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        items = connection.execute(
            "SELECT product_id, quantity, unit_price_cents FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
        result = dict(order)
        result["items"] = [dict(item) for item in items]
        return result
    finally:
        connection.close()


@app.post("/orders/{order_id}/pay")
def pay_order(order_id: int) -> dict[str, Any]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute(
            "SELECT id, status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        if order["status"] == "paid":
            connection.rollback()
            return {"id": order_id, "status": "paid"}
        connection.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        connection.execute(
            "INSERT INTO payments(order_id, status) VALUES (?, 'captured')", (order_id,)
        )
        connection.commit()
        return {"id": order_id, "status": "paid"}
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if "locked" in str(exc).lower():
            raise locked_error(exc) from exc
        raise
    finally:
        connection.close()
