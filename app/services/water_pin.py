"""水位钉点：甲路（旁路账册）唯一保留路线。

口径：
- 提交即整笔写库：落点行写入 water_pin_marks，同事务落定读轨引用，
  写库失败给出明确错误且不留半态。
- 封存后拒回刷：已有在效钉点时再次提交（旧窗重灌）一律 409。
- 徽标与窗止点派生自真实落点与指纹核验，不再读取可伪造的展示位。
- 闸门：无落点正常放行；有落点必须指纹三方一致（库行 / meta / 重算）。
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime

from app.db import get_db
from app.services.errors import ServiceError

_SLUG = "water_pin"
_OK = "水位已亮"
_BAD = "窗止点旧"
_TITLE = "水位钉点"
_OLD = "old_track"
_CUTOVER = "cutover_book"

_COMMIT_LOCK = threading.Lock()


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def _fingerprint(pin_key: str, window_end: str, ref_id: int, note: str) -> str:
    raw = f"{pin_key}|{window_end}|{ref_id}|{note}|{_CUTOVER}"
    return "fp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def landing_rows(db_path: str | None = None) -> list[dict]:
    """水位钉点名录：落点行全量（按落点先后排队）。"""
    try:
        with get_db(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM water_pin_marks ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def active_landing(db_path: str | None = None) -> dict | None:
    rows = [r for r in landing_rows(db_path) if r.get("is_active") == 1]
    return rows[-1] if rows else None


def active_read_ref(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_active_read", _OLD)


def cutover_fp(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_cutover_fp", "")


def reject_refresh(db_path: str | None = None) -> bool:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_reject_refresh", "0") == "1"


def window_end(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_window_end", "")


def _fingerprint_consistent(row: dict, meta_fp: str) -> bool:
    expected = _fingerprint(
        str(row.get("pin_key", "")),
        str(row.get("window_end", "")),
        int(row.get("ref_id") or 0),
        str(row.get("note", "")),
    )
    stored = str(row.get("fingerprint", ""))
    return bool(stored) and stored == expected and meta_fp == expected


def alignment(db_path: str | None = None) -> dict:
    """汇总钉点真实状态：封存、指纹、读轨、对齐。"""
    row = active_landing(db_path)
    ref = active_read_ref(db_path)
    meta_fp = cutover_fp(db_path)
    sealed = (
        row is not None
        and ref == _CUTOVER
        and reject_refresh(db_path)
    )
    fp_ok = bool(row) and _fingerprint_consistent(row, meta_fp)
    aligned = bool(sealed and fp_ok)
    return {
        "landing": row,
        "sealed": sealed,
        "fp_ok": fp_ok,
        "aligned": aligned,
        "active_read": ref,
        "cutover_fp": meta_fp,
        "reject_refresh": reject_refresh(db_path),
        "window_end": window_end(db_path),
        "mismatch": bool(row) and not aligned,
    }


def panel_chip(db_path: str | None = None) -> str:
    """徽标派生自真实对齐态，未钉定/拧花一律不亮绿。"""
    return _OK if alignment(db_path)["aligned"] else _BAD


def truth_flag(db_path: str | None = None) -> str:
    return _OK if alignment(db_path)["aligned"] else _BAD


def commit_action(payload: dict | None = None, db_path: str | None = None) -> dict:
    """水位钉点提交：甲路写旁路账册，当场键钉死并配指纹。

    已封存时拒回刷（409）；整笔写库失败给出明确错误且不留半态。
    """
    payload = payload or {}
    ref_id = int(payload.get("ref_id") or payload.get("ref") or 0)
    note = (str(payload.get("note") or "水位钉定")).strip()[:200] or "水位钉定"
    with _COMMIT_LOCK:
        try:
            with get_db(db_path) as conn:
                existing = conn.execute(
                    "SELECT id FROM water_pin_marks WHERE is_active=1"
                ).fetchone()
                if existing:
                    raise ServiceError(
                        f"{_TITLE}已封存（落点 #{existing['id']}），拒回刷：旧窗重灌被挡",
                        409,
                    )
                counter = int(_meta_get(conn, f"{_SLUG}_counter", "0") or "0") + 1
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                pin_key = f"WP-{stamp}-{counter:04d}"
                wend = f"WEND-{stamp}-{counter:04d}"
                fp = _fingerprint(pin_key, wend, ref_id, note)
                cur = conn.execute(
                    """
                    INSERT INTO water_pin_marks(
                      pin_key, route, window_end, fingerprint, ref_id, note,
                      status, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, '已钉定', 1)
                    """,
                    (pin_key, _CUTOVER, wend, fp, ref_id, note),
                )
                mark_id = cur.lastrowid
                _meta_set(conn, f"{_SLUG}_counter", str(counter))
                _meta_set(conn, f"{_SLUG}_active_read", _CUTOVER)
                _meta_set(conn, f"{_SLUG}_reject_refresh", "1")
                _meta_set(conn, f"{_SLUG}_cutover_fp", fp)
                _meta_set(conn, f"{_SLUG}_window_end", wend)
                _meta_set(conn, f"{_SLUG}_last_payload", str(payload)[:200])
                _meta_set(
                    conn,
                    f"{_SLUG}_evt_{counter}",
                    f"钉定落点#{mark_id} {pin_key} 窗止点{wend} 指纹{fp}",
                )
        except ServiceError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ServiceError(f"{_TITLE}争用冲突，整笔写库已回滚: {exc}", 409) from exc
        except sqlite3.Error as exc:
            raise ServiceError(f"{_TITLE}整笔写库失败: {exc}", 500) from exc
    snap = snapshot(db_path)
    return {
        "ok": True,
        "chip": snap["panel_chip"],
        "title": _TITLE,
        "landing": snap["landing"],
        "active_read": snap["active_read"],
        "cutover_fp": snap["cutover_fp"],
        "reject_refresh": snap["reject_refresh"],
        "window_end": snap["window_end"],
        "message": f"{_TITLE}已钉定封存，读轨只认旁路账册",
    }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    """抓取闸门：无落点放行；有落点必须封存且指纹一致（拧花即挡）。"""
    rows = landing_rows(db_path)
    if not rows:
        return True
    return alignment(db_path)["aligned"]


def require_pipeline_allowed(db_path: str | None = None) -> None:
    if not gate_allows_pipeline(db_path):
        raise ServiceError(
            f"{_TITLE}徽标与窗止点拧花（指纹不一致），旧窗重灌被挡",
            409,
        )


def require_pack_or_raise(db_path: str | None = None) -> None:
    if not alignment(db_path)["aligned"]:
        raise ServiceError(f"{_TITLE}读轨未对齐，禁止放行", 409)


def snapshot(db_path: str | None = None) -> dict:
    state = alignment(db_path)
    rows = landing_rows(db_path)
    chip = _OK if state["aligned"] else _BAD
    return {
        "title": _TITLE,
        "panel_chip": chip,
        "truth": chip,
        "aligned": state["aligned"],
        "sealed": state["sealed"],
        "fp_ok": state["fp_ok"],
        "mismatch": state["mismatch"],
        "landing": state["landing"],
        "landing_count": len(rows),
        "active_read": state["active_read"],
        "cutover_fp": state["cutover_fp"],
        "reject_refresh": state["reject_refresh"],
        "window_end": state["landing"]["window_end"] if state["landing"] else "",
        "route": _CUTOVER,
    }


def queue_shape(db_path: str | None = None) -> list[dict]:
    """水位钉点队列形态面：名录按落点先后排成队列节点。"""
    state = alignment(db_path)
    nodes = []
    for idx, row in enumerate(landing_rows(db_path), start=1):
        nodes.append(
            {
                "seq": idx,
                "id": row["id"],
                "pin_key": row["pin_key"],
                "window_end": row["window_end"],
                "fingerprint": row["fingerprint"],
                "status": row["status"],
                "active": bool(row.get("is_active")),
                "stage": "读轨换线" if state["aligned"] and row.get("is_active") else "封存",
            }
        )
    return nodes


def dashboard(db_path: str | None = None) -> dict:
    snap = snapshot(db_path)
    return {
        "title": _TITLE,
        "chip": snap["panel_chip"],
        "truth": snap["truth"],
        "aligned": snap["aligned"],
        "sealed": snap["sealed"],
        "mismatch": snap["mismatch"],
        "landing": snap["landing"],
        "rows": landing_rows(db_path),
        "queue": queue_shape(db_path),
        "landing_count": snap["landing_count"],
        "active_read": snap["active_read"],
        "cutover_fp": snap["cutover_fp"],
        "reject_refresh": snap["reject_refresh"],
        "window_end": snap["window_end"],
        "route": _CUTOVER,
        "ok_chip": _OK,
        "bad_chip": _BAD,
        "label": "水位钉点",
    }


def list_events(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "note": r["value"]} for r in rows]
