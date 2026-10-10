# -*- coding: utf-8 -*-
"""仪表盘服务端测试（手机访问用）。

用户需求（2026-09-23）：**支持在手机上打开**，每次打开/刷新时**主动重新计算**，
**不需要手机后台常驻**。

⇒ 设计为：Mac 上起一个只读 HTTP 服务，**每次请求重新跑 pipeline 并渲染**，
手机浏览器打开/刷新即得最新状态。**手机侧不装任何东西、不跑后台进程。**
"""
import base64
import inspect
import json
import struct
import threading
import urllib.error
import urllib.request

import pandas as pd
import pytest

from fg_system.dashboard import pwa, report, server


def _feat(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "fg_index": 50.0, "zone": 2, "core_position": 0.35, "ammo_position": 0.10,
        "target_position": 0.45, "vix": 50.0, "term": 50.0, "price": 50.0,
        "breadth": 50.0, "circuit_breaker": False,
    }, index=idx)


def _serve(get_features, tmp_path, apk_path=None, auth=None):
    """在随机端口起服务，返回 (server, base_url)。"""
    srv = server.make_server(port=0, get_features=get_features,
                             prices_path=str(tmp_path / "no_prices.csv"),
                             apk_path=apk_path, auth=auth)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def _get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.status, r.read().decode("utf-8")


# ================================================================ 核心行为

