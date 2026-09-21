"""Capacitated VRP with time windows, multiple vehicle types and optional dropped orders (OR-Tools)."""
from __future__ import annotations

import math
import time
from typing import Dict, List

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .model import Problem, make_unassigned, order_is_servable, simulate_route, summarize

W_SCALE = 10      # weight kg -> 0.1 kg integer units
V_SCALE = 100     # volume m3 -> 0.01 m3 integer units
COST_SCALE = 100  # currency -> hundredths, so arc costs stay integers
DROP_PENALTY = 10_000_000 * 1  # far above any real route cost: serving an order always beats dropping it


def solve_vrp(p: Problem, time_limit_s: int) -> Dict:
    started = time.perf_counter()
    n_nodes = p.n_orders + 1
    n_veh = len(p.vehicles)

    manager = pywrapcp.RoutingIndexManager(n_nodes, n_veh, 0)
    routing = pywrapcp.RoutingModel(manager)

    # --- Cost: distance x per-km rate of that vehicle type, plus a fixed cost for using a vehicle.
    callbacks: Dict[float, int] = {}
    for v, veh in enumerate(p.vehicles):
        rate = max(veh.cost_per_km, 0.1)  # keep some distance pressure even if the rate is 0
        if rate not in callbacks:
            def arc_cost(from_index, to_index, rate=rate):
                i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
                return int(p.dist_m[i][j] / 1000 * rate * COST_SCALE)
            callbacks[rate] = routing.RegisterTransitCallback(arc_cost)
        routing.SetArcCostEvaluatorOfVehicle(callbacks[rate], v)
        routing.SetFixedCostOfVehicle(int(veh.fixed_cost * COST_SCALE), v)

    # --- Capacity: weight and volume, per vehicle.
    demand_w = [int(math.ceil(x * W_SCALE)) for x in p.w]
    demand_v = [int(math.ceil(x * V_SCALE)) for x in p.v]
    w_cb = routing.RegisterUnaryTransitCallback(lambda idx: demand_w[manager.IndexToNode(idx)])
    v_cb = routing.RegisterUnaryTransitCallback(lambda idx: demand_v[manager.IndexToNode(idx)])
    routing.AddDimensionWithVehicleCapacity(w_cb, 0, [int(veh.max_weight * W_SCALE) for veh in p.vehicles], True, "Weight")
    routing.AddDimensionWithVehicleCapacity(v_cb, 0, [int(veh.max_volume * V_SCALE) for veh in p.vehicles], True, "Volume")

    # --- Time: travel + service time, delivery windows, shift limits, max route duration.
    def time_cb(from_index, to_index):
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return p.time_min[i][j] + p.svc[i]

    t_idx = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(t_idx, 240, p.shift_end, False, "Time")  # up to 4h of waiting between stops
    time_dim = routing.GetDimensionOrDie("Time")

    servable = {node: order_is_servable(p, node) for node in range(1, n_nodes)}
    for node in range(1, n_nodes):
        idx = manager.NodeToIndex(node)
        lo, hi = max(p.tw_s[node], p.shift_start), min(p.tw_e[node], p.shift_end)
        if servable[node] and lo <= hi:
            time_dim.CumulVar(idx).SetRange(lo, hi)
        routing.AddDisjunction([idx], DROP_PENALTY)  # allows dropping an order instead of failing outright
        if not servable[node]:
            routing.solver().Add(routing.ActiveVar(idx) == 0)

    for v in range(n_veh):
        time_dim.CumulVar(routing.Start(v)).SetRange(p.shift_start, p.shift_end)
        time_dim.CumulVar(routing.End(v)).SetRange(p.shift_start, p.shift_end)
        time_dim.SetSpanUpperBoundForVehicle(p.req.max_route_min, v)
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(int(time_limit_s))

    solution = routing.SolveWithParameters(params)
    elapsed = round(time.perf_counter() - started, 2)

    routes: List[Dict] = []
    visited = set()
    if solution is not None:
        for v, veh in enumerate(p.vehicles):
            index = solution.Value(routing.NextVar(routing.Start(v)))
            seq = []
            while not routing.IsEnd(index):
                seq.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
            if seq:
                visited.update(seq)
                routes.append(simulate_route(p, veh, seq, smart_start=True))

    dropped = [n for n in range(1, n_nodes) if n not in visited]
    unassigned = make_unassigned(p, dropped)
    return {
        "routes": routes,
        "unassigned": unassigned,
        "metrics": {**summarize(routes, unassigned, p.n_orders), "solve_time_s": elapsed},
        "status": "solved" if solution is not None else "no_solution",
    }
