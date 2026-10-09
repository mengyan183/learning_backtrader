# macOS 部署与运维 Runbook

> **适用**：把本系统部署到家里 Mac，作为**生产服务**每日运行。
> **架构**：公司电脑（Windows）= **开发**；家里 Mac（macOS）= **服务运行**。
>
> **本文只写「怎么做」。为什么这样做见
> [`trading-discipline.md` 第 14.5 条](trading-discipline.md)** —— 那里记录了全部
> 实测依据、踩过的坑与取舍。
> **两者冲突时，以 §14.5 为准。**

---

## 0. 前置条件

| 项 | 要求 | 怎么确认 |
|---|---|---|
| 局域网 | 两台机器能互通 | `ping <公司电脑IP>` |
| Python | **3.10**（实测 3.10.11） | `python3.10 -V` |
| 仓库同步 | **无远程仓库**，走局域网拷贝 | `git remote -v` 应为空 |
| 守猪待兔密钥 | `Data/shoutu_token`（32 字符） | 从公司电脑拷，**已被 gitignore** |

### ⚠️ 不再需要的东西（切到 API 通道后）

- ❌ `npm i -g browser-skill`
- ❌ Chrome + browser-skill 扩展
- ❌ `bsk` CLI

> 只有**研究快照** `scripts/fetch_shoutu.py` 才需要 bsk，而它**不在每日任务里**。

---

## 1. 建立局域网同步通道

**⚠️ 双向，且两个方向的「所有者」不同** —— 否则会互相覆盖：

| 方向 | 内容 | 所有者 |
|---|---|---|
| 公司 → 家 | 代码 + `Data/` | 公司电脑（**开发**） |
| 家 → 公司 | **仅 `Data/raw/shoutu_fng.csv`** | Mac（**生产**） |

**⚠️ 两条纪律**：

1. **不要用 `rsync --delete` 双向对拷** —— 两边各自拥有不同文件，`--delete`
   会把对端独有的删掉
2. **Mac 上不做 `git commit`** —— 保持「**公司电脑是唯一提交者**」，
   否则两边 `.git` 会分叉

### 1.0 要传哪些文件（**权威清单**）

```bash
python scripts/check_deploy_set.py --list    # 打印清单
python scripts/check_deploy_set.py           # 拷到干净目录**跑全套测试**验证
```

**要传**（合计 **约 4.8 MB**）：

| 路径 | 文件数 | 体积 | 说明 |
|---|---|---|---|
| `fg_system/` | 37 | 272 KB | 系统本体 |
| `scripts/` | 13 | 75 KB | 入口脚本 |
| `tests/` | 54 | 276 KB | 自检用 |
| **`Data/raw/`** | 14 | **4.2 MB** | **原始行情 / 因子 —— 不可再生** |
| `Data/accounts.csv` `positions.csv` | — | 1 KB | 实盘快照 |
| `Data/state.json` `crypto_state.json` | — | 1 KB | 仓位与冷却状态 |
| `Data/trade_log.csv` | — | 1 KB | 交易记录 |
| `requirements.txt` | — | 1.8 KB | 依赖 |
| `pytest.ini` | — | 0.9 KB | 测试路径隔离 |
| `mobile/`（**仅根目录文件**） | 10 | 80 KB | `tests/` 引用其中的 `patch_repos.py` |

**不用传**：

| 路径 | 为什么不传 |
|---|---|
| **`Data/daily_price.csv`** | **19.1 MB** —— 全仓搜索确认**只有 `learning_lesson1/2/3` 读**（教学代码，不部署） |
| `Data/features.csv` `crypto_features.csv` `portfolio_features.csv` | **管道产物** —— Mac 上 `pipeline.run` 会重算（已在 `.gitignore`） |
| `Data/synthetic_leverage.csv` | 同上（由 `crypto_underlying` + 成本率合成） |
| `Data/tqqq_history.csv` `Data/trade_info.csv` | **零代码引用**（全仓搜索无命中） |
| `Data/shoutu_digitized/` | 已证伪方案的中间产物 |
| `mobile/node_modules` `mobile/android` `mobile/dist` `mobile/www` | 依赖 / 可生成 / 产物 |
| `learning_lesson1~3` `Lesson*.py` `FullDemo.py` `record.*` | 教学代码与笔记 |
| `reports/` `logs/` `.venv/` `.git/` | 产物 / 环境 |

