# -*- coding: utf-8 -*-
"""守猪待兔**前向录入**的存储层测试（第 12.26 条）。

只测可离线复现的部分（幂等、越界、白名单、密钥读取）。
**不测 API 抓取** —— 接口契约尚未确认，按第 8 条流程不写投机代码。
"""
import os

import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader, shoutu


# ---------------------------------------------------------------- 转换
def test_mapping_to_frame_uses_today_by_default():
    df = shoutu.mapping_to_frame({"CONL": 24})
    assert list(df.columns) == shoutu.RECORD_COLUMNS
    assert df.iloc[0]["date"] == pd.Timestamp.today().normalize()
    assert df.iloc[0]["symbol"] == "CONL"
    assert df.iloc[0]["value"] == 24.0


def test_mapping_to_frame_normalizes_symbol_case():
    df = shoutu.mapping_to_frame({"conl": 1}, date="2026-09-22")
    assert df.iloc[0]["symbol"] == "CONL"
    assert df.iloc[0]["date"] == pd.Timestamp("2026-09-22")


# ---------------------------------------------------------------- 幂等并入
def test_append_creates_file_when_missing(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    wide, n = shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22"), p)
    assert n == 1
    assert os.path.exists(p)
    assert wide.loc[pd.Timestamp("2026-09-22"), "CONL"] == 24.0


def test_append_is_idempotent_on_same_date_and_symbol(tmp_path):
    """同一天同一标的录两次**不得**产生两行 —— 否则分布被污染。"""
    p = str(tmp_path / "shoutu_fng.csv")
    rec = shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22")
    shoutu.append_records(rec, p)
    shoutu.append_records(rec, p)
    raw = pd.read_csv(p)
    assert len(raw) == 1


def test_append_correction_overwrites(tmp_path):
    """补录/更正取**后写入的值**（keep=last），不是保留旧值。"""
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 26}, "2026-09-22"), p)
    wide, _ = shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22"), p)
    assert wide.loc[pd.Timestamp("2026-09-22"), "CONL"] == 24.0


