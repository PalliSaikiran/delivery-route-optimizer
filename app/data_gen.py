"""Synthetic delivery orders around a real city, so the demo needs no private data.

    python -m app.data_gen --n 100 --city bengaluru --out data/sample_orders.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from typing import Dict, List

from .schemas import fmt_time

CITIES: Dict[str, Dict] = {
    "bengaluru": {"center": (12.9716, 77.5946), "radius_km": 14},
    "hyderabad": {"center": (17.3850, 78.4867), "radius_km": 15},
    "delhi": {"center": (28.6139, 77.2090), "radius_km": 18},
    "mumbai": {"center": (19.0760, 72.8777), "radius_km": 14},
    "chennai": {"center": (13.0827, 80.2707), "radius_km": 12},
}

CSV_FIELDS = ["order_id", "lat", "lng", "weight", "volume", "time_window_start", "time_window_end", "service_time"]


def _offset(center, dx_km, dy_km):
    lat = center[0] + dy_km / 111.32
    lng = center[1] + dx_km / (111.32 * math.cos(math.radians(center[0])))
    return round(lat, 6), round(lng, 6)


def generate(n: int = 100, city: str = "bengaluru", seed: int = 42) -> Dict:
    """Return a complete solve request (depot, orders, fleet) as a plain dict."""
    if city not in CITIES:
        raise ValueError(f"unknown city '{city}', choose from {sorted(CITIES)}")
    rng = random.Random(seed)
    center, radius = CITIES[city]["center"], CITIES[city]["radius_km"]
    depot_lat, depot_lng = _offset(center, 3.0, 2.0)

    orders: List[Dict] = []
    for i in range(1, n + 1):
        r = radius * math.sqrt(rng.random())
        theta = rng.uniform(0, 2 * math.pi)
        lat, lng = _offset(center, r * math.cos(theta), r * math.sin(theta))
        weight = round(min(120.0, max(2.0, rng.lognormvariate(3.2, 0.6))), 1)
        volume = round(weight * 0.006 * rng.uniform(0.7, 1.3), 3)
        if rng.random() < 0.15:  # some customers accept anything during the working day
            start, end = 6 * 60, 18 * 60
        else:
            start = 6 * 60 + 30 * rng.randint(0, 20)
            end = min(start + rng.choice([120, 180, 240]), 19 * 60)
        orders.append(
            {
                "id": f"ORD{i:04d}",
                "lat": lat,
                "lng": lng,
                "weight": weight,
                "volume": volume,
                "tw_start": fmt_time(start),
                "tw_end": fmt_time(end),
                "service_min": rng.randint(5, 15),
            }
        )

    return {
        "depot": {"lat": depot_lat, "lng": depot_lng},
        "orders": orders,
        "vehicle_types": [
            {"name": "Small van", "count": max(4, math.ceil(n / 12)), "max_weight": 750, "max_volume": 4.0, "cost_per_km": 12, "fixed_cost": 300},
            {"name": "Medium truck", "count": max(2, math.ceil(n / 30)), "max_weight": 2000, "max_volume": 12.0, "cost_per_km": 22, "fixed_cost": 600},
        ],
        "shift_start": "06:00",
        "shift_end": "20:00",
        "max_route_min": 600,
        "avg_speed_kmph": 28,
        "road_factor": 1.3,
        "time_limit_s": 10,
        "use_osrm": False,
    }


def write_orders_csv(orders: List[Dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for o in orders:
            writer.writerow(
                {
                    "order_id": o["id"], "lat": o["lat"], "lng": o["lng"], "weight": o["weight"], "volume": o["volume"],
                    "time_window_start": o["tw_start"], "time_window_end": o["tw_end"], "service_time": o["service_min"],
                }
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate synthetic delivery orders")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--city", default="bengaluru", choices=sorted(CITIES))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/sample_orders.csv")
    args = ap.parse_args()
    data = generate(args.n, args.city, args.seed)
    write_orders_csv(data["orders"], args.out)
    print(f"wrote {len(data['orders'])} orders to {args.out}; depot at {data['depot']}")
