# 2026-10-08 issue#3 补传还原 + 首跑 pytest 修复

## 变更

### 1. 补传 19 个被 strip 的实现文件（commit ce44ae1）
- 用户手机导出飞书 md（100801.md 含 1/52~52/52 全部分片、100802.md 为 41-52 冗余），
  `restore_from_base64.py` 还原到仓库，git add/commit/push（ce44ae1，20 文件 4525 行）。
- 19 个文件在仓库中**全部缺失**（零覆盖冲突）；`scripts/fetch_shoutu.py` 未覆盖（远程已存在）。

### 2. Mac 端首跑 pytest 暴露 3 类问题 → 修复（待提交）
| 问题 | 根因 | 修复 |
|---|---|---|
| tests/factors/test_screening.py 7 失败 | venv 缺 scipy（pandas nanops / scipy.stats.spearmanr） | requirements.txt 补 `scipy==1.14.1` + 本地安装 |
| test_minimal_excludes_dev_only_modules 1 失败 | `minimal_files()` 对包级引用**整目录全量收录** .py ⇒ 补传后 `factors/screening.py` 被误收进 minimal（Windows 端当时缺该文件才碰巧通过） | 改为**精确闭包**：目录引用只收 `__init__.py`，子模块由 `__init__` 的 imports 继续递归 |
| test_text_mode_emits_bootstrap_script 等 5 失败 | ① `scripts/mac_bootstrap.sh` 不在 19 个补传清单 ⇒ 引导分片无法生成/端到端测试读不到文件；② 测试断言直接 b64decode 全文（未 strip `###FGB:` 标记）⇒ Incorrect padding（Windows 端从未跑过 pytest） | ① 按测试规格新建 `scripts/mac_bootstrap.sh`（`python3 - <<'PY'` 字面量锚点、.md/.txt 双 glob、`\#`/`\+` 转义、混旧导出警告、非 xz 包警告、缺片报错）；② 测试改用 `bundle.strip_boot_marker()` 去标记后拼回解码 |

## 依据
- issue#3 结论（用户 2026-10-08 会话开头）：19 个清单口径、工具缺陷修复方向、Mac 端 pytest 为唯一真裁判。
- 测试即规格：`tests/test_make_feishu_bundle.py` 的守卫断言（minimal 排除研究模块、bootstrap 逐字节一致、引导分片排序在前不带 `###FG:`）。

## 口径
- skip 基线：补传前 21 skipped（624 passed）→ 首跑 13 failed（823 passed / 2 skipped）→ 修复后 **836 passed / 2 skipped / 0 failed**（+212 转回运行，符合"25 skipped 中约 23 个转回"的预期方向）。
- 剩余 2 skipped 为刻意跳过项（待查，不阻塞）。

## 影响
- `make_feishu_bundle --minimal` 体积进一步瘦身（研究模块不再误入运行集）。
- `mac_bootstrap.sh` 成为首次引导的标准入口（与 mac_restore.sh 并存：前者不依赖仓库文件，后者依赖 restore_from_base64.py）。
- Windows 端拉取后行为对齐（minimal 闭包、bootstrap 链路均按 Mac 端真裁判修正）。

## 验证
- `.venv/bin/python -m pytest -q` → **836 passed, 2 skipped, 0 failed**（exit=0，2026-10-08 实测）。
- 还原链路：`restore_from_base64.py ~/Downloads/fg_restore` 认出 1 包 backfill 52/52 无缺片，解压 19 文件 + APPLY-ON-MAC.md。

## 提交
- ce44ae1（补传 19 文件 + 变更记录）已推送。
- 78e4c44（mac_bootstrap.sh / make_feishu_bundle.py / requirements.txt / 测试修正）已推送。

## 追加（2026-10-08 收尾）：剩余 2 skipped 归零
- 排查：`pytest -rs` 定位 2 个 skip 均为 `test_shoutu_page_query.py::test_query_one_js_*`，
  deps 误挂 `scripts/shoutu_page_query.js`（该文件双端均不存在，生产零引用）。
- 实测：去掉 deps 后两测试**直接通过**（0.46s）—— 它们实际守卫 fetch_shoutu.py 的
  `query_one_js`（重建版已内联 JS 模板，不再读 js 文件）。
- 处理：**不删测试**（会丢失有效守卫），改为把 deps 修正为 `scripts/fetch_shoutu.py`
  （与本文件其他测试一致）+ 注释说明根因。
- 最终全量 pytest：**838 passed / 0 skipped / 0 failed**（skip 21→2→0）。
- 结论：Windows→Mac 投递链正式关闭（唯一曾缺失的 js 文件双端均不存在，非传输缺口）。
