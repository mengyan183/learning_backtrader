# 变更记录（CHANGELOG）

> **用途**：跨设备开发时快速了解关键变更。在公司电脑 `git pull` 后，打开本文件即可看到最新演进；完整明细用 `git log --oneline` / `git show <hash>`。
>
> **约定**：按日期倒序；每条含 commit hash、变更内容、涉及文件、验证方式；被后续提交取代的变更标注「已取代」。

## 2026-10-02 — Dashboard 内容与 UI 升级（12 个 commit，最新在顶部）

### 7e7daa5 — 路径 B：个股系统指数（当前 HEAD）
- **新增** `fg_system/factors/symbol.py`：个股系统贪恐指数（0-100，高分=贪婪）
  - 三因子合成（先验权重，禁止优化）：60 日动量 ×0.5 + 20 日动量 ×0.3 + 20 日年化波动率（反向）×0.2
  - 每个因子按 `RANK_WINDOW`（756 日）滚动分位映射到 0-100
  - **硬约束（§4.5 约束 1）**：输入必须为无杠杆底层，禁用杠杆 ETF 自身价格；映射复用 config 权威表（`SIGNAL_UNDERLYING_MAP` / `CRYPTO_UNDERLYING` / `GDXU_UNDERLYING_BLEND`）
  - 回退链：底层历史 <816 日或无底层 → 返回 None，调用方回退市场级 fg_index
- **接入** `fg_system/dashboard/report.py`：持仓卡「系统」列 = 个股系统指数（最新日），与守猪待兔个股系数形成**两套独立计算**对比
- 实测：YINN 53（FXI）、GDXU 35（GDX+GDXJ）、AXTX 58（AXTI）、BTC 73（现货 BTC）；CRCG（CRCL 仅 331 日）与 CONL（COIN 无数据）回退市场 55
- 验证：本地渲染 1.0s；线上 8000 端口重启验证；浏览器实拍持仓页 6 卡双系数正常

### 77bd28c — 持仓卡系统列改为市场级真实 fg 指数
- 系统是市场级模型（四因子合成），系统列展示系统真实输出 fg（55.1 中性），与守猪待兔个股系数形成可验证对比
- 说明文字同步注明口径（随后被 7e7daa5 的个股指数取代）

### 58dee13 — 持仓卡标的级双系统贪恐系数（定稿方向）
- 每张持仓卡展示该标的双系数：「系统」+「守猪待兔」（此前整页市场级双系数条 92ea977 被移除）
- BTC-USDT 键名兼容（positions 用 BTC-USDT，pipeline 用 BTC）

### 92ea977 — 持仓页顶部双系统贪恐系数条（**已取代**）
- 整页市场级双系数条，后被 58dee13 改为持仓卡内标的级展示并移除

### d20febf — 市场页双系数 + 持仓成本/现价
- 市场页 hero 双系数并排：当前系统 fg（55.1 中性）+ 守猪待兔市场温度（36.6 恐惧，全标的均值转刻度）
- 持仓卡新增「成本 X · 现价 Y」+ 市值/占净值/数量行

### f78d989 — shadcn 式设计 token 体系（样式定稿基线）
- `static/style.css` 引入五层设计 token（`--bg/--surface/--border/--fg/--accent/--up/--down/--radius/--shadow-card/--font-num` 等）
- 组件质感：卡片悬浮阴影、h2 左侧色条、表格 hover、持仓/因子卡按压缩放、tab 选中蓝绿渐变指示条、数字等宽字体

### 903cb56 — 样式拆分为独立 `static/style.css`
- 模板只保留结构与脚本，`<link>` 引用静态样式

### 1a76503 — http.server 迁移至 Flask + Jinja2（重要架构变更）
- `server.py` 重写为 Flask app：Basic Auth 全路由拦截、`/manifest.json`、`/icon-<int>.png`、`/apk`、`/static/<path>`（带路径穿越防护）
- `werkzeug.serving.make_server` 保持 `serve_forever`/`server_address` 接口兼容（LaunchAgent 启动命令不变）
- 模板独立文件 `templates/index.html`（Jinja2，不再需要 Python `%%` 转义）
- 35 项 pytest 全绿

### 75c82bc — 引入 Apache ECharts 5.5.1（本地离线）
- `static/echarts.min.js`（1,030,855B，npmmirror 下载）
- 指数曲线（档位带 markArea）、目标仓位面积图、四因子迷你趋势全部专业图表化

### 5a49d0f — 借鉴守猪逮兔官网 UI
- 底部三 Tab 导航（市场/持仓/系统）、市场温度刻度条（temp-track/fill/dot/ticks）、大数字状态卡

### ce02c25 — UI 再美化
- 四因子卡片化（迷你图+当前值）、目标仓位进度条、净值对比横向柱、持仓卡展示守猪待兔系数与信号

### 58f7e88 — 界面现代化改造（本轮起点）
- 深色金融仪表盘主题、区块卡片化、持仓卡片网格（移动端响应式）

---

## 关键背景文档
- `docs/evolution-plan.md`：贪恐系统自我进化方案（需求/验证顺序/下一步建议）
- `fg_system/dashboard/`：report.py（HTML 渲染）+ templates/index.html（Jinja2）+ static/（style.css / echarts.min.js）
- 数据文件：`Data/features.csv`（fg_index 等）、`Data/positions.csv`（实盘持仓快照）、`Data/raw/prices.csv`（个股日线，2016-09 起）、`Data/raw/crypto_underlying.csv`（BTC 现货，2016-10 起）、`Data/raw/shoutu_fng.csv`（守猪待兔标的系数）

## 运行与验证速查
```bash
# 重启 dashboard（LaunchAgent 已配置开机自启）
launchctl kickstart -k gui/$(id -u)/com.xingguo.fg-dashboard

# 线上抓取验证（Basic Auth，凭据见 LaunchAgent 环境变量 FG_DASHBOARD_PASSWORD）
curl -s -m 20 -u "fg:<密码见 ~/Library/LaunchAgents/com.xingguo.fg-dashboard.plist>" http://127.0.0.1:8000/ -o /tmp/dash_live.html

# 本地渲染验证
PYTHONPATH=. .venv/bin/python -c "
from fg_system.dashboard import report; import pandas as pd
f = pd.read_csv('Data/features.csv', parse_dates=['date']).set_index('date')
open('/tmp/dash.html','w').write(report.render_html(f))"
```

## 2026-10-02（进化闭环⑤收尾）
- `Data/raw/prices.csv`：补录 COIN 日线 1254 行（Yahoo Finance，2021-10-04→2026-10-01，代理下载，已去重）→ 解锁 CONL 个股系统指数（55.5，不再回退市场）与 H-003 的 CONL 波动项
- `evolution/LESSONS.md`：归档 L-001（杠杆波动放大，H-003 adopted）/L-002（信号回落期浮亏扩大，H-004 adopted）/L-003（数据源缺口污染验证结论）
- `evolution/baseline.json`：骨架（回测恢复后由 evolve_baseline.py 填充）
- `tests/factors/test_symbol.py`：新增 CONL 有底层用例（11 passed）
- `scripts/evolve_verify.py`：H-003 支持 CONL 以 2×COIN 近似

- `Data/raw/prices.csv`：补录 CONL 真实行情 690 行（FutuOpenD US.CONL 前复权，2024-01-02→2026-10-01，权威源，与持仓同源富途；与守猪待兔 shoutu_history 交叉验证量级一致）→ H-003 的 CONL 项升级为真实波动 5.82%（替代 2×COIN 近似 2.8%）；CONL 个股系统指数仍用底层 COIN（路径 B 设计不变）
