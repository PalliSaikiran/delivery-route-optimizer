"""Request models. Times are minutes after midnight internally; "HH:MM" strings are accepted."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator


def parse_minutes(value) -> int:
    """Accept 615, "615" or "10:15" and return minutes after midnight."""
    if isinstance(value, bool):
        raise ValueError("time must be a number of minutes or an HH:MM string")
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            hours, minutes = text.split(":")[:2]
            return int(hours) * 60 + int(minutes)
        return int(float(text))
    raise ValueError("time must be a number of minutes or an HH:MM string")


def fmt_time(minutes: float) -> str:
    total = int(round(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


class Depot(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Order(BaseModel):
    id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    weight: float = Field(ge=0, description="kg")
    volume: float = Field(default=0, ge=0, description="cubic metres")
    tw_start: int = Field(description="earliest delivery, minutes after midnight or HH:MM")
    tw_end: int = Field(description="latest delivery start, minutes after midnight or HH:MM")
    service_min: int = Field(default=10, ge=0, le=240)

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return str(v)

    @field_validator("tw_start", "tw_end", mode="before")
    @classmethod
    def _times(cls, v):
        return parse_minutes(v)

    @model_validator(mode="after")
    def _window_order(self):
        if self.tw_end < self.tw_start:
            raise ValueError(f"order {self.id}: time window ends before it starts")
        return self


class VehicleType(BaseModel):
    name: str
    count: int = Field(ge=1, le=200)
    max_weight: float = Field(gt=0, description="kg")
    max_volume: float = Field(gt=0, description="cubic metres")
    cost_per_km: float = Field(ge=0)
    fixed_cost: float = Field(default=0, ge=0, description="cost of using the vehicle at all")


class SolveRequest(BaseModel):
    depot: Depot
    orders: List[Order] = Field(min_length=1, max_length=300)
    vehicle_types: List[VehicleType] = Field(min_length=1, max_length=10)
    shift_start: int = 6 * 60
    shift_end: int = 20 * 60
    max_route_min: int = Field(default=600, ge=30, le=1440)
    avg_speed_kmph: float = Field(default=28, gt=5, le=120)
    road_factor: float = Field(default=1.3, ge=1.0, le=3.0)
    time_limit_s: int = Field(default=10, ge=1, le=120)
    use_osrm: bool = False

    @field_validator("shift_start", "shift_end", mode="before")
    @classmethod
    def _times(cls, v):
        return parse_minutes(v)

    @model_validator(mode="after")
    def _checks(self):
        if self.shift_end <= self.shift_start:
            raise ValueError("shift_end must be after shift_start")
        ids = [o.id for o in self.orders]
        if len(set(ids)) != len(ids):
            raise ValueError("order ids must be unique")
        return self