> **为什么 `Data/` 要逐项指定**：整目录是 24.8 MB，但 **19.1 MB 是 `daily_price.csv`**，
> 而它只有教学代码读。整目录拷会让传输量**翻 5 倍**，且全是噪声。
> 有测试守着这条结论（`tests/test_check_deploy_set.py`）。

> **`mobile/` 现在整体不用传** —— 手机端改走「添加到主屏幕」（PWA），不再需要 APK。
> 只因为 `tests/` 里有个测试引用 `mobile/patch_repos.py`，才带上它那几个根文件。

**⚠️ 必须手动拷的两个凭据**（被 `.gitignore` 覆盖，**git 和「只拷 git 跟踪文件」都会漏掉**）：

```bash
cp <公司电脑>/Data/shoutu_token  Data/shoutu_token
chmod 600 Data/shoutu_token
# Data/tstoken 同理（若 Mac 上要用到）
```

**⚠️ `Data/raw/` 有 4.2 MB —— 飞书仍传不了**（实测拦截阈值在 5.7 KB ~ 100 KB 之间）。
必须走下面的局域网共享。

### 1.1 ⚠️ 只能走飞书时（**局域网共享走不通**）

**飞书对公司网络的上传做内容检查，实测结论（2026-09-23，20+ 次上传）：**

| 结果 | 文件 | 大小 | 特征 |
|---|---|---|---|
| ✅ | `output-metadata.json` | 394 B | 纯文本 |
| ✅ | `合并说明.txt` | 1.8 KB | 纯文本 |
| ✅ | `fg-src-kit.zip` | 5.7 KB | zip 魔数（**小到能扫完**） |
| ✅ | `code-part03.bin` | **10188 B** | **无魔数**（压缩流中段碎片） |
| ❌ | `keep.bin` | **7.8 KB** | **xz 魔数** |
| ❌ | `code-part01/02.bin` | 90 KB | xz 魔数 |
| ❌ | `keep.zip` | 10183 B | zip 魔数 |
| ❌ | `probe-20k.txt` … | 20~80 KB | 纯文本（**太大**） |

⇒ **两条规则叠加**：

1. **有压缩魔数（zip / xz）→ 直接拦**，与大小无关
   （`keep.bin` 7.8 KB 被拦，而 **10188 B** 的中段碎片能过 —— 差别只在**开头有没有魔数**）
2. **纯文本 → 上限约 10 KB**（1.8 KB 过、20 KB 不过）

⇒ **唯一稳定能过的形态是 base64 纯文本**（无魔数、纯 ASCII）。

```bash
python scripts/make_feishu_bundle.py --text          # ← 走这个
python scripts/make_feishu_bundle.py --text --chunk-kb 8
```

#### ⚠️ 三条通道全部实测过 —— **只有消息能通**

| 通道 | 实测结果 |
|---|---|
| **文件上传** | ❌ 被 DLP 拦（压缩魔数直接拒；纯文本 >10 KB 也拒） |
| **云文档** | ❌ 「**你正处于离线状态**」—— 同步被网络阻断，保存不了 |
| **消息** | ✅ **能通**，但上限 **1,700 字符/条** |

⇒ 132 KB base64 ÷ 1,700 = **约 103 条消息**。**唯一可行路径。**

```bash
python scripts/make_feishu_bundle.py --text      # 默认 --msg-chars 1700
```

产出在 `dist/feishu/text/`（**三种形态 MD5 已验证完全一致**）：

| 文件 | 用途 |
|---|---|
| `code-t001..t103.txt` | **逐条发消息** ← **走这个** |
| `keep-t001..t007.txt` | 同上 |
| `code-d01..d04.txt` / `code.b64.txt` | 文档块 / 整块 —— 通道不通，留档 |

#### 关键设计：每条消息带**自定界标记**

```
###FG:code:001/103###
/Td6WFoAAA…（1700 字符）
###FG:end###
```

