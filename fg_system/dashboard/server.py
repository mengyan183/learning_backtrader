# -*- coding: utf-8 -*-
"""仪表盘只读 HTTP 服务（手机访问用）。

【需求（用户，2026-09-23）】支持在**手机上打开**，**每次打开/刷新时主动重新计算**，
**不需要手机后台常驻**。

⇒ 架构：Mac 上起一个只读 HTTP 服务；**每次请求**重跑 pipeline 并渲染 HTML；
手机浏览器打开/刷新即得最新状态。**手机侧不装任何东西、不跑后台进程。**

【为什么用标准库 `http.server` 而不是 Flask】
本服务只做「GET / → 渲染 HTML」，没有路由 / 模板 / 中间件需求。
引入 Flask 会给 `requirements.txt` 加一个**生产依赖**，收益为零。

【⚠️ 本服务**绝不**抓取守猪待兔】见 `tests/dashboard/test_server.py` 的
`test_server_never_fetches_from_api`。两条理由，任一条都足以禁止：

1. 该指数**实时更新**，而 `append_records` 对同一 `(date, symbol)` 是**覆盖**
   语义 ⇒ **每次刷新都抓 = 每次刷新都污染当天样本**（§14.5 已实际发生过一次）
2. 每次刷新都消耗 `query_api` 额度（5000/月）

⇒ 仪表盘只做**纯计算**（读已有 CSV）；抓取由 06:30 的定时任务**独占**。

【⚠️ 安全 —— 页面里有**持仓指令**】
本服务**默认无鉴权**（只适合可信局域网）。一旦要**远程访问**：

1. **不要**把 8000 端口直接映射到公网 —— 等于公开你的仓位
2. 先建**加密隧道**（Tailscale / 蒲公英 / 路由器 IPSec），详见 `docs/remote-access.md`
3. 再加 `--password 用户名:密码`（HTTP Basic）做**纵深防御**

   ⚠️ Basic 在**纯 HTTP** 下是**明文**传输，所以它**必须**和隧道（或 HTTPS）
   搭配使用，不能单独扛公网。
"""
import base64
import hmac
import http.server
import os
import re
import socket
import sys

from fg_system import config
from fg_system.dashboard import pwa
from fg_system.dashboard import report

APK_MIME = "application/vnd.android.package-archive"
MANIFEST_MIME = "application/manifest+json"
_ICON_RE = re.compile(r"^/icon-(\d+)\.png$")
_ICON_SIZES = (192, 512)


def render_dashboard(features=None, prices_path=None):
    """渲染一份**新鲜**的仪表盘 HTML（纯计算：不写盘、不改状态、**不抓取**）。"""
    if features is None:
        from fg_system import pipeline
        features = pipeline.run(write=False)     # write=False：只读视图，不落盘
    return report.render_html(features, prices_path=prices_path)


def check_basic_auth(header, user, password):
    """校验 `Authorization: Basic ...`。用 `compare_digest` 防时序侧信道。"""
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip()).decode("utf-8")
    except Exception:
        return False
    got_user, sep, got_pass = raw.partition(":")
    if not sep:
        return False
    return (hmac.compare_digest(got_user, user)
            and hmac.compare_digest(got_pass, password))


def parse_auth(spec):
    """把 `user:pass` 解析成 `(user, pass)`；空/非法返回 None。"""
    if not spec:
        return None
    user, sep, password = spec.partition(":")
    if not sep or not user or not password:
        raise ValueError("密码格式应为 用户名:密码，例如 fg:mysecret")
    return user, password


