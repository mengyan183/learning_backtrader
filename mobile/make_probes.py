# -*- coding: utf-8 -*-
"""生成「决定性探针」—— 一次实验分离 **大小 / 内容 / 扩展名** 三个变量。

【为什么要重做探针（2026-09-23）】
第一版探针全是 `.bin` + **随机数据**，三个变量混在一起，结果无法解释：

    fg-src-kit.zip      5.7 KB   ✅ 通过
    probe-100k.bin      100 KB   ❌ 上传失败
    probe-500k.bin      500 KB   ❌
    probe-1m.bin        1 MB     ❌
    probe-2m.bin        2 MB     ❌

  阈值落在 (5.7 KB, 100 KB] —— 但**说不清拦的是哪一个**：

    A. 大小？  —— 5.7 KB 过、100 KB 不过
    B. 内容？  —— 随机二进制**无法扫描**，DLP 可能"扫不了就拦"
    C. 扩展名？—— `.bin` 是未知类型，可能直接被拒

【本探针的设计】只让**一个变量**变化：

    t05k.zip    5 KB   文本    .zip    基准（已知可过）
    t50k.zip   50 KB   文本    .zip    大小↑，内容仍可扫描
    t500k.zip 500 KB   文本    .zip    **决定性**：过 ⇒ 大小不是限制
    r05k.zip    5 KB   随机    .zip    内容：小尺寸下的不可扫描内容
    t05k.json   5 KB   文本    .json   扩展名（.json 已知可过）
    t05k.bin    5 KB   文本    .bin    扩展名：内容可扫描但类型未知

【怎么读结果】
  t500k.zip 过           ⇒ 拦的是**内容**（可扫描性），不是大小
  t500k.zip 不过 / t50k.zip 过 ⇒ 拦的是**大小**，阈值在 50~500 KB
  r05k.zip 不过          ⇒ 内容不可扫描会被拦（与大小无关）
  t05k.bin 不过 / t05k.json 过 ⇒ `.bin` 这种未知扩展名会被拦
"""
import json
import os
import sys
import zipfile

# 可读文本 —— DLP 能扫出内容，模拟"正常文件"
TEXT = ("2026-09-23 06:30:00 INFO  fg_index=52.3 zone=中性 "
        "position=0.45 vix=48.1 term=51.7 price=49.2 breadth=47.8\n")

SIZES = {"t05k": 5 * 1024,
         "t50k": 50 * 1024,
         "t500k": 500 * 1024,
         "r05k": 5 * 1024}


def _text(n):
    return (TEXT * (n // len(TEXT) + 1)).encode("utf-8")[:n]


def _zip_bytes(payload, name="data.txt"):
    """用 **STORED**（不压缩）打包，好让 zip 大小≈payload 大小，便于控制。"""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr(name, payload)
    return buf.getvalue()


def _zip_of_size(target):
    """构造一个**大小接近 target** 的 zip（STORED，故 payload 比 target 略小）。"""
    guess = max(64, target - 256)
    for _ in range(12):                       # 迭代收敛
        blob = _zip_bytes(_text(guess))
        delta = target - len(blob)
        if abs(delta) <= 16:
            return blob
        guess += delta
    return blob


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    made = []

    for key, size in SIZES.items():
        if key == "r05k":
            blob = _zip_bytes(os.urandom(size - 256))
        else:
            blob = _zip_of_size(size)
        p = os.path.join(out_dir, key + ".zip")
        with open(p, "wb") as fh:
            fh.write(blob)
        made.append(p)

    # 同内容、不同扩展名 —— 只变扩展名这一个变量
    same = _text(SIZES["t05k"])
    for ext in (".json", ".bin"):
        p = os.path.join(out_dir, "t05k" + ext)
        with open(p, "wb") as fh:
            if ext == ".json":
                # 必须是**合法 JSON**，否则又混入"格式非法"这个变量
                fh.write(json.dumps(
                    {"note": "probe", "date": "2026-09-23",
                     "payload": same.decode("utf-8")},
                    ensure_ascii=False).encode("utf-8"))
            else:
                fh.write(same)
        made.append(p)

    return made


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "mobile/dist/probe2"
    print("=== 决定性探针（分离 大小 / 内容 / 扩展名）===")
    print("    全部传一次，把结果告诉我。\n")
    for p in sorted(build(out)):
        print("    %-14s %9s" % (os.path.basename(p), _human(os.path.getsize(p))))
    print("\n    目录：%s" % out)
    print("\n    怎么读结果：")
    print("      t500k.zip 过              -> 拦的是【内容】不是大小")
    print("      t50k 过 / t500k 不过      -> 拦的是【大小】，阈值在 50~500 KB")
    print("      r05k.zip 不过             -> 不可扫描内容会被拦（与大小无关）")
    print("      t05k.bin 不过 / .json 过  -> 【未知扩展名】会被拦")
    return 0


def _human(n):
    return ("%d B" % n) if n < 1024 else (
        ("%.1f KB" % (n / 1024)) if n < 1048576 else ("%.2f MB" % (n / 1048576)))


if __name__ == "__main__":
    sys.exit(main())
