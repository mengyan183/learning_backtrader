# fg_system/human30/store.py
# -*- coding: utf-8 -*-
"""Human 3.0 数据层：读写 + 原子写 + 损坏抛错（懒迁移与同日合并见后续 Task）。"""
import json
import os
from datetime import date

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "Data", "human30.json")

# 编译期默认值（不可变）：用于识别运行时 monkeypatch 后的路径。
_DEFAULT_DATA_PATH = DATA_PATH


def _data_path():
    """运行时解析数据路径（兼容两种 monkeypatch 习惯，且绝不误写真实 Data/）：

    - v1 测试：`monkeypatch.setattr(human30, "DATA_PATH", ...)`（包命名空间）；
    - 包内 store 测试：`monkeypatch.setattr(store, "DATA_PATH", ...)`（本模块）。

    谁被改离默认值就用谁；都没改则用本模块默认值。这样无论测试猴补哪一层，
    都会落在临时路径，而不会去写真实的 Data/human30.json。
    """
    import sys
    pkg = sys.modules.get("fg_system.human30")
    pkg_path = getattr(pkg, "DATA_PATH", None) if pkg is not None else None
    if DATA_PATH != _DEFAULT_DATA_PATH:      # 本模块被猴补 ⇒ 优先（包内测试）
        return DATA_PATH
    if pkg_path and pkg_path != _DEFAULT_DATA_PATH:   # 包命名空间被猴补 ⇒ v1 测试
        return pkg_path
    return DATA_PATH


def _load():
    """读数据文件。文件不存在 ⇒ 空历史（唯一允许降级的情形）。"""
    if not os.path.exists(_data_path()):
        return {"records": []}
    try:
        with open(_data_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # S-2（2026-10-12）：**不得**把「文件损坏」降级成「空历史」——
        # 否则下一次 _save() 会把损坏文件整个覆盖，用户打卡记录永久丢失。
        raise RuntimeError(
            "human30 数据文件损坏/不可读，拒绝按空历史处理"
            "（否则下一次写入会把它覆盖丢失）：%s（%s: %s）"
            % (_data_path(), type(e).__name__, e))


def _save(data):
    """原子写：tmp + fsync + os.replace，杜绝半截 JSON。"""
    d = os.path.dirname(_data_path())
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    tmp = _data_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _data_path())


def _merge_same_day(old, new):
    """同日合并。

    规则（评审 C-3 修正版）：
      - **新记录里出现的顶层 key 一律整体取新值**（如 `market` 快照 ⇒ 非法值不残留 ✓）
      - **新记录里没有的顶层 key 保留旧值**（如 v2 的 `schema` / `levels` / `phases` ✓）
    """
    if old is None:
        return dict(new)
    merged = dict(new)
    for k, v in old.items():
        if k not in new:
            merged[k] = v
    return merged


def record(mind, body, spirit, vocation, note="", when=None, market=None):
    """追加一条自评记录（同日重复打卡则**合并**当日：新值覆盖、旧 v2 字段保留）。返回该记录。"""
    for v in (mind, body, spirit, vocation):
        if not (0 <= v <= 100):
            raise ValueError("四象限评分必须在 0-100 之间")
    rec = {
        "date": when or date.today().isoformat(),
        "mind": float(mind), "body": float(body),
        "spirit": float(spirit), "vocation": float(vocation),
        "note": note,
    }
    if market:
        m = {}
        try:
            m["fg_index"] = round(float(market.get("fg_index")), 1)
        except (TypeError, ValueError):
            pass
        try:
            m["zone"] = int(market.get("zone"))
        except (TypeError, ValueError):
            pass
        if m:
            rec["market"] = m

    data = _load()
    data.setdefault("records", [])
    old = next((r for r in data["records"] if r.get("date") == rec["date"]), None)
    merged = _merge_same_day(old, rec)
    # 只替换同日那一条，**其余记录原样保留**（不重排、不改字段）
    data["records"] = [r for r in data["records"] if r.get("date") != rec["date"]]
    data["records"].append(merged)
    data["records"].sort(key=lambda r: r.get("date") or "")
    _save(data)
    return merged


def latest():
    """最新一条记录（已懒迁移）；无记录返回 None。"""
    records = _load().get("records", [])
    return migrate_record(records[-1]) if records else None


def history(n=30):
    """最近 n 条记录（时间升序，均已懒迁移）。"""
    return [migrate_record(r) for r in _load().get("records", [])[-n:]]


def bucket_level(score):
    """旧记录分档映射（〔自创〕，沿用 v1 阈值）：>70→3，40..70→2，<40→1。"""
    if score > 70:
        return 3
    if score >= 40:
        return 2
    return 1


def migrate_record(rec):
    """懒迁移：为旧记录补 levels/phases（幂等；不改动原字段）。"""
    from . import model
    out = dict(rec)
    if "levels" not in out:
        out["levels"] = {q: bucket_level(out[q]) for q in model.QUADRANTS if q in out}
    if "phases" not in out:
        out["phases"] = {q: "unknown" for q in model.QUADRANTS}
    return out
