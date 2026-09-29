# -*- coding: utf-8 -*-
"""让仪表盘可「添加到主屏幕」—— **彻底绕开 APK 传输问题**。

【为什么需要这个（2026-09-23）】
用户想在手机上「以独立图标打开仪表盘」，为此做了 Android APK。
但**公司传输限制拦的是文件大小**，实测阈值落在 **(5.7 KB, 100 KB]**：

    fg-src-kit.zip      5.7 KB   ✅ 通过
    probe-100k.bin      100 KB   ❌ 上传失败
    app-debug.apk       3.9 MB   ❌
    a.tar.gz            3.5 MB   ❌
    app-debug.json      3.9 MB   ❌（已改名，仍被拦）

⇒ 3.87 MB 的 APK 要切成 **80 片以上**才可能传出去，不现实。

【PWA 方案 —— 零传输、零安装】
Mac 上跑的服务本来就能被手机访问（同一 Wi-Fi）。只要给页面加上
**Web App Manifest**，安卓 Chrome 的「添加到主屏幕」就会生成一个**独立图标**：

    手机 Chrome 打开 http://<mac>:8000/
      → 菜单 →「添加到主屏幕」
      → 主屏出现「贪恐指数」图标 → 点开即仪表盘

⇒ **不需要 APK、不需要构建、不需要传文件、不需要装任何东西。**

【⚠️ 关于 `display: standalone`】
`standalone`（无地址栏，看起来跟原生 App 一样）在 Chrome 上**需要 HTTPS**
才会升级成 WebAPK。本服务是局域网 `http://`，Chrome 通常**只生成普通快捷方式**
（点开仍在 Chrome 里，**带地址栏**）。

⇒ 图标、一键直达都有；**只是多一条地址栏**。若这不可接受，再走 APK（Mac 上构建，
见 `mobile/BUILD-ON-MAC.md`）。manifest 里仍然写 `standalone` ——
将来若换成 HTTPS（或 Chrome 放宽），**无需改代码**即自动升级。

【为什么图标是**手绘 PNG** 而不是放个图片文件】
本模块零依赖（只用标准库 `zlib`/`struct` 手工编码 PNG），
避免为了一个图标往 `requirements.txt` 里加 Pillow。
"""
import json
import struct
import zlib

# --------------------------------------------------------------------------- 配色
BG = (0x1B, 0x22, 0x33)          # 深蓝底
BARS = [(0x22, 0xC5, 0x5E),      # 绿 —— 贪婪
        (0xEA, 0xB3, 0x08),      # 琥珀 —— 中性
        (0xEF, 0x44, 0x44)]      # 红 —— 恐惧

MANIFEST = {
    "name": "贪婪恐惧指数仪表盘",
    "short_name": "贪恐指数",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#fafafa",
    "theme_color": "#1b2233",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

# 注入 `<head>` 的标签 —— 由 report.render_html 使用
HEAD_TAGS = (
    '<meta name="theme-color" content="#1b2233">\n'
    '<meta name="mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-title" content="贪恐指数">\n'
    '<link rel="manifest" href="/manifest.json">\n'
    '<link rel="apple-touch-icon" href="/icon-192.png">\n'
    '<link rel="icon" href="/icon-192.png">\n'
)


def manifest_json():
    """Manifest 的 JSON 字节（UTF-8，不转义中文）。"""
    return json.dumps(MANIFEST, ensure_ascii=False, indent=2).encode("utf-8")


# --------------------------------------------------------------------------- PNG
def _chunk(tag, data):
    body = tag + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def _encode_png(width, height, pixels):
    """`pixels` 是 `width*height` 个 `(r,g,b,a)` 元组（逐行）。"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)                                   # filter type 0 (None)
        for x in range(width):
            raw.extend(pixels[y * width + x])
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def _in_rounded_rect(x, y, w, h, r):
    """点 (x, y) 是否落在圆角矩形内（圆角用四分之一圆判定）。"""
    if not (0 <= x < w and 0 <= y < h):
        return False
    cx = min(max(x, r), w - 1 - r)                      # 最近的圆角圆心
    cy = min(max(y, r), h - 1 - r)
    if x == cx or y == cy:                              # 不在圆角区域
        return True
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _blend(dst, src, alpha):
    """把 `src` 按 `alpha`(0~1) 叠加到 `dst` 上。"""
    return tuple(int(d + (s - d) * alpha) for d, s in zip(dst, src))


def _render(size, ss=2):
    """渲染图标。`ss` 为超采样倍数（抗锯齿）。"""
    n = size * ss
    radius = int(n * 0.22)
    pad = int(n * 0.16)                                  # 内边距
    plot_h = n - 2 * pad
    bar_w = int((n - 2 * pad) * 0.20)
    gap = int((n - 2 * pad - 3 * bar_w) / 2)
    base_y = n - pad
    heights = [int(plot_h * f) for f in (0.46, 0.70, 1.00)]

    canvas = []
    for y in range(n):
        for x in range(n):
            # 1) 圆角底
            if _in_rounded_rect(x, y, n, n, radius):
                px = BG
            else:
                canvas.append((0, 0, 0, 0))
                continue
            # 2) 三根柱子（顶部圆角）
            for i in range(3):
                bx = pad + i * (bar_w + gap)
                by = base_y - heights[i]
                if bx <= x < bx + bar_w and by <= y < base_y:
                    r = min(bar_w // 2, int(heights[i] * 0.5))
                    top = _in_rounded_rect(x - bx, y - by, bar_w, heights[i], r)
                    if top:
                        px = BARS[i]
            canvas.append(px + (255,))

    # 3) 超采样降采样 —— 得到抗锯齿边缘
    out = []
    for y in range(size):
        for x in range(size):
            acc = [0, 0, 0, 0]
            for dy in range(ss):
                for dx in range(ss):
                    p = canvas[(y * ss + dy) * n + (x * ss + dx)]
                    for k in range(4):
                        acc[k] += p[k]
            cnt = ss * ss
            out.append(tuple(v // cnt for v in acc))
    return out


_CACHE = {}


def icon_png(size):
    """返回 `size×size` 的 PNG 字节（带缓存）。"""
    if size not in _CACHE:
        _CACHE[size] = _encode_png(size, size, _render(size))
    return _CACHE[size]
