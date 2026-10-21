"""fg_sync_tool._brief_filter 测试（MT-1021a 实踩 bug 修复）。

bug 背景：--brief 模式只保留 ✅/❌/⛔/⚠️ 开头的行，
导致 ⛔ 冲突文件明细（"   - evolution/hypotheses.md"）被吞掉，
Windows 侧只看到「冲突文件：」而看不到具体文件。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fg_sync_tool import _brief_filter  # noqa: E402


def test_brief_keeps_error_block_details():
    """⛔ 错误行后的 - xxx 明细和「处理方式」提示必须保留。"""
    out = (
        "认出的包：sync_1021a(12片)\n"
        "解压中...\n"
        "白名单校验中...\n"
        "⛔ 与 Mac 本地未提交修改冲突，中止（不自动覆盖），冲突文件：\n"
        "   - evolution/hypotheses.md\n"
        "   - docs/mac-tasks.md\n"
        "处理方式：先在 Mac 提交/丢弃本地改动，再重新触发同步。\n"
        "其他过程细节...\n"
    )
    result = _brief_filter(out, "")
    assert "认出的包：sync_1021a(12片)" in result
    assert "⛔" in result
    assert "evolution/hypotheses.md" in result, "冲突文件明细必须保留"
    assert "docs/mac-tasks.md" in result
    assert "处理方式" in result, "处理提示必须保留"
    assert "解压中" not in result, "过程细节必须丢弃"
    assert "白名单校验中" not in result


def test_brief_drops_details_after_success():
    """✅ 成功行后的过程细节仍被丢弃。"""
    out = (
        "认出的包：sync_1021b(3片)\n"
        "过程细节 1...\n"
        "过程细节 2...\n"
        "✅ 已推送 origin/main（提交 abc1234）\n"
        "✅ 增量 pytest 通过\n"
    )
    result = _brief_filter(out, "")
    assert "认出的包" in result
    assert "✅" in result
    assert "过程细节" not in result


def test_brief_keeps_warnings():
    """⚠️ 警告行保留。"""
    out = "⚠️ 分片不齐：还缺第 2 片\n其他细节\n"
    result = _brief_filter(out, "")
    assert "⚠️" in result
    assert "其他细节" not in result


def test_brief_error_block_stops_at_next_conclusion():
    """⛔ 错误块在遇到下一个 ✅/⚠️ 行时停止。"""
    out = (
        "⛔ patch 应用失败\n"
        "   - 文件 A\n"
        "   - 文件 B\n"
        "⚠️ 已保留分片待排查\n"
        "其他过程\n"
    )
    result = _brief_filter(out, "")
    assert "文件 A" in result
    assert "文件 B" in result
    assert "⚠️" in result
    # ⚠️ 后的过程细节不应被当作错误块明细保留
    assert "其他过程" not in result
