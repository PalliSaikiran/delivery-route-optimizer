# Delivery Route Optimizer

A web app that plans a day of deliveries for a fleet. Give it a depot, a list of orders and your vehicles, and it returns routes that respect **vehicle capacity, customer time windows and driver shift limits**, then compares the plan with simpler dispatch methods on distance, cost, vehicles and on-time delivery.

The underlying problem is the Capacitated Vehicle Routing Problem with Time Windows (CVRPTW), solved with Google OR-Tools.

## Results

Synthetic orders around Bengaluru, seed 42. Reproduce with `python benchmark.py`. Search is time-limited, so optimized numbers can move by a percent or two between runs.

| Orders | Plan | Distance (km) | Cost (₹) | Vehicles | Weight used | On time |
|---|---|---|---|---|---|---|
| 50 | Optimized | 294 | 4,424 | 3 | 56% | 100% |
| 50 | Greedy dispatch | 478 | 9,396 | 7 | 19% | 100% |
| 50 | One trip per order | 1,204 | 29,450 | 50 | 3% | 100% |
| 100 | Optimized | 493 | 7,416 | 5 | 78% | 100% |
| 100 | Greedy dispatch | 689 | 14,982 | 11 | 25% | 100% |
| 100 | One trip per order | 2,651 | 61,809 | 100 | 4% | 100% |
| 200 | Optimized | 757 | 12,084 | 10 | 77% | 100% |
| 200 | Greedy dispatch | 1,231 | 26,048 | 19 | 30% | 100% |
| 200 | One trip per order | 5,130 | 121,555 | 200 | 3% | 100% |

Every order is delivered inside its window in all three plans, so the comparison is like for like. "Greedy dispatch" is a simple nearest-neighbour heuristic (see below), not a state-of-the-art competitor, so read the savings as "versus naive dispatch".

## What it models

| Constraint | How |
|---|---|
| Capacity | Weight (kg) and volume (m³) per vehicle, both enforced |
| Time windows | Service must start inside each order's window; vehicles wait if early |
| Shift | Vehicles leave and return between shift start and end |
| Max route duration | Cap on time from leaving the depot to returning |
| Mixed fleet | Several vehicle types, each with its own capacity, cost per km and fixed cost |
| Unservable orders | Reported with a reason (too big for any vehicle, window unreachable, fleet exhausted) instead of failing the whole plan |

**Optimizer.** OR-Tools routing model, parallel cheapest insertion for the first solution, then Guided Local Search until the time limit. The objective is total cost: distance times each vehicle's cost per km, plus a fixed cost per vehicle used. Dropping an order carries a penalty far above any route cost, so orders are only dropped when they can't be served.

**Schedules.** Every route is scheduled by a forward pass (earliest possible finish) followed by a backward pass (leave the depot as late as that finish allows). This gives the minimum-duration schedule, so drivers don't sit outside a customer waiting for a window to open. The same function schedules the optimized routes and both baselines.

**Baselines.**
- *Greedy dispatch:* fill the biggest vehicles first; from the current position always drive to the nearest order that still fits in the vehicle and can be delivered inside its window before the shift ends.
- *One trip per order:* each order goes out alone in the cheapest vehicle that fits. A worst case that shows what consolidation is worth.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

Generate sample data as a CSV, or run the tests:

```bash
python -m app.data_gen --n 100 --city bengaluru --out data/sample_orders.csv
pytest
```

The tests re-validate every returned plan against the raw constraints (capacity, windows, shift, duration, each order exactly once), so they check the solver's output rather than trusting it.

## Using your own data

Upload a CSV in the UI with these columns (aliases such as `id`, `latitude`, `longitude` also work):

```
order_id,lat,lng,weight,volume,time_window_start,time_window_end,service_time
ORD0001,12.987339,77.696528,18.2,0.125,14:30,16:30,14
```

Weight is in kg, volume in m³, times as HH:MM, service time in minutes. Set the depot, shift and fleet in the panel on the left.

## API

