"""Independent checks: every returned plan is re-validated against the raw constraints."""
import pytest
from fastapi.testclient import TestClient

from app.baseline import nearest_neighbour, one_trip_per_order
from app.data_gen import generate
from app.main import app
from app.model import build_problem
from app.schemas import SolveRequest, parse_minutes
from app.solver import solve_vrp

client = TestClient(app)


def hhmm(text):
    return parse_minutes(text)


def validate(req: SolveRequest, result: dict):
    """Fails if any route breaks capacity, a window, the shift or the max duration, or if an order
    is missing/duplicated."""
    types = {vt.name: vt for vt in req.vehicle_types}
    orders = {o.id: o for o in req.orders}
    seen = []
    used_per_type = {}
    for r in result["routes"]:
        vt = types[r["type"]]
        used_per_type[r["type"]] = used_per_type.get(r["type"], 0) + 1
        assert sum(orders[s["order_id"]].weight for s in r["stops"]) <= vt.max_weight + 1e-6
        assert sum(orders[s["order_id"]].volume for s in r["stops"]) <= vt.max_volume + 1e-6
        assert hhmm(r["depart"]) >= req.shift_start
        assert hhmm(r["return"]) <= req.shift_end
        assert r["duration_min"] <= req.max_route_min
        for s in r["stops"]:
            o = orders[s["order_id"]]
            assert s["late_min"] == 0
            assert o.tw_start <= hhmm(s["service_start"]) <= o.tw_end
            seen.append(s["order_id"])
    assert all(used_per_type[t] <= types[t].count for t in used_per_type)
    seen += [u["order_id"] for u in result["unassigned"]]
    assert sorted(seen) == sorted(orders), "every order must appear exactly once"


@pytest.mark.parametrize("n,seed", [(25, 1), (60, 5)])
def test_optimized_plan_is_valid_and_serves_everything(n, seed):
    req = SolveRequest(**generate(n, seed=seed))
    p = build_problem(req)
    result = solve_vrp(p, 4)
    validate(req, result)
    assert result["metrics"]["unassigned"] == 0
    assert result["metrics"]["on_time_pct"] == 100.0


def test_optimizer_beats_nearest_neighbour_on_cost():
    req = SolveRequest(**generate(60, seed=3))
    p = build_problem(req)
    opt, nn = solve_vrp(p, 5), nearest_neighbour(p)
    validate(req, nn)
    assert opt["metrics"]["cost"] < nn["metrics"]["cost"]
    assert opt["metrics"]["vehicles_used"] <= nn["metrics"]["vehicles_used"]


def test_unservable_orders_are_reported_with_reasons():
    data = generate(20, seed=2)
    data["orders"][0]["weight"] = 5000          # heavier than any vehicle
    data["orders"][1]["tw_start"] = "05:00"     # closes before the shift can reach it
    data["orders"][1]["tw_end"] = "05:30"
    req = SolveRequest(**data)
    result = solve_vrp(build_problem(req), 3)
    reasons = {u["order_id"]: u["reason"] for u in result["unassigned"]}
    assert "Heavier" in reasons[data["orders"][0]["id"]]
    assert "time window" in reasons[data["orders"][1]["id"]]
    validate(req, result)


def test_small_fleet_drops_orders_instead_of_failing():
    data = generate(40, seed=4)
    data["vehicle_types"] = [{"name": "Small van", "count": 1, "max_weight": 300, "max_volume": 2, "cost_per_km": 12, "fixed_cost": 0}]
    req = SolveRequest(**data)
    result = solve_vrp(build_problem(req), 3)
    assert result["metrics"]["unassigned"] > 0
    validate(req, result)


def test_one_trip_per_order_is_the_upper_bound():
    req = SolveRequest(**generate(30, seed=6))
    p = build_problem(req)
    assert one_trip_per_order(p)["metrics"]["vehicles_used"] == 30
    assert one_trip_per_order(p)["metrics"]["distance_km"] > solve_vrp(p, 3)["metrics"]["distance_km"]


def test_time_parsing():
    assert parse_minutes("10:15") == 615 and parse_minutes(615) == 615 and parse_minutes("615") == 615


def test_api_health_sample_and_solve():
    assert client.get("/health").json() == {"status": "ok"}
    sample = client.get("/api/sample", params={"n": 20, "city": "hyderabad", "seed": 9}).json()
    assert len(sample["orders"]) == 20
    sample["time_limit_s"] = 3
    body = client.post("/api/solve", json=sample).json()
    assert body["optimized"]["metrics"]["served"] == 20
    assert set(body) >= {"meta", "optimized", "nearest_neighbour", "one_trip_per_order", "savings_vs_nearest_neighbour_pct"}


def test_api_rejects_bad_input():
    sample = generate(10)
    sample["orders"][0]["tw_end"] = "05:00"   # ends before it starts
    assert client.post("/api/solve", json=sample).status_code == 422
    assert client.get("/api/sample", params={"city": "atlantis"}).status_code == 400