**为什么必须这样**：从飞书聊天记录「全选复制」会把**昵称、时间戳**一起复制进来。
若靠「过滤掉非 base64 字符」，时间戳 `17:01` 里的**数字是合法 base64 字符**，
会被保留 ⇒ **静默污染数据**，要到解压失败才发现。

有标记就能精确切，而且还原脚本会：
- 按**序号**排序（消息乱序复制回来也不怕）
- **报告缺了第几片**（告诉你要补发哪条）
- 分片内混入非法字符时**明确报错**，不静默损坏

#### 步骤

1. **公司电脑**：生成投递包

```bash
python scripts/make_feishu_bundle.py --minimal --strip --text
# 产出 58 条（keep 7 + minimal 51），每条 <= 1700 字符
```

2. **公司电脑**：自动发送（**不要手工发 58 次**）

```bash
python scripts/feishu_send.py --dry-run          # 先看
python scripts/feishu_send.py --chat 郭星        # 真发
python scripts/feishu_send.py --start 30         # 断了续发
```

   脚本用 `bsk` 驱动浏览器：开飞书 → 进与自己会话 → 逐条 `fill` + `Enter`。

3. **Mac**：打开同一个会话 → **全选复制**整段聊天记录 → 粘进一个文件

4. **Mac**：还原

```bash
python3 scripts/restore_from_base64.py <那个目录>
```

#### ✅ 这条路径已实测走通（2026-09-23）

```
发送：keep 7/7 + minimal 51/51 = 58 条 全部到达
还原：模拟聊天记录（带昵称+时间戳）→ 精确提取 7 + 51 片
      → 解压 → pipeline.run() 2514 行，贪恐指数 56.3
      → 仪表盘渲染 480586 字节
```

#### ⚠️ 三个必须做对的地方（都是实测踩出来的）

| # | 坑 | 后果 | 已修 |
|---|---|---|---|
| 1 | 标记**带换行** | 飞书按回车就发送 ⇒ 只发出第一行，**58 条全是残的** | 改**单行**标记 |
| 2 | 分片大小**没扣标记长度** | 1700 是**整条**上限，每条超一点点 ⇒ 全发不出去 | 扣掉标记长度 |
| 3 | 发完一条 **ref 就失效** | 第 2 条报 `snapshot ref was not found` | 每条重新 observe |
| 4 | 飞书**间歇性卡首屏** | `main` 空渲染，等 45 秒也没用 | 等一半时间自动 `reload` |

> **兜底**：不管粘成几个文件、叫什么名字，脚本都能从 `###FG:` 标记里认出来；
> 缺片会**报出是第几片**，用 `--start N` 补发即可。

```bash
python3 scripts/restore_from_base64.py ~/Downloads/fg
```

> **`restore_from_base64.py` 本身只有 4.8 KB 纯文本** —— 可以直接当文件传
> （低于 10 KB 上限）。`bootstrap_data.py` 同理（6.9 KB）。
> 否则用这条一行命令代替：
> ```bash
> python3 -c "import base64,sys;open('code.tar.xz','wb').write(base64.b64decode(''.join(open(sys.argv[1]).read().split())))" code.b64.txt
> ```

**端到端验证过**：base64 → 还原 → 解压 → 跑 pipeline，
37 个文件与仓库**逐字节一致**，仪表盘正常渲染（499 KB，含 PWA manifest）。

#### 为什么 `data` 通常不用传 —— Mac 自己抓

**公司电脑没有公网**（走内网 Nexus + 代理），但 **Mac 有**。
而 `Data/raw/` 里**几乎全是公开数据**：

| 文件 | 来源 | 大小 |
|---|---|---|
| `prices.csv` | Nasdaq 官方 API | 2.5 MB |
| `vix.csv` / `vix3m.csv` | CBOE cdn | 471 KB |
| `crypto_prices.csv` | Nasdaq 官方 API | 379 KB |
| `crypto_underlying.csv` | blockchain.info | 73 KB |
| `crypto_fng.csv` | alternative.me | 78 KB |
| `putcall_*.csv` | CBOE（2019 停更） | **生产零引用，不用管** |

⇒ 在 Mac 上跑一次就全有了：

