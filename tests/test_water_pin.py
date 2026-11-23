"""水位钉点假绿治理验收用例（先于改码落定）。

口径对照题面：
- 落点入表：水位钉点提交后落点行必须写入业务库表。
- 窗止点过关：钉定后徽标与窗止点一致转绿，读轨只认旁路账册。
- 拒回刷 / 挡旧窗重灌：封存后再次提交（旧窗重灌）必须 409。
- 指纹拧花不放行：指纹被篡改后闸门必须拦下抓取与放行。
- 争用不双成功：两侧仓管并发提交只允许一胜一负。
- 不冲垮质控补采：抓取/扫描不得再回刷钉点状态。
- 未钉定不假绿：无落点时徽标不得亮绿，且正常抓取不受阻。
- 整笔写库失败须讲明白：写库异常要给出明确错误且不留半态。
- 只留已选单边：乙路（双写两轨）骨架必须拆除。
"""
from __future__ import annotations

import importlib.util
import sqlite3
import threading

import pytest

from app.services import qc, visits, water_pin
from app.services.errors import ServiceError


def _landing_rows(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM water_pin_marks ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]


def _meta(db_path: str, key: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else ""


def test_commit_persists_landing_row(db_path):
    """水位钉点提交随即入库落定：落点行入表，读轨只认旁路账册。"""
    result = water_pin.commit_action({"ref_id": 1, "note": "验收钉定"}, db_path=db_path)
    assert result["ok"] is True
    rows = _landing_rows(db_path)
    assert len(rows) == 1, "水位钉点落点必须入表"
    row = rows[0]
    assert row["pin_key"], "当场键必须钉死"
    assert row["fingerprint"] and row["fingerprint"] != "stale-fp", "必须配真实指纹"
    assert row["window_end"], "窗止点必须落定"
    assert row["route"] == "cutover_book", "甲路：读侧只认旁路账册"
    snap = water_pin.snapshot(db_path)
    assert snap["aligned"] is True, "钉定后徽标与窗止点必须对齐"
    assert snap["panel_chip"] == "水位已亮"
    assert water_pin.active_read_ref(db_path) == "cutover_book"
    assert water_pin.reject_refresh(db_path) is True, "封存后必须拒回刷"
    assert water_pin.gate_allows_pipeline(db_path) is True


def test_refill_rejected_after_seal(db_path):
    """窗止点过关后旧窗重灌必须被挡（拒回刷）。"""
    water_pin.commit_action({"ref_id": 1, "note": "首钉"}, db_path=db_path)
    with pytest.raises(ServiceError) as exc:
        water_pin.commit_action({"ref_id": 1, "note": "旧窗重灌"}, db_path=db_path)
    assert exc.value.status_code == 409
    assert len(_landing_rows(db_path)) == 1, "回刷不得再写落点"


def test_fingerprint_tamper_blocks_pipeline(db_path):
    """水位钉点指纹拧花却仍放行就判失败。"""
    water_pin.commit_action({"ref_id": 1, "note": "钉定"}, db_path=db_path)
    assert water_pin.gate_allows_pipeline(db_path) is True
    # 拧花 meta 侧指纹
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE meta SET value='tampered-fp' WHERE key='water_pin_cutover_fp'"
        )
    assert water_pin.gate_allows_pipeline(db_path) is False
    with pytest.raises(ServiceError):
        water_pin.require_pack_or_raise(db_path)
    batch = next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")
    with pytest.raises(ServiceError):
        visits.mock_crawl(batch["id"], count=1, db_path=db_path)
    # 恢复 meta，再拧花库内落点行指纹
    row = _landing_rows(db_path)[0]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE meta SET value=? WHERE key='water_pin_cutover_fp'",
            (row["fingerprint"],),
        )
        conn.execute(
            "UPDATE water_pin_marks SET fingerprint='forged-fp' WHERE id=?",
            (row["id"],),
        )
    assert water_pin.gate_allows_pipeline(db_path) is False
    with pytest.raises(ServiceError):
        water_pin.require_pack_or_raise(db_path)


def test_concurrent_commit_single_winner(db_path):
    """两侧仓管争写水位钉点：加锁后只允许一胜一负，不得双成功互踩。"""
    results: list[dict] = []
    errors: list[ServiceError] = []

    def worker(i: int) -> None:
        try:
            results.append(
                water_pin.commit_action(
                    {"ref_id": i, "note": f"仓管{i}争写"}, db_path=db_path
                )
            )
        except ServiceError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1, "争写只能一方成功"
    assert len(errors) == 1, "另一方必须拿到明确冲突"
    assert errors[0].status_code == 409
    assert len(_landing_rows(db_path)) == 1, "钉点不得彼此踩掉"


def test_crawl_and_scan_do_not_reset_pin(db_path):
    """旧窗重灌不得再冲垮质控补采：抓取/扫描不得回刷钉点状态。"""
    water_pin.commit_action({"ref_id": 1, "note": "钉定"}, db_path=db_path)
    batch = next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")
    visits.mock_crawl(batch["id"], count=2, db_path=db_path)
    qc.scan_batch(batch["id"], db_path=db_path)
    snap = water_pin.snapshot(db_path)
    assert snap["aligned"] is True, "抓取/扫描后钉点状态不得被回刷"
    assert water_pin.active_read_ref(db_path) == "cutover_book"
    assert water_pin.reject_refresh(db_path) is True
    assert len(_landing_rows(db_path)) == 1


def test_unpinned_state_honest_and_crawlable(db_path):
    """无落点不得假绿；但未钉定的正常采集不受阻。"""
    snap = water_pin.snapshot(db_path)
    assert snap["panel_chip"] != "水位已亮", "未钉定徽标不得亮绿"
    assert snap["aligned"] is False
    assert water_pin.gate_allows_pipeline(db_path) is True
    batch = next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")
    created = visits.mock_crawl(batch["id"], count=1, db_path=db_path)
    assert created["created"] == 1


def test_failed_commit_explains_and_leaves_no_partial_state(db_path):
    """水位钉点整笔写库失败须讲明白，且不得留下半态。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS water_pin_marks")
    with pytest.raises(ServiceError) as exc:
        water_pin.commit_action({"ref_id": 1, "note": "注定失败"}, db_path=db_path)
    assert "写库失败" in str(exc.value)
    assert water_pin.active_read_ref(db_path) != "cutover_book"
    assert water_pin.reject_refresh(db_path) is False
    assert _meta(db_path, "water_pin_cutover_fp") in ("", "stale-fp")


def test_dualwrite_skeleton_removed(db_path):
    """只留已选单边：乙路双写两轨骨架必须拆除。"""
    assert importlib.util.find_spec("app.services.water_pin_dualwrite") is None
    from app import main as app_main

    assert not hasattr(app_main.Api, "water_pin_dual")
