"""Baselines to compare against: a planner's nearest-neighbour dispatch, and one trip per order."""
from __future__ import annotations

from typing import Dict, List

from .model import Problem, Vehicle, make_unassigned, order_is_servable, simulate_route, summarize


def nearest_neighbour(p: Problem) -> Dict:
    """Greedy dispatch: fill the biggest vehicles first, always driving to the closest order that
    still fits in the vehicle and can be delivered inside its window before the shift ends.
    Orders that no vehicle in the fleet gets to are left unassigned."""
    remaining = {n for n in range(1, p.n_orders + 1) if order_is_servable(p, n)}
    vehicles = sorted(p.vehicles, key=lambda x: (-x.max_weight, x.cost_per_km))
    routes: List[Dict] = []

    for veh in vehicles:
        if not remaining:
            break
        load_w = load_v = 0.0
        depart = t = pos = 0
        seq: List[int] = []
        while True:
            chosen = chosen_start = chosen_depart = None
            for node in sorted(remaining, key=lambda n: p.dist_m[pos][n]):
                if load_w + p.w[node] > veh.max_weight or load_v + p.v[node] > veh.max_volume:
                    continue
                cand_depart = depart if seq else max(p.shift_start, p.tw_s[node] - p.time_min[0][node])
                base_t = t if seq else cand_depart
                start = max(base_t + p.time_min[pos][node], p.tw_s[node])
                back = start + p.svc[node] + p.time_min[node][0]
                if start <= p.tw_e[node] and back <= p.shift_end and back - cand_depart <= p.req.max_route_min:
                    chosen, chosen_start, chosen_depart = node, start, cand_depart
                    break
            if chosen is None:
                break
            depart = chosen_depart
            t = chosen_start + p.svc[chosen]
            load_w += p.w[chosen]
            load_v += p.v[chosen]
            seq.append(chosen)
            remaining.discard(chosen)
            pos = chosen
        if seq:
            routes.append(simulate_route(p, veh, seq, smart_start=True))

    unassigned_nodes = sorted(
        remaining | {n for n in range(1, p.n_orders + 1) if not order_is_servable(p, n)}
    )
    unassigned = make_unassigned(p, unassigned_nodes)
    return {"routes": routes, "unassigned": unassigned, "metrics": summarize(routes, unassigned, p.n_orders)}


def one_trip_per_order(p: Problem) -> Dict:
    """Worst case: every order goes out on its own round trip in the cheapest vehicle that fits."""
    routes: List[Dict] = []
    skipped: List[int] = []
    types: Dict[str, Vehicle] = {}
    for veh in p.vehicles:
        types.setdefault(veh.type_name, veh)
    for node in range(1, p.n_orders + 1):
        if not order_is_servable(p, node):
            skipped.append(node)
            continue
        best = None
        for veh in types.values():
            if p.w[node] <= veh.max_weight and p.v[node] <= veh.max_volume:
                route = simulate_route(p, veh, [node], smart_start=True)
                if best is None or route["cost"] < best["cost"]:
                    best = route
        routes.append(best)
    unassigned = make_unassigned(p, skipped)
    return {"unassigned": unassigned, "metrics": summarize(routes, unassigned, p.n_orders)}