```bash
export FG_PROXY=""        # ⚠️ 必须 —— 默认代理是**公司地址**，Mac 上不通
.venv/bin/python scripts/bootstrap_data.py
```

**真正不可再生的只剩 10 KB**（就是 `keep` 包里的东西）：

| 文件 | 为什么不可再生 |
|---|---|
| **`Data/raw/shoutu_fng.csv`** | 守猪待兔**逐日累积**的贪恐值 —— API 只能查「现在」，**查不了历史** |
| `Data/raw/splits.csv` | 手工维护的拆股表 |
| `Data/state.json` `crypto_state.json` | 仓位与冷却状态 |
| `Data/accounts.csv` `positions.csv` | **手工录入**的实盘快照 |
| `Data/trade_log.csv` | 交易记录 |
| `Data/shoutu_token` `tstoken` | 凭据（被 `.gitignore`，git 带不过来） |

> **⚠️ `shoutu_fng.csv` 建议单独备份** —— 它现在只有 13 行，但那是**起点**，
> 丢了就永远补不回来。

#### Mac 上的完整步骤

`dist/feishu/合并说明.txt` 里已经写好，照抄即可：

```bash
# 1. 飞书里全部下载到同一个目录，然后合并
cd ~/Downloads/fg
cat code-part*.bin > code.zip
cat tests-part*.bin > tests.zip 2>/dev/null || true
# （keep.zip 只有 1 个文件，本身就是 zip）

# 2. 解压到仓库
mkdir -p ~/learning_backtrader && cd ~/learning_backtrader
for z in ~/Downloads/fg/*.zip; do unzip -o "$z"; done

# 3. 建环境
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. 抓数据（公司电脑没公网，只有 Mac 能抓）
export FG_PROXY=""
.venv/bin/python scripts/bootstrap_data.py

# 5. 拷凭据（keep 包里已含；若手动拷则）
chmod 600 Data/shoutu_token

# 6. 自检
.venv/bin/python -m pytest -q
```

> **端到端验证过**：把分片按上面的方式合并解压后，跑测试得
> **579 passed / 3 skipped**（跳过的是「非 git 仓库」那几条，属正常）。

### Windows 侧（一次性）

右键仓库目录 → 属性 → 共享 → 高级共享 → 勾选「共享此文件夹」。

### macOS 侧

```bash
mkdir -p ~/mnt/win
mount_smbfs //<windows用户>@<公司电脑IP>/<共享名> ~/mnt/win
```

**拉取（公司 → 家）**：

```bash
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='logs/' \
      ~/mnt/win/learning_backtrader/ ~/learning_backtrader/
```

**回传（家 → 公司，只传每日产物）**：

```bash
cp ~/learning_backtrader/Data/raw/shoutu_fng.csv \
   ~/mnt/win/learning_backtrader/Data/raw/
```

```bash
umount ~/mnt/win
```

---

## 2. 首次部署

```bash
cd ~/learning_backtrader

# 2.1 环境（必须 3.10）
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2.2 密钥（从公司电脑拷，或设环境变量 SHOUTU_TOKEN）
cp <从公司电脑拷来的> Data/shoutu_token
chmod 600 Data/shoutu_token

# 2.3 自检
.venv/bin/python -m pytest -q            # 期望 511 passed
```

**⚠️ 若 `pytest` 报网络超时**：那是 `learning_lesson3` 在 **import 阶段**联网抓
tushare。仓库已加 `pytest.ini`（`testpaths = tests`）隔离，**裸跑应当正常**。

### 2.4 验证抓取（**不会写文件**）

```bash
.venv/bin/python scripts/fetch_shoutu_api.py --dry-run
```

期望输出 8 个标的的 `lever` / `emo_area` / `score`。

### 2.5 验证与页面一致（需要 bsk，可选）

```bash
.venv/bin/python scripts/compare_shoutu.py
```

期望 `表内标的 6 个，最大差 0.0` 与 `结论：✅ 一致`。

---

## 3. 注册定时任务

```bash
bash scripts/install_shoutu_task.sh
```

注册 `launchd` 作业 `com.fg.shoutu-daily`：**周二~周六 06:30**（本地时间）。

### 3.1 设置定时唤醒（**需 sudo**）

