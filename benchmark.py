"""Reproduce the README results table: python benchmark.py"""
from app.baseline import nearest_neighbour, one_trip_per_order
from app.data_gen import generate
from app.model import build_problem
from app.schemas import SolveRequest
from app.solver import solve_vrp

print("| Orders | Plan | Distance (km) | Cost (₹) | Vehicles | Weight used | On time |")
print("|---|---|---|---|---|---|---|")
for n, seconds in [(50, 5), (100, 10), (200, 20)]:
    p = build_problem(SolveRequest(**generate(n, city="bengaluru", seed=42)))
    plans = [("Optimized", solve_vrp(p, seconds)), ("Greedy dispatch", nearest_neighbour(p)), ("One trip per order", one_trip_per_order(p))]
    for name, r in plans:
        m = r["metrics"]
        print(f"| {n} | {name} | {m['distance_km']:,.0f} | {m['cost']:,.0f} | {m['vehicles_used']} | {m['avg_util_weight']:.0f}% | {m['on_time_pct']:.0f}% |")
