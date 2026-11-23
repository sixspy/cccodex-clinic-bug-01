"""水位钉点甲路·旁路账册：当场键钉死配指纹，读侧只认这本账册并拒回刷。"""
from __future__ import annotations

from app.services.water_pin import (
    active_read_ref,
    commit_action,
    cutover_fp,
    dashboard,
    landing_rows,
    panel_chip,
    reject_refresh,
    truth_flag,
)

_SLUG = "water_pin"
_TITLE = "水位钉点"


def append_cutover(ref_id: int, note: str, db_path: str | None = None) -> dict:
    """切流账册落笔：与提交同一条整笔写库路径，封存后拒回刷。"""
    result = commit_action({"ref_id": ref_id, "note": note or _TITLE}, db_path=db_path)
    return {
        "ref_id": ref_id,
        "note": note,
        "panel": panel_chip(db_path),
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
        "cutover_fp": cutover_fp(db_path),
        "reject_refresh": reject_refresh(db_path),
        "landing": result.get("landing"),
    }


def cutover_rows(db_path: str | None = None) -> list[dict]:
    return [
        {
            **row,
            "chip": panel_chip(db_path),
            "active_read": active_read_ref(db_path),
        }
        for row in landing_rows(db_path)
    ]


def board(db_path: str | None = None) -> dict:
    dash = dashboard(db_path)
    dash["cutover"] = cutover_rows(db_path)
    dash["fate"] = "cutover_book"
    return dash
