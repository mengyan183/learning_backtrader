# -*- coding: utf-8 -*-
"""G-5 守卫：OKX 凭据**不得**出现在 curl 的 argv 里。

背景（WT-12 代码审查 G-5）：原实现把 api_key / 签名 / passphrase 作为
`curl -H` 参数 ⇒ 出现在**进程命令行**，同机任意进程（`ps aux` / Windows
任务管理器）都能读到，等于把密钥文件 `chmod 600` 的保护整个绕开。

修法：写进 0600 的 `--config` 临时文件，用完即删。本测试锁住三件事：
① argv 里没有凭据；② 凭据确实经 `--config` 传入（否则请求会失败）；
③ 临时文件被删掉（不留残骸）。

不联网：`subprocess.run` 被替换成假的。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "sync_positions.py")


def _load():
    spec = importlib.util.spec_from_file_location("sync_positions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()

CREDS = {"api_key": "AK-SECRET-111", "secret": "SK-SECRET-222",
         "passphrase": "PP-SECRET-333"}


class _Result:
    returncode = 0
    stdout = "{}"
    stderr = ""


def test_okx_credentials_not_in_argv(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        i = cmd.index("--config")
        seen["cfg_path"] = cmd[i + 1]
        with open(cmd[i + 1], encoding="utf-8") as f:
            seen["cfg"] = f.read()
        return _Result()

    # ⚠️ `sync_positions` 的 subprocess 是**函数内局部 import** ⇒ 模块上没有
    #    该属性，必须 patch 全局模块（首版踩坑：AttributeError）。
    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)
    sp._okx_request(dict(CREDS), "/api/v5/account/balance")

    argv = " ".join(seen["cmd"])
    for label in ("api_key", "secret", "passphrase"):
        assert CREDS[label] not in argv, (
            "%s 出现在 curl argv 里（同机可读）⇒ 必须走 --config" % label)

    assert CREDS["api_key"] in seen["cfg"], "凭据应经 --config 文件传入"
    assert CREDS["passphrase"] in seen["cfg"]


def test_okx_config_tempfile_removed(monkeypatch):
    """临时文件必须删掉 —— 否则凭据以明文留在 %TEMP% 里。"""
    seen = {}

    def fake_run(cmd, **kw):
        i = cmd.index("--config")
        seen["cfg_path"] = cmd[i + 1]
        assert os.path.exists(cmd[i + 1]), "发请求时配置文件应存在"
        return _Result()

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)
    sp._okx_request(dict(CREDS), "/api/v5/account/balance")

    assert not os.path.exists(seen["cfg_path"]), "凭据临时文件未清理"