def test_serves_dashboard_over_http(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        status, body = _get(base + "/")
        assert status == 200
        assert "<!DOCTYPE html" in body
        assert 'name="viewport"' in body, "手机端必须带 viewport"
    finally:
        srv.shutdown()


def test_recomputes_on_every_request(tmp_path):
    """**核心**：每次请求都**重新计算**，不是启动时算一次后缓存。

    这正是「打开/刷新即最新」的实现方式 —— 用户明确要求的行为。
    """
    calls = []

    def fake():
        calls.append(1)
        return _feat()

    srv, base = _serve(fake, tmp_path)
    try:
        _get(base + "/")
        _get(base + "/")
        _get(base + "/")
        assert len(calls) == 3, "每次请求都应重新计算（实际 %d 次）" % len(calls)
    finally:
        srv.shutdown()


def test_unknown_path_returns_404(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/nope")
        assert exc.value.code == 404
    finally:
        srv.shutdown()


def test_render_error_returns_500_not_crash(tmp_path):
    """渲染失败必须返回 500 且**服务不挂** —— 手机端能看到错误而不是连接被拒。"""
    def boom():
        raise RuntimeError("模拟渲染失败")

    srv, base = _serve(boom, tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/")
        assert exc.value.code == 500
        assert "模拟渲染失败" in exc.value.read().decode("utf-8")
        # 服务仍可用：换成正常数据源后应能恢复
        server2, base2 = _serve(lambda: _feat(), tmp_path)
        try:
            assert _get(base2 + "/")[0] == 200
        finally:
            server2.shutdown()
    finally:
        srv.shutdown()


# ================================================================ 守卫

def test_server_never_fetches_from_api():
    """**守卫**：服务端**绝不**触发守猪待兔抓取。

    两条理由，任一条都足以禁止：

    1. 该指数**实时更新**，而 `append_records` 对同一 `(date, symbol)` 是
       **覆盖**语义 ⇒ 任何非 06:30 时刻的抓取都会把当天记录覆盖成该时刻的
       快照（§14.5 已实际发生过一次）。**每次刷新都抓 = 每次刷新都污染当天样本。**
    2. 每次刷新都消耗 `query_api` 额度（5000/月），刷新几十次就吃掉可观比例。

    ⇒ 仪表盘只做**纯计算**（读已有 CSV），抓取仍由 06:30 的定时任务独占。
    """
    src = inspect.getsource(server)
    for forbidden in ("fetch_shoutu", "collect_scores", "fetch_shoutu_score"):
        assert forbidden not in src, (
            "服务端出现了 %s —— 抓取必须留在定时任务里，见 §14.5" % forbidden)


def test_default_get_features_uses_pipeline_without_writing(tmp_path, monkeypatch):
    """默认数据源必须 `pipeline.run(write=False)` —— 不得改 features/state。

    仪表盘是**只读视图**；写盘是 06:30 任务的职责。
    """
    seen = {}

    def fake_run(write=True):
        seen["write"] = write
        return _feat()

    import fg_system.pipeline as pipeline
    monkeypatch.setattr(pipeline, "run", fake_run)
    html = server.render_dashboard()
    assert seen["write"] is False, "仪表盘不得写盘"
    assert "<!DOCTYPE html" in html


# ================================================================ APK 分发
# 公司有安全下载限制，APK **传不出公司网络**。而手机与 Mac 本就要在同一 Wi-Fi，
# 所以让 Mac 顺带把 APK 提供出去 —— 手机浏览器直接下载，不经任何第三方。

def _fake_apk(tmp_path, content=b"PK\x03\x04fake-apk-bytes"):
    p = tmp_path / "app-debug.apk"
    p.write_bytes(content)
    return str(p)


def test_serves_apk_when_present(tmp_path):
    apk = _fake_apk(tmp_path)
    srv, base = _serve(lambda: _feat(), tmp_path, apk_path=apk)
    try:
        with urllib.request.urlopen(base + "/apk", timeout=15) as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "application/vnd.android.package-archive"
            assert "attachment" in r.headers["Content-Disposition"]
            assert r.read() == b"PK\x03\x04fake-apk-bytes"
    finally:
        srv.shutdown()


def test_apk_404_with_hint_when_missing(tmp_path):
    """没构建过 APK 时要**明确说清楚**，而不是给个空响应。

    手机端只看到一个 404 会以为服务坏了；实际是"还没构建"。
    """
    srv, base = _serve(lambda: _feat(), tmp_path,
                       apk_path=str(tmp_path / "not-built.apk"))
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/apk", timeout=15)
        assert exc.value.code == 404
        body = exc.value.read().decode("utf-8")
        assert "build_apk" in body, "应提示如何构建：%s" % body[:200]
    finally:
        srv.shutdown()


def test_apk_route_does_not_run_pipeline(tmp_path):
    """**守卫**：下载 APK 不该触发 pipeline —— 那是纯浪费（还要跑几秒）。"""
    calls = []
    apk = _fake_apk(tmp_path)

    def fake():
        calls.append(1)
        return _feat()

    srv, base = _serve(fake, tmp_path, apk_path=apk)
    try:
        urllib.request.urlopen(base + "/apk", timeout=15).read()
        assert calls == [], "下载 APK 不应重新计算仪表盘"
    finally:
        srv.shutdown()


def test_dashboard_still_works_alongside_apk(tmp_path):
    """加了 /apk 路由后，`/` 必须照常工作（不能互相影响）。"""
    apk = _fake_apk(tmp_path)
    srv, base = _serve(lambda: _feat(), tmp_path, apk_path=apk)
    try:
        status, body = _get(base + "/")
        assert status == 200 and "<!DOCTYPE html" in body
    finally:
        srv.shutdown()


# ================================================================ 添加到主屏幕（PWA）
# 公司传输限制拦的是**文件大小**（实测阈值 (5.7 KB, 100 KB]），3.87 MB 的 APK
# 要切成 80 片以上才可能传出去 —— 不现实。
# ⇒ 让仪表盘本身可「添加到主屏幕」：**零传输、零安装**就有独立图标。

def test_manifest_served_as_valid_json(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        with urllib.request.urlopen(base + "/manifest.json", timeout=15) as r:
            assert r.status == 200
            assert "manifest" in r.headers["Content-Type"]
            m = json.loads(r.read().decode("utf-8"))
        assert m["name"] and m["short_name"], "主屏图标要有名字"
        assert m["display"] == "standalone", "要独立窗口（而非浏览器标签页）"
        assert m["start_url"] == "/" and m["scope"] == "/"
        assert {i["src"] for i in m["icons"]} == {"/icon-192.png", "/icon-512.png"}
    finally:
        srv.shutdown()


@pytest.mark.parametrize("size", [192, 512])
def test_icon_served_as_real_png(tmp_path, size):
    """图标必须是**真的 PNG** —— 否则 Chrome 不会用来做主屏图标。"""
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        with urllib.request.urlopen(base + "/icon-%d.png" % size, timeout=30) as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "image/png"
            body = r.read()
    finally:
        srv.shutdown()

    assert body[:8] == b"\x89PNG\r\n\x1a\n", "PNG 签名不对"
    w, h = struct.unpack(">II", body[16:24])          # IHDR 里的宽高
    assert (w, h) == (size, size)
    assert b"IEND" in body[-12:], "PNG 未正常收尾"


def test_icon_bytes_are_cached(tmp_path):
    """图标是固定内容，必须缓存 —— 纯 Python 画 512×512 要 1.8 秒。"""
    assert pwa.icon_png(192) is pwa.icon_png(192)
    assert pwa.icon_png(192) != pwa.icon_png(512)


def test_unknown_icon_size_is_404(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/icon-64.png")
        assert exc.value.code == 404
    finally:
        srv.shutdown()


def test_pwa_routes_do_not_run_pipeline(tmp_path):
    """**守卫**：取 manifest / 图标不该重算仪表盘 —— 它们与数据无关。"""
    calls = []

    def fake():
        calls.append(1)
        return _feat()

    srv, base = _serve(fake, tmp_path)
    try:
        _get(base + "/manifest.json")
        # 图标是二进制，不能走 _get（它按 UTF-8 解码）
        urllib.request.urlopen(base + "/icon-192.png", timeout=30).read()
        assert calls == [], "PWA 静态资源不应触发 pipeline"
    finally:
        srv.shutdown()


def test_dashboard_html_links_manifest(tmp_path):
    """**核心**：仪表盘 HTML 必须带上 manifest 链接，否则「添加到主屏幕」没有图标。

    `report.render_html` 是**离线落盘**和**在线服务**共用的入口，
    两条路径都要带上这些标签。
    """
    html = report.render_html(_feat(), prices_path=str(tmp_path / "no_prices.csv"))
    assert 'rel="manifest"' in html
    assert 'href="/manifest.json"' in html
    assert 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html, "iOS 用 apple-touch-icon"


def test_manifest_icon_paths_match_served_routes(tmp_path):
    """**守卫**：manifest 里写的图标路径必须**真的能取到** —— 写错了只有手机上才发现。"""
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        m = json.loads(_get(base + "/manifest.json")[1])
        for icon in m["icons"]:
            with urllib.request.urlopen(base + icon["src"], timeout=30) as r:
                assert r.status == 200, "%s 取不到" % icon["src"]
                assert r.read()[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        srv.shutdown()


# ================================================================ 手机该访问哪个地址
# 「手机上怎么访问」是启动服务后**第一个**会卡住的问题：一台机器常有 Wi-Fi /
# 有线 / VPN 多个网卡，**只猜一个很容易猜错** —— 故列出候选让用户换着试。

def test_is_usable_filters_loopback_and_link_local():
    assert server._is_usable("192.168.1.10")
    assert server._is_usable("10.0.0.5")
    assert not server._is_usable("127.0.0.1"), "回环地址手机访问不到"
    assert not server._is_usable("169.254.13.7"), "169.254 是链路本地，通常没连上网"


def test_lan_addresses_never_returns_loopback():
    primary, others = server.lan_addresses()
    assert primary is None or server._is_usable(primary)
    for ip in others:
        assert server._is_usable(ip)
        assert ip != primary, "候选里不该重复出现 primary"


def test_bonjour_name_only_on_macos(monkeypatch):
    monkeypatch.setattr(server.sys, "platform", "win32")
    assert server.bonjour_name() is None, "Windows 没 Bonjour，不该瞎给地址"


def test_bonjour_name_appends_local(monkeypatch):
    """macOS 上 `<主机名>.local` 经 Bonjour 可直接解析 —— **换 IP 也能用**。"""
    monkeypatch.setattr(server.sys, "platform", "darwin")
    monkeypatch.setattr(server.socket, "gethostname", lambda: "MacBook-Pro")
    assert server.bonjour_name() == "MacBook-Pro.local"

    monkeypatch.setattr(server.socket, "gethostname", lambda: "MacBook-Pro.local")
    assert server.bonjour_name() == "MacBook-Pro.local", "别重复加 .local"


# ================================================================ 鉴权
# 页面里有**用户的持仓指令**，而服务默认无鉴权 —— 一旦要远程访问，
# 必须再加一道门（纵深防御：即使隧道那层出了岔子，还有这道）。

def _req(url, user=None, password=None):
    """发请求，返回 `(status, body_bytes)`；给了 `user` 就带 Basic 头。"""
    req = urllib.request.Request(url)
    if user is not None:
        token = base64.b64encode(
            ("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_no_auth_by_default(tmp_path):
    """不设密码时保持开放 —— 局域网日常使用不该被拦。"""
    srv, base = _serve(lambda: _feat(), tmp_path)
    try:
        assert _req(base + "/")[0] == 200
    finally:
        srv.shutdown()


def test_auth_required_when_configured(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path, auth=("fg", "s3cret"))
    try:
        status, body = _req(base + "/")
        assert status == 401
        assert b"<!DOCTYPE" not in body, "401 不得回显任何仪表盘内容"
    finally:
        srv.shutdown()


def test_auth_challenge_header_present(tmp_path):
    """必须有 `WWW-Authenticate`，否则浏览器不会弹账号密码框。"""
    srv, base = _serve(lambda: _feat(), tmp_path, auth=("fg", "s3cret"))
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/", timeout=15)
        assert exc.value.headers["WWW-Authenticate"].startswith("Basic ")
    finally:
        srv.shutdown()


@pytest.mark.parametrize("user,password", [
    ("fg", "wrong"),        # 密码错
    ("nobody", "s3cret"),   # 用户错
    ("fg", ""),             # 空密码
])
def test_wrong_credentials_rejected(tmp_path, user, password):
    srv, base = _serve(lambda: _feat(), tmp_path, auth=("fg", "s3cret"))
    try:
        assert _req(base + "/", user, password)[0] == 401
    finally:
        srv.shutdown()


def test_correct_credentials_accepted(tmp_path):
    srv, base = _serve(lambda: _feat(), tmp_path, auth=("fg", "s3cret"))
    try:
        status, body = _req(base + "/", "fg", "s3cret")
        assert status == 200
        assert b"<!DOCTYPE html" in body
    finally:
        srv.shutdown()


@pytest.mark.parametrize("path", ["/manifest.json", "/icon-192.png", "/apk"])
def test_auth_covers_every_route(tmp_path, path):
    """**守卫**：鉴权必须在**所有**路由之前 —— 漏一条就等于开了个后门。"""
    apk = _fake_apk(tmp_path)
    srv, base = _serve(lambda: _feat(), tmp_path, apk_path=apk,
                       auth=("fg", "s3cret"))
    try:
        assert _req(base + path)[0] == 401, "%s 绕过了鉴权" % path
    finally:
        srv.shutdown()


def test_auth_does_not_run_pipeline_when_rejected(tmp_path):
    """未通过鉴权时**不该**重算仪表盘 —— 既浪费，也可能成为 DoS 入口。"""
    calls = []

    def fake():
        calls.append(1)
        return _feat()

    srv, base = _serve(fake, tmp_path, auth=("fg", "s3cret"))
    try:
        _req(base + "/")
        assert calls == []
    finally:
        srv.shutdown()


def test_parse_auth_validation():
    assert server.parse_auth("") is None
    assert server.parse_auth("fg:pw") == ("fg", "pw")
    assert server.parse_auth("fg:a:b") == ("fg", "a:b"), "密码里可以有冒号"
    for bad in ("nocolon", ":pw", "user:"):
        with pytest.raises(ValueError):
            server.parse_auth(bad)


def test_check_basic_auth_rejects_malformed():
    assert not server.check_basic_auth(None, "fg", "pw")
    assert not server.check_basic_auth("Bearer xxx", "fg", "pw")
    assert not server.check_basic_auth("Basic !!!not-base64!!!", "fg", "pw")
    nocolon = "Basic " + base64.b64encode(b"nocolon").decode("ascii")
    assert not server.check_basic_auth(nocolon, "fg", "pw"), "缺冒号要拒"
    ok = "Basic " + base64.b64encode(b"fg:pw").decode("ascii")
    assert server.check_basic_auth(ok, "fg", "pw")


# ================================================================ Human 3.0 打卡端点

def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8")


def test_human30_post_writes_and_returns_aggregate(tmp_path, monkeypatch):
    from fg_system import human30
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "human30.json"))
    srv, base = _serve(lambda: _features(10), tmp_path)
    try:
        st, body = _post(base + "/api/human30",
                         {"mind": 70, "body": 55, "spirit": 60, "vocation": 50, "note": "测试"})
        assert st == 200
        data = json.loads(body)
        assert data["record"]["mind"] == 70
        assert data["aggregate"]["level"] == 2
        # 当日重复打卡 → 覆盖当日（记录数不变）
        _post(base + "/api/human30",
              {"mind": 80, "body": 60, "spirit": 65, "vocation": 55, "note": "覆盖"})
        recs = human30.history(10)
        assert len(recs) == 1
        assert recs[0]["mind"] == 80
    finally:
        srv.server_close()


def test_human30_post_rejects_bad_values(tmp_path):
    srv, base = _serve(lambda: _features(10), tmp_path)
    try:
        for bad in ({"mind": 101, "body": 1, "spirit": 1, "vocation": 1},
                    {"mind": "abc", "body": 1, "spirit": 1, "vocation": 1},
                    {"mind": -5, "body": 1, "spirit": 1, "vocation": 1},
                    {"body": 1, "spirit": 1, "vocation": 1}):   # 缺 mind
            try:
                st, _ = _post(base + "/api/human30", bad)
                assert st == 400, "非法参数应 400: %s" % bad
            except urllib.error.HTTPError as e:
                assert e.code == 400
    finally:
        srv.server_close()


def test_human30_answers_payload_writes(tmp_path, monkeypatch):
    """问答打卡：POST answers(1-5) → 服务端确定性映射 → 写入记录。"""
    from fg_system import human30
    monkeypatch.setattr(human30, "DATA_PATH", str(tmp_path / "human30.json"))
    srv, base = _serve(lambda: _features(10), tmp_path)
    try:
        st, body = _post(base + "/api/human30",
                         {"answers": {"mind": 2, "body": 3, "spirit": 4, "vocation": 5}})
        assert st == 200
        data = json.loads(body)
        assert data["record"]["mind"] == 40
        assert data["record"]["vocation"] == 100
        assert data["aggregate"]["avg"] == 70.0
    finally:
        srv.server_close()


def test_human30_answers_invalid_400(tmp_path):
    srv, base = _serve(lambda: _features(10), tmp_path)
    try:
        for bad in ({"mind": 9, "body": 3, "spirit": 3, "vocation": 3},
                    {"mind": 0, "body": 3, "spirit": 3, "vocation": 3},
                    {"mind": "x", "body": 3, "spirit": 3, "vocation": 3},
                    {"mind": 3, "spirit": 3, "vocation": 3}):   # 缺 body
            try:
                st, _ = _post(base + "/api/human30", {"answers": bad})
                assert st == 400, "非法 answers 应 400: %s" % bad
            except urllib.error.HTTPError as e:
                assert e.code == 400
    finally:
        srv.server_close()