def make_handler(get_features, prices_path=None, apk_path=None, auth=None):
    """构造请求处理器。

    `get_features()` 在**每次请求**时调用 —— 这正是「打开/刷新即最新」的实现，
    也是用户明确要求的行为（而不是启动时算一次后缓存）。

    路由：
      `GET /`               仪表盘（每次重新计算）
      `GET /manifest.json`  PWA manifest —— 「添加到主屏幕」用
      `GET /icon-N.png`     PWA 图标（N=192/512，**手绘生成，不落盘**）
      `GET /apk`            Android 客户端安装包（**不触发计算**）

    `auth` 为 `(user, password)` 时，**所有路由**都要求 HTTP Basic 认证。
    不设则完全不校验（只适合**可信局域网**）—— 见模块 docstring 的安全说明。
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # 鉴权放在**最前面**：任何路由（含 manifest/图标）都不能绕过，
            # 未通过时**不返回任何仪表盘内容**。
            if auth and not check_basic_auth(
                    self.headers.get("Authorization"), auth[0], auth[1]):
                self._unauthorized()
                return

            path = self.path.split("?")[0]

            # 「添加到主屏幕」——让手机**不需要 APK** 也有独立图标。
            # 静态且不变，故可缓存；**不触发 pipeline**。
            if path == "/manifest.json":
                self._serve_bytes(pwa.manifest_json(), MANIFEST_MIME, cache=True)
                return
            m = _ICON_RE.match(path)
            if m and int(m.group(1)) in _ICON_SIZES:
                self._serve_bytes(pwa.icon_png(int(m.group(1))), "image/png",
                                  cache=True)
                return

            if path == "/apk":
                self._serve_apk()
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
                return
            if path not in ("/", "/index.html"):
                self.send_error(404, "Not Found")
                return
            try:
                html = render_dashboard(get_features(), prices_path=prices_path)
            except Exception as exc:      # 渲染失败不能把服务搞挂
                self._plain(500, "渲染失败：%s: %s" % (type(exc).__name__, exc))
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")   # 刷新必须拿新的
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, rel):
            """提供本地静态资源（echarts.min.js 等）——离线可用、不经第三方。"""
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
            target = os.path.normpath(os.path.join(base, rel))
            if not target.startswith(base) or not os.path.isfile(target):
                self.send_error(404, "Not Found")
                return
            ctype = ("application/javascript" if target.endswith(".js")
                     else "text/plain")
            with open(target, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def _serve_apk(self):
            """分发 APK —— **公司有安全下载限制，APK 传不出公司网络**。

            手机与 Mac 本就要在同一 Wi-Fi，故让 Mac 当分发点：
            手机浏览器打开 `http://<mac>:8000/apk` 即可下载，不经任何第三方。

            **不触发 pipeline**（下载安装包没必要重算仪表盘）。
            """
            p = apk_path or config.APK_PATH
            if not os.path.isfile(p):
                self._plain(404,
                            "APK 尚未构建。\n\n"
                            "在开发机上运行：\n"
                            "    bash mobile/build_apk.sh\n\n"
                            "产物路径：\n"
                            "    %s\n\n"
                            "（本服务只负责分发；构建需要 JDK 21 + Android SDK，"
                            "见 mobile/README.md）" % p)
                return
            with open(p, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", APK_MIME)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition",
                             'attachment; filename="fg-dashboard.apk"')
            self.end_headers()
            self.wfile.write(body)

        def _serve_bytes(self, body, ctype, cache=False):
            """发送一段内存里的内容（manifest / 图标）。"""
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # 内容固定不变：允许浏览器缓存，省掉每次重新生成图标
            self.send_header("Cache-Control",
                             "public, max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _unauthorized(self):
            """401 + `WWW-Authenticate` —— 浏览器据此弹出账号密码框。

            **不回显任何仪表盘内容**（连标题都不给），避免未授权泄露。
            """
            body = "需要登录。\n".encode("utf-8")
            self.send_response(401)
            self.send_header("WWW-Authenticate",
                             'Basic realm="fg-dashboard", charset="UTF-8"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _plain(self, code, text):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            sys.stderr.write("[dashboard] %s %s\n" % (self.address_string(), fmt % args))

    return Handler


def make_server(host="0.0.0.0", port=8000, get_features=None, prices_path=None,
                apk_path=None, auth=None):
    """创建（**未启动**的）HTTP 服务。`port=0` 表示随机端口（测试用）。

    `auth` 为 `(user, password)` 时要求 HTTP Basic 认证，见 `make_handler`。
    """
    if get_features is None:
        def get_features():
            from fg_system import pipeline
            return pipeline.run(write=False)
    return http.server.ThreadingHTTPServer(
        (host, port),
        make_handler(get_features, prices_path=prices_path, apk_path=apk_path,
                     auth=auth))


# ============================================================ 手机该访问哪个地址
# 「手机上怎么访问」是启动服务后**第一个**会卡住的问题。
# 一台机器常有多个网卡（Wi-Fi / 有线 / VPN / Docker），**只猜一个很容易猜错**，
# 所以把候选**都列出来**让用户换着试。

def _is_usable(ip):
    """排除回环与链路本地（169.254.x.x，通常意味着没连上网）。"""
    return not (ip.startswith("127.") or ip.startswith("169.254."))


def _primary_ip():
    """内核选出的默认出口 IP —— 最可能是手机该用的那个。

    连 UDP 8.8.8.8 不会**真的发包**，只是让内核按路由表挑一个源地址。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def _hostname_ips():
    """本机主机名解析出的所有 IPv4（作为补充候选）。"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out


def lan_addresses():
    """返回 `(primary, others)` —— 手机可用的局域网 IP。

    `primary` 最可能对；`others` 是其余候选（换着试）。
    一个都没有时 `primary` 为 None（例如只绑了 127.0.0.1）。
    """
    primary = _primary_ip()
    if primary is not None and not _is_usable(primary):
        primary = None

    others = [ip for ip in _hostname_ips()
              if _is_usable(ip) and ip != primary]
    if primary is None and others:
        primary = others.pop(0)
    return primary, others


def bonjour_name():
    """macOS 上 `<主机名>.local` 经 Bonjour 可直接解析 —— **换 IP 也能用**。

    非 macOS 返回 None（Windows 需要额外装 Bonjour 服务）。
    """
    if sys.platform != "darwin":
        return None
    host = socket.gethostname()
    if not host:
        return None
    return host if host.endswith(".local") else host + ".local"