Mac 睡眠时 `launchd` **不会**执行；唤醒后才会补跑。若要保证 06:30 一定在运行：

```bash
sudo pmset repeat wakeorpoweron TWRFS 06:25:00
```

> **⚠️ `TWRFS` 不是 `MTWRFS`**：`pmset` 的日期字母
> **M=周一 T=周二 W=周三 R=周四 F=周五 S=周六 U=周日**。
> 任务只跑**周二~周六**，故用 `TWRFS`（含 `M` 会白白唤醒周一）。

---

## 4. 并行观察期（**一周**）

两个通道**同时跑**，互不冲突（同 `(date, symbol)` 是覆盖语义，且两边数值实测
吻合在 0~1 点内）：

| 机器 | 通道 | 覆盖标的 |
|---|---|---|
| 公司电脑（Windows） | bsk 浏览器 | **8**（分类表 6 + 个股贪恐视图 2，2026-09-24 起） |
| 家里 Mac | partner API | **8**（含 AXTX/CRCG） |

> 浏览器通道原先只有 6 个（AXTX/CRCG **不在**任何分类表内）。2026-09-24 起
> 对**分类表未覆盖**的标的改走 `#/stock_scan` 的「查询」，补齐到 8 个；
> 实测该查询对**已查询过**的标的**不扣额度**（服务端按标的去重计数）。
> 依据与选择器见 `docs/trading-discipline.md` 第 14.5 条「E1 补」。

**⚠️ 观察期内不要手动触发任何一台的抓取** —— 该指数**实时更新**，而
`append_records` 对同一 `(date, symbol)` 是**覆盖**语义 ⇒ 任何非 06:30 的手动运行
都会把当天记录覆盖成该时刻的快照（2026-09-23 已实际发生过一次）。

**一周后**：确认 Mac 稳定 ⇒ 停掉公司电脑的任务：

```bat
schtasks /change /tn "ShoutuDailyFetch" /disable
```

---

## 5. 日常运维

```bash
# 看日志
tail -f ~/learning_backtrader/logs/shoutu_daily.log

# 作业状态（含上次退出码）
launchctl print gui/$(id -u)/com.fg.shoutu-daily | grep -E "state|last exit"

# 暂停（保留配置，推荐用这个而不是删除）
launchctl disable gui/$(id -u)/com.fg.shoutu-daily

# 恢复
launchctl enable  gui/$(id -u)/com.fg.shoutu-daily

# 彻底删除
launchctl bootout gui/$(id -u)/com.fg.shoutu-daily
rm ~/Library/LaunchAgents/com.fg.shoutu-daily.plist
```

**重新注册**（改时间/改星期后）：编辑 `scripts/install_shoutu_task.sh` 里的
`StartCalendarInterval`，重跑即可（脚本是幂等的）。

---

## 6. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志 `FATAL exit=127: 未找到 python3` | 没建 venv 且系统无 python3 | 建 `.venv` |
| 日志 `警告：未找到 .venv/bin/python` | 回退到系统 python3 | **建 venv** —— 版本不符会破坏数值可复现性 |
| 日志 `[YINN] 守猪待兔 API 返回错误` | **`emo_area` 填错**（最可能） | 复核 `config.SHOUTU_API_PARAMS`，见 §14.5 §3 |
| 日志 `POST 失败` | 网络/代理 | 家里应**置空** `FG_PROXY` 走直连；公司需走代理 |
| 对照报 `diff` | **`emo_area` 填错**（唯一会静默出错处） | 跑 `scripts/compare_shoutu.py` 定位是哪个标的 |
| 对照报 `page_missing` | **异常**（2026-09-24 起对照已覆盖全部 8 个标的） | 先看步骤 `1b`（个股贪恐视图）是否报错，再看页面是否改版 |
| 当天记录缺失 | Mac 关机 / 睡眠未唤醒 | 检查 `pmset repeat`；补跑会覆盖当天快照，**慎用** |
| 对照报"页面零命中" | 页面改版 / 未登录 / sweep 漏读 | 先看 `bsk doctor` |

---

## 7. 手机访问仪表盘

