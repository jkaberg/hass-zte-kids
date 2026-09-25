"""Daily activity totals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SportSummary:
    """Today's totals for one watch.

    ``api/sport/query/daily`` returns one row per hour plus running totals, so
    the summary is taken from the last row that carries them.
    """

    day: str | None = None
    steps: int | None = None
    distance_m: float | None = None
    calories: float | None = None
    goal: int | None = None

    @classmethod
    def from_rows(cls, rows: list[Mapping[str, Any]]) -> SportSummary:
        if not rows:
            return cls()

        latest: Mapping[str, Any] | None = None
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if row.get("totalStep") is not None or row.get("step") is not None:
                latest = row
        if latest is None:
            return cls()

        return cls(
            day=latest.get("day"),
            steps=_coerce_int(_first(latest, "totalStep", "step")),
            distance_m=_coerce_float(_first(latest, "totalDistance", "distance")),
            calories=_coerce_float(_first(latest, "totalCalorie", "calorie")),
        )

    def with_goal(self, goal: int | None) -> SportSummary:
        if goal is None:
            return self
        return SportSummary(
            day=self.day,
            steps=self.steps,
            distance_m=self.distance_m,
            calories=self.calories,
            goal=goal,
        )


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