def test_append_merges_new_date_with_existing(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22"), p)
    wide, _ = shoutu.append_records(shoutu.mapping_to_frame({"YINN": -41}, "2026-09-23"), p)
    assert wide.shape == (2, 2)
    assert wide.loc[pd.Timestamp("2026-09-23"), "YINN"] == -41.0
    assert wide.loc[pd.Timestamp("2026-09-22"), "CONL"] == 24.0


def test_append_keeps_rows_sorted(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(shoutu.mapping_to_frame({"YINN": -41}, "2026-09-23"), p)
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22"), p)
    raw = pd.read_csv(p)
    assert list(raw["date"]) == ["2026-09-22", "2026-09-23"]
    assert raw["date"].is_monotonic_increasing


# ---------------------------------------------------------------- 失败不落盘
def test_out_of_range_raises_and_does_not_touch_file(tmp_path):
    """越界必须**报错且不写文件** —— 静默截断会把口径错误伪装成极值信号。"""
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22"), p)
    before = open(p, encoding="utf-8").read()
    with pytest.raises(shoutu.ShoutuError, match="越界"):
        shoutu.append_records(shoutu.mapping_to_frame({"CONL": 101}, "2026-09-23"), p)
    assert open(p, encoding="utf-8").read() == before


@pytest.mark.parametrize("value", [-101.0, 101.0])
def test_out_of_range_both_directions(tmp_path, value):
    p = str(tmp_path / "shoutu_fng.csv")
    with pytest.raises(shoutu.ShoutuError, match="越界"):
        shoutu.append_records(shoutu.mapping_to_frame({"CONL": value}, "2026-09-22"), p)
    assert not os.path.exists(p)


def test_boundary_values_are_accepted(tmp_path):
    """±100 是**量程内**，不得被当成越界（边界条件）。"""
    p = str(tmp_path / "shoutu_fng.csv")
    wide, _ = shoutu.append_records(
        shoutu.mapping_to_frame({"CONL": 100, "YINN": -100}, "2026-09-22"), p)
    assert wide.loc[pd.Timestamp("2026-09-22"), "CONL"] == 100.0
    assert wide.loc[pd.Timestamp("2026-09-22"), "YINN"] == -100.0


def test_unknown_symbol_raises(tmp_path):
    """白名单防录入笔误：CONLL 不应被静默接受。"""
    p = str(tmp_path / "shoutu_fng.csv")
    with pytest.raises(shoutu.ShoutuError, match="未知标的"):
        shoutu.append_records(shoutu.mapping_to_frame({"CONLL": 24}, "2026-09-22"), p)
    assert not os.path.exists(p)


def test_missing_column_raises(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    with pytest.raises(shoutu.ShoutuError, match="缺少列"):
        shoutu.append_records(pd.DataFrame({"date": ["2026-09-22"], "value": [24.0]}), p)


def test_unparsable_value_raises(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    df = pd.DataFrame({"date": ["2026-09-22"], "symbol": ["CONL"], "value": ["abc"]})
    with pytest.raises(shoutu.ShoutuError, match="无法解析"):
        shoutu.append_records(df, p)


# ---------------------------------------------------------------- 密钥
def test_load_token_prefers_env(tmp_path, monkeypatch):
    f = tmp_path / "shoutu_token"
    f.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv(shoutu.TOKEN_ENV, "from-env")
    assert shoutu.load_token(str(f)) == "from-env"


def test_load_token_falls_back_to_file(tmp_path, monkeypatch):
    f = tmp_path / "shoutu_token"
    f.write_text("  secret-value\n", encoding="utf-8")
    monkeypatch.delenv(shoutu.TOKEN_ENV, raising=False)
    assert shoutu.load_token(str(f)) == "secret-value"


def test_load_token_missing_file_raises_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv(shoutu.TOKEN_ENV, raising=False)
    missing = str(tmp_path / "nope_token")
    with pytest.raises(shoutu.ShoutuError) as exc:
        shoutu.load_token(missing)
    assert missing in str(exc.value)              # 提示路径
    assert shoutu.TOKEN_ENV in str(exc.value)     # 提示环境变量名


def test_load_token_empty_file_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(shoutu.TOKEN_ENV, raising=False)
    f = tmp_path / "shoutu_token"
    f.write_text("   \n", encoding="utf-8")
    with pytest.raises(shoutu.ShoutuError, match="为空"):
        shoutu.load_token(str(f))


def test_token_path_is_gitignored():
    """**守卫**：密钥文件必须落在 .gitignore 覆盖范围内，否则会入库。

    本测试直接问 git（`git check-ignore`），而不是读 .gitignore 文本做字符串
    匹配 —— 后者无法验证 glob 是否真的命中（`Data/*token*` **不**匹配
    `Data/raw/shoutu_token`，这类错误只有问 git 才能发现）。
    """
    import subprocess
    if not os.path.isdir(os.path.join(config.ROOT, ".git")):
        pytest.skip("非 git 仓库")
    r = subprocess.run(["git", "check-ignore", "-q", config.SHOUTU_TOKEN_PATH],
                       cwd=config.ROOT, capture_output=True)
    assert r.returncode == 0, (
        "%s **未**被 .gitignore 覆盖，密钥会入库！" % config.SHOUTU_TOKEN_PATH)


# ---------------------------------------------------------------- 真实文件守卫
# ---------------------------------------------------------------- E1 全市场抓取解析
def test_parse_universe_rows_basic():
    lines = ["美股杠杆~US.TQQQ~三倍纳指~33~80.750~368.85",
             "我的自选~US.CONL~两倍Coin~27~6.790~6.14"]
    df = shoutu.parse_universe_rows(lines, date="2026-09-23")
    assert len(df) == 2
    assert list(df.columns) == shoutu.UNIVERSE_COLUMNS
    r = df[df["code"] == "US.TQQQ"].iloc[0]
    assert r["category"] == "美股杠杆"
    assert r["name"] == "三倍纳指"
    assert r["fg_index"] == 33.0
    assert r["price"] == 80.75
    assert r["scale"] == 368.85


def test_parse_universe_rows_keeps_name_with_spaces():
    """**守卫**：名称含空格必须完整保留 —— 这是选 `~` 作分隔符的唯一理由。

    若将来有人把分隔符改成空格或逗号，这条会立刻失败。
    """
    df = shoutu.parse_universe_rows(
        ["美股杠杆~US.AXTX~2倍做多AXTI ETF-Tradr~-21~35.50~0.5"])
    assert df.iloc[0]["name"] == "2倍做多AXTI ETF-Tradr"


def test_parse_universe_rows_skips_masked_and_broken():
    """未激活时数值是 `**` ⇒ 该行跳过；残缺行也跳过（**不得抛异常**）。

    页面改版时宁可少收几行，也不能让整个抓取失败 ——
    抓取失败意味着当天没有数据。
    """
    df = shoutu.parse_universe_rows([
        "美股杠杆~US.TQQQ~三倍纳指~**~80.750~368.85",   # 未激活打码
        "美股杠杆~US.SOXL~三倍半导体",                    # 残缺
        "",                                              # 空行
        "美股杠杆~US.UPRO~三倍标普~24~153.830~54.93",    # 正常
    ])
    assert list(df["code"]) == ["US.UPRO"]


def test_parse_universe_rows_empty_input():
    assert shoutu.parse_universe_rows([]).empty
    assert shoutu.parse_universe_rows(None).empty


def test_record_universe_is_idempotent_per_day(tmp_path):
    """同一天重复抓取**覆盖**而不是追加（抓取会重跑，不能越抓越多）。"""
    p = str(tmp_path / "u.csv")
    df = shoutu.parse_universe_rows(["美股杠杆~US.TQQQ~三倍纳指~33~80.75~368.85"],
                                    date="2026-09-23")
    shoutu.record_universe(df, p)
    merged, _ = shoutu.record_universe(df, p)
    assert len(merged) == 1


def test_record_universe_keeps_overlapping_categories(tmp_path):
    """**守卫**：分类是**重叠**的（`我的自选` ⊂ `美股杠杆`），
    去重键必须含 `category`，否则会丢掉分类信息。

    实测：按 `(date, code)` 去重会把 379 行压成 **361** 行。
    """
    p = str(tmp_path / "u.csv")
    df = shoutu.parse_universe_rows([
        "我的自选~US.CONL~两倍Coin~27~6.79~6.14",
        "美股杠杆~US.CONL~两倍Coin~27~6.79~6.14",
    ], date="2026-09-23")
    merged, _ = shoutu.record_universe(df, p)
    assert len(merged) == 2
    assert set(merged["category"]) == {"我的自选", "美股杠杆"}


def test_record_universe_keeps_other_days(tmp_path):
    p = str(tmp_path / "u.csv")
    a = shoutu.parse_universe_rows(["美股杠杆~US.TQQQ~三倍纳指~33~80.75~368.85"],
                                   date="2026-09-22")
    b = shoutu.parse_universe_rows(["美股杠杆~US.TQQQ~三倍纳指~30~79.00~368.85"],
                                   date="2026-09-23")
    shoutu.record_universe(a, p)
    merged, _ = shoutu.record_universe(b, p)
    assert len(merged) == 2
    assert list(merged["fg_index"]) == [33.0, 30.0]


def test_token_never_appears_in_tracked_files():
    """**守卫**：密钥**不得**出现在任何已跟踪文件中（用户要求只留本地）。

    为什么必须问 git 而不是遍历目录：`git grep` 只搜**已跟踪**文件，
    正好对应"会不会被提交/推送"这个问题；直接遍历目录会把 gitignore 的
    密钥文件本身也算进去，必然误报。

    同时检查**前 8 位**：站点在「我的」页显示的打码形式正是"前 8 + 后 8"，
    把它抄进文档同样是泄漏（本轮就犯过这个错，而且**第一次修的时候又抄了一遍**）。
    探测长度取 8 而不是更长 —— 更长的前缀**拦不住**站点实际暴露的那 8 位。
    """
    import subprocess
    if not os.path.isdir(os.path.join(config.ROOT, ".git")):
        pytest.skip("非 git 仓库")
    try:
        token = shoutu.load_token()
    except shoutu.ShoutuError:
        pytest.skip("未配置密钥")
    for probe, label in ((token, "完整密钥"), (token[:8], "密钥前 8 位")):
        r = subprocess.run(["git", "grep", "-q", "-F", probe],
                           cwd=config.ROOT, capture_output=True)
        # git grep：0 = 命中（泄漏）；1 = 未命中（正常）
        assert r.returncode == 1, (
            "%s 出现在已跟踪文件中，会被提交/推送！" % label)


def test_real_file_symbols_are_whitelisted():
    """真实 CSV 里的标的必须在白名单内（防手工编辑绕过校验）。"""
    if not os.path.exists(config.SHOUTU_FNG_PATH):
        pytest.skip("真实守猪待兔文件不存在")
    wide = loader.load_shoutu_fng()
    assert set(wide.columns) <= set(config.SHOUTU_SYMBOLS)


def test_recorded_symbols_counts_days(tmp_path):
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 24, "YINN": -41}, "2026-09-22"), p)
    shoutu.append_records(shoutu.mapping_to_frame({"CONL": 30}, "2026-09-23"), p)
    assert shoutu.recorded_symbols(p) == {"CONL": 2, "YINN": 1}


def test_recorded_symbols_empty_when_missing(tmp_path):
    assert shoutu.recorded_symbols(str(tmp_path / "nope.csv")) == {}


# ================================================================ price 列（2026-09-24 spec A2）
# 目的：`price` 与贪恐指数**并列留存**，供后续做「价格 × 情绪」的对照。
# 三条抓取路径其实**早已拿到 price**（分类表的 price 列 / 查询面板的「股票价格」/
# API 的 data.price），此前只是丢掉 —— 这里把"传下去"钉死。

# ⚠️ 原有一条 `test_record_columns_include_price`（断言常量 == [...]）已删：
# 改代码即可改绿、无判别力；且 `test_mapping_to_frame_price_defaults_to_nan`
# 已断言 `list(df.columns) == shoutu.RECORD_COLUMNS`，覆盖同一件事（评审指出）。

def test_column_names_stay_disjoint_from_history(tmp_path):
    """**契约**：前向文件用 `value`、历史文件用 `score` —— 列名**刻意不同**。

    这不是风格问题：两表若被 `pd.concat`，列名不重叠 ⇒ **不报错**，而是各自
    一半 NaN —— 最危险的失败模式（静默产出"看起来有值"的表）。
    把"刻意不同"从**文档约定**升为**可执行契约**：谁要合并，必须先显式 rename。
    """
    fng, hist = str(tmp_path / "fng.csv"), str(tmp_path / "hist.csv")
    shoutu.append_records(
        shoutu.mapping_to_frame({"CONL": 24}, date="2026-09-22"), path=fng)
    shoutu.record_history(
        pd.DataFrame([{"date": "2026-09-22", "symbol": "CONL",
                       "score": 24, "price": 6.79}]), path=hist)

    fng_cols = list(loader.load_shoutu_records(fng).columns)
    hist_cols = list(loader.load_shoutu_history(hist).columns)
    assert "value" in fng_cols and "score" not in fng_cols
    assert "score" in hist_cols and "value" not in hist_cols


def test_mapping_to_frame_price_defaults_to_nan():
    """手动录入（`cli shoutu-record --values`）不带 price ⇒ NaN，**不报错**。"""
    df = shoutu.mapping_to_frame({"CONL": 24}, date="2026-09-22")
    assert list(df.columns) == shoutu.RECORD_COLUMNS
    assert df["price"].isna().all()


def test_mapping_to_frame_accepts_prices():
    df = shoutu.mapping_to_frame({"CONL": 24}, date="2026-09-22",
                                 prices={"CONL": 6.79})
    assert df["price"].iloc[0] == pytest.approx(6.79)


def test_mapping_to_frame_missing_price_for_one_symbol_is_nan():
    df = shoutu.mapping_to_frame({"CONL": 24, "YINN": -41}, date="2026-09-22",
                                 prices={"CONL": 6.79})
    got = dict(zip(df["symbol"], df["price"]))
    assert got["CONL"] == pytest.approx(6.79)
    assert pd.isna(got["YINN"])


def test_append_records_preserves_existing_price(tmp_path):
    """**回归红线**：并新行时**不得**丢掉旧行的 price。

    旧实现从**宽表**（只有 `value`）重读旧数据再 melt ⇒ price 会被静默清空。
    这条测试就是为那次改动钉的：写一批、再写另一天，第一批的 price 必须还在。
    """
    p = str(tmp_path / "shoutu_fng.csv")
    shoutu.append_records(
        shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22", prices={"CONL": 6.79}), p)
    wide, _ = shoutu.append_records(
        shoutu.mapping_to_frame({"YINN": -41}, "2026-09-23", prices={"YINN": 48.5}), p)

    raw = pd.read_csv(p)
    got = {(str(r["date"]), r["symbol"]): r["price"] for _, r in raw.iterrows()}
    assert got[("2026-09-22", "CONL")] == pytest.approx(6.79), "旧行的 price 被丢了"
    assert got[("2026-09-23", "YINN")] == pytest.approx(48.5)
    assert wide.loc[pd.Timestamp("2026-09-22"), "CONL"] == 24.0   # 宽表契约不变


def test_append_records_reads_legacy_three_column_file(tmp_path):
    """**向后兼容**：现网 `shoutu_fng.csv` 只有 3 列，必须照常可读、可续写。"""
    p = str(tmp_path / "legacy.csv")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("date,symbol,value\n2026-09-22,CONL,24.0\n")
    wide, _ = shoutu.append_records(
        shoutu.mapping_to_frame({"YINN": -41}, "2026-09-23", prices={"YINN": 48.5}), p)
    raw = pd.read_csv(p)
    assert list(raw.columns) == shoutu.RECORD_COLUMNS
    assert len(raw) == 2
    got = {(str(r["date"]), r["symbol"]): r["price"] for _, r in raw.iterrows()}
    assert pd.isna(got[("2026-09-22", "CONL")])          # 旧行 price 为 NaN
    assert got[("2026-09-23", "YINN")] == pytest.approx(48.5)


def test_append_records_price_unparsable_becomes_nan(tmp_path):
    """price 不可解析 ⇒ 置 NaN，**不报错**（它是参考量，不是信号）。"""
    p = str(tmp_path / "shoutu_fng.csv")
    rec = shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22")
    rec["price"] = ["abc"]
    wide, n = shoutu.append_records(rec, p)
    assert n == 1
    assert pd.isna(pd.read_csv(p)["price"].iloc[0])


def test_append_records_price_out_of_range_is_not_checked(tmp_path):
    """**price 不参与量程校验** —— 只有 `value` 受 −100~100 约束。

    若把 price 也纳入，正常股价（如 300）会被误判成"越界"而让抓取失败。
    """
    p = str(tmp_path / "shoutu_fng.csv")
    wide, n = shoutu.append_records(
        shoutu.mapping_to_frame({"CONL": 24}, "2026-09-22", prices={"CONL": 300.0}), p)
    assert n == 1
    assert pd.read_csv(p)["price"].iloc[0] == pytest.approx(300.0)


# ---------------------------------------------------------------- 取价（三条路径）

def test_universe_prices_reads_the_universe_table():
    df = shoutu.parse_universe_rows([
        "美股杠杆~US.TQQQ~三倍纳指~33~80.750~368.85",
        "我的自选~US.CONL~两倍Coin~27~6.790~6.14",
    ])
    assert shoutu.universe_prices(df, ["TQQQ", "CONL"]) == \
        {"TQQQ": pytest.approx(80.75), "CONL": pytest.approx(6.79)}
    assert shoutu.universe_prices(df, ["AXTX"]) == {}


def test_collect_score_records_keeps_price():
    """API 路径：`collect_scores` 只留 score，本函数**同时留 price**。"""
    def fake(symbol, lever, emo_area):
        return {"status": 1, "data": {"score": -73.0, "price": 145.6}}

    out = shoutu.collect_score_records(["GDXU"], fetch_one=fake)
    assert out["GDXU"]["score"] == pytest.approx(-73.0)
    assert out["GDXU"]["price"] == pytest.approx(145.6)


def test_collect_score_records_raises_on_any_failure():
    """与 `collect_scores` 同一约定：任一标的失败即抛错，不静默跳过。"""
    def fake(symbol, lever, emo_area):
        return {"status": 2, "msg": "杠杆倍数错误"}

    with pytest.raises(shoutu.ShoutuError, match="CRCG"):
        shoutu.collect_score_records(["CRCG"], fetch_one=fake)