| Method and path | Purpose |
|---|---|
| `GET /health` | Health check |
| `GET /api/cities` | Cities available for sample data |
| `GET /api/sample?n=100&city=bengaluru&seed=42` | A complete sample request (depot, orders, fleet) |
| `POST /api/solve` | Plan routes. Body is the sample request shape; returns optimized routes, both baselines and savings |
| `GET /docs` | Interactive OpenAPI docs |

```bash
curl -s "localhost:8000/api/sample?n=40" | curl -s -X POST localhost:8000/api/solve \
  -H "Content-Type: application/json" -d @- | python -m json.tool | head -40
```

## Deploy

The repo includes a `Dockerfile` and a Render Blueprint (`render.yaml`), so a deploy is a push and a few clicks.

**1. Push to GitHub**

```bash
git init && git add . && git commit -m "Delivery route optimizer"
git branch -M main
git remote add origin https://github.com/<your-username>/route-optimizer.git
git push -u origin main
```

**2. Deploy on Render (free)**

1. Sign in at render.com and connect your GitHub account.
2. New, then Blueprint, and pick the repository. Render reads `render.yaml` and builds the Docker image.
3. Click Apply. When the build finishes you get a public `https://route-optimizer-xxxx.onrender.com` URL.
4. Open `/health` first (should return `{"status":"ok"}`), then the root URL for the app.

The free plan sleeps after about 15 minutes idle, so the first request afterwards takes up to a minute. Open the link yourself shortly before you share it with anyone. Free instances also have limited CPU, so the search gets fewer iterations in the same time limit; results stay valid but can be slightly less optimized than on a laptop.

**Other hosts.** Anything that runs a Dockerfile and provides `$PORT` works: Railway detects the Dockerfile automatically; on Fly.io run `fly launch` and set the internal port to 8000. The container binds to `$PORT` and defaults to 8000.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAX_TIME_LIMIT` | `30` | Upper bound on solver seconds per request |
| `MAX_CONCURRENT_SOLVES` | `2` | Simultaneous solves; extra requests get a 429 instead of overloading the host |
| `OSRM_URL` | `https://router.project-osrm.org` | OSRM server used for road distances, travel times, and the road-following lines drawn on the map, when "Distances" is set to "Real roads" (the default). This is OSRM's public demo server — fine for a portfolio project, not for production traffic. Falls back automatically to straight-line estimates (dashed on the map) if it's unreachable, rate-limited, or there are more than 100 points |

## Limits and honest caveats

- **Real roads by default, with a fallback.** The UI defaults to OSRM for both distances and the lines drawn on the map, so routes follow streets instead of cutting through buildings. If OSRM can't be reached (offline, rate-limited, more than 100 points), it falls back to straight-line distance times a detour factor (1.3) with a fixed average speed, and the map draws dashed straight lines between stops so it's clear they aren't road geometry.
- **Synthetic data.** Orders are generated, not real. The generator draws weights, volumes and windows from simple distributions.
- **Time-limited search.** Guided Local Search finds good, not provably optimal, plans. The gap to optimal is unknown.
- **Single depot, single trip per vehicle per day.** Multi-depot, multi-trip and pickup-and-delivery are not modelled.
- **Baselines are simple.** Beating nearest-neighbour is a low bar. A stronger comparison would be a sweep or savings-algorithm baseline.
- **No authentication or persistence.** Plans are computed per request and not stored.

## Project layout

```
app/
  main.py        FastAPI routes, concurrency guard, static UI
  schemas.py     Request validation (pydantic)
  distance.py    Haversine and OSRM distance/time matrices
  model.py       Problem expansion, route scheduling, metrics
  solver.py      OR-Tools CVRPTW model
  baseline.py    Greedy dispatch and one-trip-per-order baselines
  data_gen.py    Synthetic orders and default fleet (also a CLI)
  static/index.html   Map UI (Leaflet, no build step)
tests/           Solver, baseline and API tests
benchmark.py     Reproduces the results table
Dockerfile, render.yaml
```

## Ideas for next steps

- Real travel times by hour of day (a learned model feeding the time matrix)
- Re-optimization when an urgent order arrives mid-day
- Multiple trips per vehicle, and multiple depots
- Road geometry on the map from OSRM or a routing API
