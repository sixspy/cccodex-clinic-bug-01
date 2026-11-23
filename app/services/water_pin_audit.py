"""水位钉点读轨审计：汇总甲路旁路账册一侧引用（乙路骨架已拆除）。"""
from __future__ import annotations

from app.services.water_pin import list_events
from app.services.water_pin_cutover import board as cutover_board


def audit_list(db_path: str | None = None) -> list[dict]:
    return [{"key": e["key"], "value": e["note"]} for e in list_events(db_path)]


def audit_summary(db_path: str | None = None) -> dict:
    return {
        "title": "水位钉点审计",
        "events": audit_list(db_path),
        "cutover": cutover_board(db_path),
    }
