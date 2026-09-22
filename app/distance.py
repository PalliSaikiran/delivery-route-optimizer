"""Distance/time matrices: Haversine with a road-detour factor, or real road data from OSRM."""
from __future__ import annotations

import json
import logging
import math
import urllib.request
from typing import List, Tuple

log = logging.getLogger("route-optimizer")
EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _haversine_matrices(coords, avg_speed_kmph, road_factor):
    n = len(coords)
    dist_m = [[0] * n for _ in range(n)]
    time_min = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            km = haversine_km(coords[i], coords[j]) * road_factor
            d = int(round(km * 1000))
            t = int(math.ceil(km / avg_speed_kmph * 60))
            dist_m[i][j] = dist_m[j][i] = d
            time_min[i][j] = time_min[j][i] = t
    return dist_m, time_min


def _osrm_matrices(coords, base_url):
    # OSRM expects lng,lat. The public demo server caps table requests at 100 coordinates.
    path = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coords)
    url = f"{base_url.rstrip('/')}/table/v1/driving/{path}?annotations=distance,duration"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.load(resp)
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')}")
    dist_m = [[int(round(x or 0)) for x in row] for row in data["distances"]]
    time_min = [[int(math.ceil((x or 0) / 60)) for x in row] for row in data["durations"]]
    return dist_m, time_min


def route_geometry(coords: List[Tuple[float, float]], base_url: str) -> List[Tuple[float, float]]:
    """Road-following path visiting coords in order (depot, stop, stop, ..., depot), via OSRM /route.
    Returns a list of (lat, lng) points, or [] if OSRM can't be reached or the route fails."""
    if len(coords) < 2:
        return []
    path = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coords)
    url = f"{base_url.rstrip('/')}/route/v1/driving/{path}?overview=full&geometries=geojson"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.load(resp)
        if data.get("code") != "Ok" or not data.get("routes"):
            return []
        # GeoJSON is [lng, lat]; flip to (lat, lng) for the map.
        return [(lat, lng) for lng, lat in data["routes"][0]["geometry"]["coordinates"]]
    except Exception as exc:  # network, quota, bad response: caller falls back to a straight line
        log.warning("OSRM route geometry unavailable (%s)", exc)
        return []


def build_matrices(
    coords: List[Tuple[float, float]],
    avg_speed_kmph: float,
    road_factor: float,
    osrm_url: str = "",
) -> Tuple[list, list, str]:
    """Return (distance in metres, travel time in whole minutes, source name)."""
    if osrm_url and len(coords) <= 100:
        try:
            dist_m, time_min = _osrm_matrices(coords, osrm_url)
            return dist_m, time_min, "osrm"
        except Exception as exc:  # network, quota, bad response: fall back rather than fail the request
            log.warning("OSRM unavailable (%s); falling back to Haversine", exc)
    dist_m, time_min = _haversine_matrices(coords, avg_speed_kmph, road_factor)
    return dist_m, time_min, "haversine"
