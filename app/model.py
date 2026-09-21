"""Shared problem model: expands the request into arrays, simulates a route's schedule, summarises results.

Everything that reports a route (optimizer, baselines, tests) goes through simulate_route, so the
numbers are computed one way and can be compared fairly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from .distance import build_matrices
from .schemas import SolveRequest, fmt_time


@dataclass
class Vehicle:
    label: str
    type_name: str
    max_weight: float
    max_volume: float
    cost_per_km: float
    fixed_cost: float


@dataclass
class Problem:
    req: SolveRequest
    dist_m: List[List[int]]
    time_min: List[List[int]]
    distance_source: str
    # Node 0 is the depot; node i (1..n) is req.orders[i-1].
    w: List[float]
    v: List[float]
    tw_s: List[int]
    tw_e: List[int]
    svc: List[int]
    vehicles: List[Vehicle]

    @property
    def shift_start(self) -> int:
        return self.req.shift_start

    @property
    def shift_end(self) -> int:
        return self.req.shift_end

    @property
    def n_orders(self) -> int:
        return len(self.req.orders)

    def order(self, node: int):
        return self.req.orders[node - 1]


def build_problem(req: SolveRequest, osrm_url: str = "") -> Problem:
    coords = [(req.depot.lat, req.depot.lng)] + [(o.lat, o.lng) for o in req.orders]
    dist_m, time_min, source = build_matrices(
        coords, req.avg_speed_kmph, req.road_factor, osrm_url if req.use_osrm else ""
    )
    vehicles: List[Vehicle] = []
    for vt in req.vehicle_types:
        for k in range(1, vt.count + 1):
            vehicles.append(Vehicle(f"{vt.name} #{k}", vt.name, vt.max_weight, vt.max_volume, vt.cost_per_km, vt.fixed_cost))
    return Problem(
        req=req,
        dist_m=dist_m,
        time_min=time_min,
        distance_source=source,
        w=[0.0] + [o.weight for o in req.orders],
        v=[0.0] + [o.volume for o in req.orders],
        tw_s=[req.shift_start] + [o.tw_start for o in req.orders],
        tw_e=[req.shift_end] + [o.tw_end for o in req.orders],
        svc=[0] + [o.service_min for o in req.orders],
        vehicles=vehicles,
    )


def fits_some_vehicle(p: Problem, node: int) -> bool:
    return any(p.w[node] <= veh.max_weight and p.v[node] <= veh.max_volume for veh in p.vehicles)


def reachable_alone(p: Problem, node: int) -> bool:
    """Can one vehicle leave the depot, serve this order inside its window and get home within limits?"""
    depart = max(p.shift_start, p.tw_s[node] - p.time_min[0][node])
    start = max(depart + p.time_min[0][node], p.tw_s[node])
    back = start + p.svc[node] + p.time_min[node][0]
    return start <= p.tw_e[node] and back <= p.shift_end and (back - depart) <= p.req.max_route_min


def order_is_servable(p: Problem, node: int) -> bool:
    return fits_some_vehicle(p, node) and reachable_alone(p, node)


def unassigned_reason(p: Problem, node: int) -> str:
    if not fits_some_vehicle(p, node):
        return "Heavier or bulkier than the largest vehicle"
    if not reachable_alone(p, node):
        return "Its time window can't be met from the depot within the shift"
    return "The fleet has no capacity or time left for it"


def _forward(p: Problem, seq: Sequence[int], depart: int):
    """Earliest service-start time at each stop when leaving the depot at `depart`."""
    starts, t, prev = [], depart, 0
    for node in seq:
        start = max(t + p.time_min[prev][node], p.tw_s[node])
        starts.append(start)
        t = start + p.svc[node]
        prev = node
    return starts, t + p.time_min[prev][0]


def _latest_departure(p: Problem, seq: Sequence[int], finish_by: int) -> int:
    """Latest depot departure that still finishes by `finish_by` and meets every window (backward pass)."""
    latest = finish_by - p.time_min[seq[-1]][0] - p.svc[seq[-1]]
    latest = min(latest, p.tw_e[seq[-1]])
    for a, b in zip(reversed(seq[:-1]), reversed(seq[1:])):
        latest = min(p.tw_e[a], latest - p.time_min[a][b] - p.svc[a])
    return latest - p.time_min[0][seq[0]]


def simulate_route(p: Problem, vehicle: Vehicle, seq: Sequence[int], smart_start: bool = True) -> Dict:
    """Schedule a route for a visiting order.

    smart_start finds the minimum-duration schedule: a forward pass gives the earliest possible
    finish, then a backward pass leaves the depot as late as that finish allows, so drivers don't
    sit waiting for windows to open. Otherwise the vehicle leaves at shift start."""
    depart = p.shift_start
    if smart_start:
        _, finish = _forward(p, seq, p.shift_start)
        depart = max(p.shift_start, _latest_departure(p, seq, finish))
    t, prev = depart, 0
    dist_m = 0
    load_w = load_v = 0.0
    stops = []
    late_stops = 0
    wait_total = 0
    for node in seq:
        dist_m += p.dist_m[prev][node]
        arrival = t + p.time_min[prev][node]
        start = max(arrival, p.tw_s[node])
        wait = start - arrival
        late = max(0, start - p.tw_e[node])
        late_stops += 1 if late else 0
        wait_total += wait
        load_w += p.w[node]
        load_v += p.v[node]
        o = p.order(node)
        stops.append(
            {
                "order_id": o.id,
                "lat": o.lat,
                "lng": o.lng,
                "weight": o.weight,
                "volume": o.volume,
                "arrival": fmt_time(arrival),
                "service_start": fmt_time(start),
                "wait_min": wait,
                "late_min": late,
                "window": f"{fmt_time(o.tw_start)}-{fmt_time(o.tw_end)}",
                "service_min": o.service_min,
                "load_after_kg": round(load_w, 1),
            }
        )
        t = start + p.svc[node]
        prev = node
    dist_m += p.dist_m[prev][0]
    back = t + p.time_min[prev][0]
    km = dist_m / 1000
    return {
        "vehicle": vehicle.label,
        "type": vehicle.type_name,
        "depart": fmt_time(depart),
        "return": fmt_time(back),
        "duration_min": back - depart,
        "distance_km": round(km, 2),
        "load_weight": round(load_w, 1),
        "load_volume": round(load_v, 2),
        "max_weight": vehicle.max_weight,
        "max_volume": vehicle.max_volume,
        "util_weight": round(100 * load_w / vehicle.max_weight, 1),
        "util_volume": round(100 * load_v / vehicle.max_volume, 1),
        "cost": round(vehicle.fixed_cost + km * vehicle.cost_per_km, 2),
        "wait_min": wait_total,
        "late_stops": late_stops,
        "stops": stops,
    }


def make_unassigned(p: Problem, nodes: Sequence[int]) -> List[Dict]:
    out = []
    for node in nodes:
        o = p.order(node)
        out.append({"order_id": o.id, "lat": o.lat, "lng": o.lng, "weight": o.weight, "reason": unassigned_reason(p, node)})
    return out


def summarize(routes: List[Dict], unassigned: List[Dict], total_orders: int) -> Dict:
    served = sum(len(r["stops"]) for r in routes)
    late = sum(r["late_stops"] for r in routes)
    n = len(routes)
    return {
        "distance_km": round(sum(r["distance_km"] for r in routes), 1),
        "cost": round(sum(r["cost"] for r in routes), 0),
        "vehicles_used": n,
        "avg_util_weight": round(sum(r["util_weight"] for r in routes) / n, 1) if n else 0,
        "avg_util_volume": round(sum(r["util_volume"] for r in routes) / n, 1) if n else 0,
        "on_time_pct": round(100 * (served - late) / served, 1) if served else 100.0,
        "late_orders": late,
        "wait_min_total": sum(r["wait_min"] for r in routes),
        "served": served,
        "unassigned": len(unassigned),
        "total_orders": total_orders,
    }