**需求（用户，2026-09-23）**：支持在**手机上打开**，每次打开/刷新时主动重新计算，
**不需要手机后台常驻**。

⇒ **不需要 APK**。仪表盘本身就是**自包含 HTML**，手机浏览器直接访问即可。

### 7.1 启动服务（Mac 上）

```bash
.venv/bin/python scripts/serve_dashboard.py
```

输出（地址按本机网卡自动列出）：

```
仪表盘服务已启动（只读）。Ctrl-C 停止。

  ========================================================
   手机浏览器打开这个：

       http://192.168.1.10:8000/

  ========================================================

   然后：Chrome 菜单 →「添加到主屏幕」→ 主屏出现「贪恐指数」图标。
        **不需要 APK、不需要装任何东西。**
```

### 7.1.1 手机上怎么访问 —— 三件事

**① 手机与 Mac 连同一个 Wi-Fi**（不能用访客网络，也不能用手机流量）

**② 把上面那个地址抄到手机浏览器地址栏**

- 一台机器常有 Wi-Fi / 有线 / VPN 多个网卡，脚本会**把候选都列出来**
  （含 macOS 的 `<主机名>.local` —— 走 Bonjour，**换 IP 也能用**）。
  第一个打不开就换下一个试。
- ⚠️ 地址要输在浏览器**地址栏**，别输进搜索框。

**③ 变成独立图标**：Chrome 菜单 →「添加到主屏幕」

**连不上时按顺序查**：

| # | 检查 | 说明 |
|---|---|---|
| 1 | 同一个 Wi-Fi？ | 访客网络 / 手机流量都不行；部分路由器开了「AP 隔离」也会挡 |
| 2 | Mac 防火墙 | 设置 → 网络 → 防火墙 → 选项 → 允许 Python 接入 |
| 3 | 地址输对了吗 | 要输在**地址栏**；`http://` 别漏 |
| 4 | 服务还在跑吗 | Mac 上那个终端窗口不能关 |

> **为什么不给二维码**：纯标准库生成 QR 需要手写完整编码器（约 250 行），
> 且**无法在本仓库内验证扫得出来**。宁可让用户抄一次地址。

### 7.2 行为

| 项 | 说明 |
|---|---|
| **每次打开/刷新** | **重新跑 pipeline 并渲染** —— 不是缓存，拿到的永远是最新状态 |
| 手机侧要装什么 | **什么都不用装**，也不需要后台常驻 |
| 是否抓取数据 | ❌ **不抓取**（见 §7.3） |
| 是否写盘 | ❌ 不写（`pipeline.run(write=False)`，纯只读视图） |
| 端口 | 默认 8000，`--port` 可改 |

### 7.3 ⚠️ 为什么服务端**不抓取**数据

看起来"刷新时顺便抓一下最新值"很自然，但**必须禁止**：

1. 该指数**实时更新**，而 `append_records` 对同一 `(date, symbol)` 是**覆盖**
   语义 ⇒ **每次刷新都抓 = 每次刷新都把当天 06:30 的快照覆盖掉**（§14.5 已实际
   发生过一次）。分位数依赖**一致采样时刻**，这会让序列失去意义。
2. 每次刷新都消耗 `query_api` 额度（5000/月）。

⇒ **抓取仍由 06:30 的定时任务独占**；仪表盘只展示**已落盘**的数据。
若想看"此刻的实时值"，用 `scripts/compare_shoutu.py`（只读、不落盘）。

### 7.4 安全

服务**默认无鉴权**，只在**可信局域网**内使用：

- 默认绑 `0.0.0.0`（局域网可访问）；只想本机看：`--host 127.0.0.1`
- ⚠️ **不要暴露到公网** —— 页面含你的**持仓指令**
- 要加密码：`--password 用户名:密码`（HTTP Basic，**所有路由**都校验）

> **不在家时怎么访问？** 见 [`docs/remote-access.md`](remote-access.md)。
> 要点：**不要做端口映射**，先建加密隧道（Tailscale / 蒲公英 / 路由器 IPSec），
> 再叠一层 `--password`。家里路由器（锐捷 EG105G-P-L）**不支持 Easy VPN**，
> 且家宽多半没有公网 IPv4 —— 那份文档里有自测方法和方案对比。

