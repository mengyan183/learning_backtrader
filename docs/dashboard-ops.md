# 贪恐仪表盘（Dashboard）开发与运维

> 面向在本地 Mac 上开发/维护 `fg_system/dashboard` 的开发者。
> 本服务是**只读**的：每次请求实时用 CSV 重算，不抓取、不写盘（`pipeline.run(write=False)`）。

## 一、入口与服务形态

| 项 | 值 |
|---|---|
| 入口脚本 | `scripts/serve_dashboard.py` |
| 渲染实现 | `fg_system/dashboard/report.py`（HTML 字符串）+ `server.py`（HTTP）+ `templates/index.html` + `static/style.css` |
| 正式端口 | **8000**（开机自启 launchd：`com.xingguo.fg-dashboard`） |
| 访问（Mac 本机） | `http://127.0.0.1:8000/`（用户名 `fg`，密码见 launchd plist 的 `FG_DASHBOARD_PASSWORD`） |
| 访问（手机 Tailscale） | `http://<Tailscale-IP>:8000/` |

## 二、⚠️ 改代码后必须重启服务（Python 进程不热加载）

常驻进程启动后，Python 代码已加载进内存——**改任何 dashboard 代码（report.py / server.py / 模板 / CSS）后不重启，线上仍跑旧版本**。

```bash
# 重启开机自启服务（加载新代码）
launchctl kickstart -k "gui/$(id -u)/com.xingguo.fg-dashboard"

# 验证新代码已生效：抓页面确认关键字段
curl -s -u "fg:fg682b6ba067" http://127.0.0.1:8000/ | grep "守猪待兔" | head
```

判断"是不是旧代码"的快捷方法：看页面是否含最新改动特征（例如档位标签改版后的文案）。

## 三、临时起服务（调试用，不碰正式实例）

```bash
cd /Users/xingguo/learning_backtrader
PYTHONPATH=. .venv/bin/python scripts/serve_dashboard.py --host 127.0.0.1 --port 8125   # 仅本机，无密码
```

- 调试完**必须 kill 掉临时实例**，避免多个实例端口混淆（正式入口永远是 8000）。
- 若用 `--host 0.0.0.0 --port 8000` 手动起，会与 launchd 实例抢端口；正式环境一律走 launchd。

## 四、数据口径速查（持仓卡）

- 持仓/净值：`Data/positions.csv`、`Data/accounts.csv` 最新日期行（`sync_positions.py` 产出，只读快照）。
- 系统列：个股系统指数（路径 B，0-100 五档）；底层数据不足回退市场指数。
- 守猪待兔列：官方原始系数 **-100~100 + 官方三档**（恐慌 ≤-60 / 中性 / 贪婪 ≥60），见 `docs/shoutu-zones.md`。
- 覆盖三态：`✅ 系统覆盖`（系统信号指令）/ `🐰 守猪待兔覆盖`（守猪待兔系数）/ `❌ 范围外`。

## 五、相关

- 远程访问安全说明见 `scripts/serve_dashboard.py` docstring（先建加密隧道，再加密码）。
- 历史变更：CHANGELOG.md（如持仓卡三态修复、守猪待兔官方口径显示）。
