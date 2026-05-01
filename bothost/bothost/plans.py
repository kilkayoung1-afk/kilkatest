"""Subscription plans, parsed from the env config.

A plan defines per-bot resources (RAM / CPU / disk / single-file size). One
subscription = one bot of that resource tier. Multi-bot per subscription is
not used in the new model: `bots` is kept in the schema for backward
compatibility but is always 1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Plan:
    id: str
    name: str
    stars: int
    days: int
    bots: int  # always 1 in the new model
    mem_mb: int  # hard RAM limit per bot
    cpu_quota: float  # nano_cpus / 1e9 — e.g. 0.5 = half a core
    disk_mb: int  # soft quota on /app/data
    fsize_mb: int  # ulimit fsize per bot — single file size cap

    def label(self) -> str:
        return (
            f"{self.name} — {self.stars}⭐ · "
            f"{_human_mem(self.mem_mb)} RAM · "
            f"{self.cpu_quota:g} CPU · "
            f"{_human_mem(self.disk_mb)} диск · "
            f"{self.days} дн."
        )

    def short_resources(self) -> str:
        return (
            f"{_human_mem(self.mem_mb)} RAM · "
            f"{self.cpu_quota:g} CPU · "
            f"{_human_mem(self.disk_mb)} диск"
        )


def _human_mem(mb: int) -> str:
    if mb >= 1024 and mb % 1024 == 0:
        return f"{mb // 1024} ГБ"
    if mb >= 1024:
        return f"{mb / 1024:.1f} ГБ"
    return f"{mb} МБ"


DEFAULT_PLANS_JSON = json.dumps(
    [
        {
            "id": "start",
            "name": "Старт",
            "stars": 50,
            "days": 14,
            "bots": 1,
            "mem_mb": 256,
            "cpu_quota": 0.25,
            "disk_mb": 100,
            "fsize_mb": 25,
        },
        {
            "id": "plus",
            "name": "Плюс",
            "stars": 130,
            "days": 14,
            "bots": 1,
            "mem_mb": 512,
            "cpu_quota": 0.5,
            "disk_mb": 300,
            "fsize_mb": 50,
        },
        {
            "id": "pro",
            "name": "Про",
            "stars": 200,
            "days": 14,
            "bots": 1,
            "mem_mb": 1024,
            "cpu_quota": 1.0,
            "disk_mb": 1024,
            "fsize_mb": 100,
        },
        {
            "id": "max",
            "name": "Макс",
            "stars": 400,
            "days": 14,
            "bots": 1,
            "mem_mb": 2048,
            "cpu_quota": 2.0,
            "disk_mb": 3072,
            "fsize_mb": 200,
        },
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
                bots=int(item.get("bots", 1)),
                mem_mb=int(item.get("mem_mb", 256)),
                cpu_quota=float(item.get("cpu_quota", 0.5)),
                disk_mb=int(item.get("disk_mb", 100)),
                fsize_mb=int(item.get("fsize_mb", 50)),
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
