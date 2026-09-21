"""FastAPI app: JSON API for the optimizer plus the static map UI."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .baseline import nearest_neighbour, one_trip_per_order
from .data_gen import CITIES, generate
from .model import build_problem
from .schemas import SolveRequest
from .solver import solve_vrp

MAX_TIME_LIMIT = int(os.getenv("MAX_TIME_LIMIT", "30"))  # seconds; protects small hosts
OSRM_URL = os.getenv("OSRM_URL", "")                      # e.g. https://router.project-osrm.org (demo use only)
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Delivery Route Optimizer", version="1.0.0")
_slots = threading.BoundedSemaphore(int(os.getenv("MAX_CONCURRENT_SOLVES", "2")))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/cities")
def cities():
    return sorted(CITIES)


@app.get("/api/sample")
def sample(n: int = Query(100, ge=5, le=300), city: str = "bengaluru", seed: int = 42):
    if city not in CITIES:
        raise HTTPException(400, f"unknown city '{city}'")
    return generate(n, city, seed)


@app.post("/api/solve")
def solve(req: SolveRequest):
    limit = min(req.time_limit_s, MAX_TIME_LIMIT)
    if not _slots.acquire(timeout=5):
        raise HTTPException(429, "The solver is busy with other requests. Try again in a few seconds.")
    try:
        problem = build_problem(req, OSRM_URL)
        optimized = solve_vrp(problem, limit)
        nn = nearest_neighbour(problem)
        per_order = one_trip_per_order(problem)
    finally:
        _slots.release()

    o, b = optimized["metrics"], nn["metrics"]

    def saving(key):
        return round(100 * (b[key] - o[key]) / b[key], 1) if b[key] else 0.0

    return {
        "meta": {
            "distance_source": problem.distance_source,
            "time_limit_s": limit,
            "orders": problem.n_orders,
            "vehicles_available": len(problem.vehicles),
            "depot": {"lat": req.depot.lat, "lng": req.depot.lng},
        },
        "optimized": optimized,
        "nearest_neighbour": nn,
        "one_trip_per_order": per_order,
        "savings_vs_nearest_neighbour_pct": {
            "distance_km": saving("distance_km"),
            "cost": saving("cost"),
            "vehicles_used": saving("vehicles_used"),
        },
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
