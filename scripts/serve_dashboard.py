# -*- coding: utf-8 -*-
"""启动仪表盘只读服务（**手机浏览器访问用**）。

用法：
    python scripts/serve_dashboard.py                     # 0.0.0.0:8000
    python scripts/serve_dashboard.py --port 8080
    python scripts/serve_dashboard.py --host 127.0.0.1    # 只允许本机
    python scripts/serve_dashboard.py --password fg:xxx   # 要求登录

启动后用**手机浏览器**打开打印出来的地址即可。**每次打开/刷新都会重新
计算**（纯读 CSV，不抓取、不写盘）—— 手机侧不需要装任何东西，也不需要后台常驻。

【远程访问（不在家时）—— 先读这段】
页面里有**你的持仓指令**，而本服务**默认无鉴权**。所以：

1. **不要**把 8000 端口直接映射到公网。家宽多半没有公网 IPv4（运营商 CGNAT），
   映射也未必通；就算通，等于把仓位公开。
2. 正解是**先建一条加密隧道**（Tailscale / 蒲公英 / 路由器 IPSec 等），
   让你「人在外面，但网络身份在家里的局域网」—— 再访问内网地址。
   详见 `docs/remote-access.md`。
3. 无论走哪条路，都建议加 `--password`（**纵深防御**）：
   万一隧道那层出了岔子，还有一道门。

【手机上怎么访问 —— 三件事】
1. 手机与 Mac 连**同一个 Wi-Fi**（不能用访客网络或手机流量）
2. Mac 上跑本脚本，**把打印出来的地址抄到手机浏览器地址栏**
   （一台机器可能有多个网卡，所以会列几个候选，打不开就换一个试）
3. 想变成独立图标：Chrome 菜单 →「添加到主屏幕」—— **不需要 APK**

【⚠️ 安全】服务**无鉴权**，只在**可信局域网**内使用；不要在公网暴露。
（本服务只读、不改任何数据，但会暴露你的持仓指令。）

【⚠️ 不会抓取数据】见 fg_system/dashboard/server.py 的模块 docstring：
每次刷新都抓会覆盖当天 06:30 的快照，且消耗额度。

【⚠️ 开发注意】本服务由 launchd 常驻（com.xingguo.fg-dashboard，端口 8000）。
**改 dashboard 代码后必须重启服务才生效**（Python 进程不热加载）：
    launchctl kickstart -k "gui/$(id -u)/com.xingguo.fg-dashboard"
详见 docs/dashboard-ops.md。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402
from fg_system.dashboard import server           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0",
                    help="默认 0.0.0.0（允许局域网访问）；127.0.0.1 则仅本机")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--password", default=os.environ.get("FG_DASHBOARD_PASSWORD", ""),
                    metavar="用户:密码",
                    help="要求登录（HTTP Basic）。**远程访问必须设**；"
                         "也可用环境变量 FG_DASHBOARD_PASSWORD")
    args = ap.parse_args()

    try:
        auth = server.parse_auth(args.password)
    except ValueError as exc:
        ap.error(str(exc))

    srv = server.make_server(host=args.host, port=args.port, auth=auth)

    lan_only = args.host == "0.0.0.0"
    primary, others = server.lan_addresses() if lan_only else (None, [])
    port = args.port

    print("仪表盘服务已启动（只读）。Ctrl-C 停止。")
    print()
    if auth:
        print("   已开启登录校验（用户：%s）。" % auth[0])
    elif lan_only:
        print("   ⚠️ **无密码** —— 同一局域网内任何人都能打开，页面含你的持仓指令。")
        print("      只在可信 Wi-Fi 用；要远程访问请加 --password 用户:密码")
    print()

    if lan_only and primary:
        bar = "=" * 56
        print("  " + bar)
        print("   手机浏览器打开这个：")
        print()
        print("       http://%s:%d/" % (primary, port))
        print()
        print("  " + bar)
        print()
        print("   然后：Chrome 菜单 →「添加到主屏幕」→ 主屏出现「贪恐指数」图标。")
        print("        **不需要 APK、不需要装任何东西。**")
        print()

        # 一台机器常有 Wi-Fi / 有线 / VPN 多个网卡，**只猜一个很容易猜错**
        cands = [(ip, "备用网卡") for ip in others]
        bonjour = server.bonjour_name()
        if bonjour:
            cands.append((bonjour, "Bonjour，换 IP 也能用"))
        if cands:
            print("   上面那个打不开？换着试：")
            for host, why in cands:
                print("       http://%-28s %s" % (host + ":%d/" % port, why))
            print("       http://%-28s %s" % ("127.0.0.1:%d/" % port, "本机自测"))
        else:
            print("   （本机只有这一张网卡）")
    elif lan_only:
        print("   ⚠️ 没找到局域网 IP —— 手机多半连不上。")
        print("      检查：Mac 是不是没连 Wi-Fi / 网线？或只连了 VPN？")
    else:
        print("   仅本机： http://127.0.0.1:%d/" % port)
        print("   （--host 127.0.0.1 只允许本机；想让手机访问就去掉这个参数）")

    if os.path.isfile(config.APK_PATH):
        print()
        print("   APK：   http://%s:%d/apk"
              % (primary or "127.0.0.1", port))

    print()
    print("   手机连不上？按顺序查：")
    print("     1. 手机与 Mac 在【同一个 Wi-Fi】？（别用访客网络 / 手机流量）")
    print("     2. Mac 防火墙：设置 → 网络 → 防火墙 → 选项 → 允许 Python 接入")
    print("     3. 地址要输在浏览器**地址栏**，别输进搜索框")
    print()
    print("   每次打开/刷新都会重新计算（纯读，不抓取、不写盘）。")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
