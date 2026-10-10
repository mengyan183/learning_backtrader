#!/usr/bin/env python3
"""fg-sync bypass handler: 收到 ###FG: 分片直接落盘聚合，绕过 LLM。

用法: python3 fg-sync-bypass.py <消息文件> [chat_id]
消息文件内容可能是单条或多条 ###FG:...###FG:end### 分片（debounce 合并）。

行为:
- 解析全部分片（包名/序号/总数/base64），逐片写入 ~/.openclaw/tmp/fg-sync-in/<包>_<序号>.md
- 同序号重复接收 → 跳过（幂等）
- 收齐（已收片数 == 总数）→ 调用 fg_sync_tool.py 还原入库，回传结果到飞书
- 未收齐 → 静默（不回传，避免 855 条刷屏）
- 无分片但命中「同步待办/任务清单/有什么任务/待办」→ 直接跑 push_todo.py 回传待办快照（免 LLM）
"""
import json, os, re, sys, subprocess, urllib.request

HOME = os.path.expanduser("~")
IN_DIR = os.path.join(HOME, ".openclaw", "tmp", "fg-sync-in")
CFG_PATH = os.path.join(HOME, ".openclaw", "openclaw.json")
REPO = "/Users/xingguo/learning_backtrader"
FG_RE = re.compile(r"###FG:([^:#\n]+):(\d+)/(\d+)###([\s\S]*?)###FG:end###")
TODO_RE = re.compile(r"同步待办|任务清单|有什么任务|待办")


def load_cfg():
    with open(CFG_PATH) as f:
        return json.load(f)


def send_feishu(text, chat_id):
    """以 bot 身份向指定 chat 发普通文本消息（复用 appId/appSecret）。"""
    cfg = load_cfg()
    f = cfg["channels"]["feishu"]
    base = "https://open.feishu.cn/open-apis"
    req = urllib.request.Request(
        f"{base}/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": f["appId"], "app_secret": f["appSecret"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        tok = json.loads(r.read())
    if tok.get("code") != 0:
        return f"token err: {tok.get('msg')}"
    token = tok["tenant_access_token"]
    body = json.dumps(
        {"receive_id": chat_id, "msg_type": "text",
         "content": json.dumps({"text": text})}
    ).encode()
    req2 = urllib.request.Request(
        f"{base}/im/v1/messages?receive_id_type=chat_id",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req2, timeout=15) as r:
            resp = json.loads(r.read())
            return "ok" if resp.get("code") == 0 else resp.get("msg", "send fail")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.read().decode()[:200]}"


def pkg_hash(pkg, total):
    """包内容哈希：全部分片原文按序号拼接的 sha256。"""
    import hashlib
    h = hashlib.sha256()
    for i in range(1, total + 1):
        p = os.path.join(IN_DIR, f"{pkg}_{i}.md")
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()


def ingest_package(pkg, total, chat_id):
    """收齐后调用 fg_sync_tool.py 还原入库并回传。幂等：同内容只入库一次。"""
    # 已入库标记：内容 hash 一致则跳过（重复发送整包不会重复入库）
    marker = os.path.join(IN_DIR, f"{pkg}.done")
    cur_hash = pkg_hash(pkg, total)
    if os.path.exists(marker) and open(marker).read().strip() == cur_hash:
        return  # 完全相同的包已入库过，静默跳过

    # 聚合全部已收分片原文（按序号排序）到 sync_in.md
    parts = []
    for i in range(1, total + 1):
        p = os.path.join(IN_DIR, f"{pkg}_{i}.md")
        if os.path.exists(p):
            parts.append(open(p).read().strip())
    if not parts:
        return
    combined = "\n".join(parts)
    # 存为单文件供 fg_sync_tool.py 消费（该工具解析 ###FG: 标记）
    sync_file = os.path.join(IN_DIR, "sync_in.md")
    with open(sync_file, "w") as f:
        f.write(combined)

    today = __import__("datetime").date.today().isoformat()
    cmd = [
        os.path.join(REPO, ".venv", "bin", "python"),
        os.path.join(REPO, "scripts", "fg_sync_tool.py"),
        "-f", sync_file,
        "--commit", f"fg-sync: {pkg} 公司端同步 {today}",
        "--quick", "--brief",
    ]
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=180)
        out = (r.stdout + r.stderr).strip()
        # 入库成功后写标记（无论 commit 是否成功——文件已落盘即可视为已处理）
        with open(marker, "w") as f:
            f.write(cur_hash)
        send_feishu(f"✅ {pkg} 已收齐 {total} 片，开始入库…\n{out}", chat_id)
    except subprocess.TimeoutExpired:
        send_feishu(f"⏳ {pkg} 入库超时，请稍后查收", chat_id)


def run_todo_snapshot(chat_id):
    """待办快照：跑 push_todo.py 并把摘要原样回传（免 LLM，秒级）。"""
    cmd = [
        os.path.join(REPO, ".venv", "bin", "python"),
        os.path.join(REPO, "scripts", "push_todo.py"),
    ]
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=60)
        out = (r.stdout + r.stderr).strip()
        if not out:
            out = "push_todo.py 无输出（检查 docs/ 是否可读）"
        send_feishu(out, chat_id)
    except subprocess.TimeoutExpired:
        send_feishu("⏳ 待办快照生成超时", chat_id)


def main():
    if len(sys.argv) < 2:
        return
    msg_file = sys.argv[1]
    if not os.path.exists(msg_file):
        return
    text = open(msg_file, encoding="utf-8", errors="replace").read()

    # chat_id 从 openclaw 配置不易拿，从消息文件所在目录约定：附加参数传入
    chat_id = sys.argv[2] if len(sys.argv) > 2 else "oc_a9306b326943821490184d073dae9a65"

    matches = FG_RE.findall(text)
    if not matches:
        # 非分片消息：命中待办关键词 → 直接回传待办快照（免 LLM）
        if TODO_RE.search(text):
            run_todo_snapshot(chat_id)
        return

    os.makedirs(IN_DIR, exist_ok=True)
    seen = {}
    for pkg, seq, total, b64 in matches:
        seq_i, total_i = int(seq), int(total)
        key = (pkg, seq_i)
        if key in seen:
            continue
        seen[key] = True
        # 落盘：原文保存（含标记），幂等（同序号覆盖）
        p = os.path.join(IN_DIR, f"{pkg}_{seq_i}.md")
        with open(p, "w") as f:
            f.write(f"###FG:{pkg}:{seq_i}/{total_i}###{b64}###FG:end###")

    # 统计每个包的进度（按磁盘实际落盘数计算，避免重复计）
    pkg_totals = {}
    for pkg, seq, total, b64 in matches:
        pkg_totals.setdefault(pkg, int(total))
    for pkg, total in pkg_totals.items():
        recv = len([1 for i in range(1, total + 1)
                    if os.path.exists(os.path.join(IN_DIR, f"{pkg}_{i}.md"))])
        if recv >= total:
            ingest_package(pkg, total, chat_id)
        elif recv > 0 and recv % 100 == 0:
            send_feishu(f"📥 {pkg} 已收 {recv}/{total} 片", chat_id)


if __name__ == "__main__":
    main()
