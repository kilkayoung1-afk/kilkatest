"""Subscription plans, parsed from the env config."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Plan:
    id: str
    name: str
    stars: int
    days: int
    bots: int

    def label(self) -> str:
        return f"{self.name} — {self.stars}⭐ ({self.bots} бот{_bots_suffix(self.bots)} / {self.days} дн.)"


def _bots_suffix(n: int) -> str:
    if n == 1:
        return ""
    if 2 <= n <= 4:
        return "а"
    return "ов"


DEFAULT_PLANS_JSON = json.dumps(
    [
        {"id": "start", "name": "Старт", "stars": 50, "days": 14, "bots": 1},
        {"id": "plus", "name": "Плюс", "stars": 130, "days": 14, "bots": 3},
        {"id": "pro", "name": "Про", "stars": 200, "days": 14, "bots": 5},
        {"id": "max", "name": "Без лимита", "stars": 400, "days": 14, "bots": 20},
    ],
    ensure_ascii=False,
)


def parse_plans(raw: str | None) -> list[Plan]:
    """Parse plans from a JSON string. Falls back to defaults if empty."""

    text = (raw or "").strip() or DEFAULT_PLANS_JSON
    data = json.loads(text)
    plans: list[Plan] = []
    for item in data:
        plans.append(
            Plan(
                id=str(item["id"]),
                name=str(item["name"]),
                stars=int(item["stars"]),
                days=int(item["days"]),
                bots=int(item["bots"]),
            )
        )
    if not plans:
        raise RuntimeError("No subscription plans configured.")
    return plans


def find_plan(plans: list[Plan], plan_id: str) -> Plan | None:
    for plan in plans:
        if plan.id == plan_id:
            return plan
    return None