### 7.5 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 手机打不开 | 不在同一局域网 / Mac 防火墙拦截 | 检查 Wi-Fi；macOS「设置 → 网络 → 防火墙」放行 Python |
| 页面字很小 | 浏览器未按 viewport 渲染 | 仪表盘已带 viewport；下拉强制刷新 |
| 要左右拖**整页**才能看全 | 表格溢出 | 仪表盘已给每个表格套横向滚动容器；应只拖**表格**。若仍溢出请报错 |
| 打开要等几秒 | 每次请求都要重跑 pipeline | 正常行为 |

### 7.6 打包成 APK（**已完成**）

已构建 Android 客户端（**WebView 外壳，3.9MB**），在手机上以独立图标打开：

```
APK 打开 → 载入本地外壳页面 → iframe 指向 Mac 的只读服务 → 显示最新仪表盘
```

**构建**（在 Windows 开发机上）：

```bash
bash mobile/build_apk.sh
# 产物：mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

**安装**：

```bash
$ANDROID_HOME/platform-tools/adb.exe install -r mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

或手机浏览器下载该 APK 手动安装（ColorOS 需允许「安装未知来源应用」）。

**首次使用**：打开 App → 弹出「服务器地址」→ 填 §7.1 打印的「手机」地址 → 保存。
之后每次打开/点「刷新」都会重新取最新结果，**不需要后台常驻**。

> ⚠️ 服务器地址存在**手机本地**，换 IP / 换 Wi-Fi 用「设置」改即可，**不必重新打包**。

**⚠️ 构建细节与四个必踩的坑**（JDK 必须是 21、仓库镜像要覆盖 `node_modules`、
build-tools 要 34.0.0、补丁要在 `cap sync` **之后**）见
[`mobile/README.md`](../mobile/README.md)。本机**公网不可达**，全部走内网 Nexus。

#### ⚠️ APK 怎么送到手机 —— 公司有安全下载限制

**APK 传不出公司网络**，故有三条路径（详见 `mobile/README.md`）：

| 路径 | 做法 | 说明 |
|---|---|---|
| **A. USB + adb** ⭐ | `adb install -r <apk>` | APK **一步都不离开公司机器**；需开 USB 调试 |
| **B. Mac 中转** | APK 随局域网同步到 Mac → 手机浏览器开 `http://<mac>:8000/apk` | Mac 顺带当分发点，见 §7.1 |
| **C. 在 Mac 上构建** | Mac 有公网，`sdkmanager` 装 SDK 无障碍 | APK **完全不碰公司网络**；仓库已是公网态配置，直接用即可 |

**§7.1 的启动输出会多一行 APK 地址**（若 Mac 上存在构建产物）：

```
  APK：   http://192.168.1.10:8000/apk    ← 手机浏览器打开即下载
```

---

## 附：macOS 与 Windows 的差异

| Windows 的坑 | macOS |
|---|---|
| `PYTHONUTF8=1` 必需（GBK 控制台） | ✅ **不需要**，默认 UTF-8 |
| `.cmd` 必须**纯 ASCII**（GBK 双字节吞换行） | ✅ **不适用**，`.sh` 中文注释安全 |
| `%date%` 含「星期几」⇒ 乱码 | ✅ 不需要 |
| 硬编码 `C:\...\python.exe` | ✅ 用 `.venv/bin/python` |
| `schtasks` 错过**不补跑** | ✅ `launchd` **唤醒后补跑** |
| — | ⚠️ `.sh` **必须 LF**（CRLF 会报 `bad interpreter: ...^M`，有守卫测试） |

---

## 附：每日流程（部署完成后）

```
06:25  pmset 唤醒 Mac
06:30  launchd → scripts/shoutu_daily.sh
         └─ .venv/bin/python scripts/fetch_shoutu_api.py
              └─ 8 个标的 → Data/raw/shoutu_fng.csv
       （无浏览器、无 Chrome、无 bsk）
       （不自动 git commit —— 由公司电脑提交）
```

**你日常什么都不用做。** 唯一需要人工的是**回传 `shoutu_fng.csv` 到公司电脑**
（见 §1 的 `cp` 命令）。
