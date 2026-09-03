# -*- coding: utf-8 -*-
"""通知适配器：Server酱(ServerChan Turbo) / PushPlus 微信推送。
配置 notify.json 于本目录：{"serverchan_key": "SCT...", "pushplus_token": ""}
未配置任一 key 时静默降级为日志（不中断业务）。
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CONF = Path(__file__).resolve().parent / "notify.json"


def _cfg():
    try:
        return json.loads(CONF.read_text(encoding="utf-8")) if CONF.exists() else {}
    except Exception:
        return {}


def available():
    c = _cfg()
    return bool(c.get("serverchan_key") or c.get("pushplus_token"))


def _post(url, data=None, headers=None, timeout=10):
    body = urlencode(data).encode("utf-8") if data else None
    req = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")[:300]
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


def send(title, content="", log=None):
    """发送微信推送。title 最长 32 字；content 支持 markdown。返回 True/False。"""
    c = _cfg()
    if not available():
        if log:
            log(f"[notify] 未配置推送通道(notify.json)，跳过: {title}")
        return False
    ok = False
    if c.get("serverchan_key"):
        r = _post(f"https://sctapi.ftqq.com/{c['serverchan_key']}.send",
                  {"title": title[:32], "desp": content})
        ok = "errno" not in r and r.startswith("{")
        if log:
            log(f"[notify] Server酱: {'OK' if ok else r[:120]}")
        if not ok:
            ok = False
    if c.get("pushplus_token"):
        import urllib.request as _u
        req = _u.Request("http://www.pushplus.plus/send", data=json.dumps(
            {"token": c["pushplus_token"], "title": title[:100], "content": content, "template": "markdown"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=10) as r:
                rp = r.read().decode("utf-8", errors="replace")
                ok = ok or '{"code":200' in rp
                if log:
                    log(f"[notify] PushPlus: {rp[:120]}")
        except Exception as e:
            if log:
                log(f"[notify] PushPlus 失败: {e}")
    return ok


if __name__ == "__main__":
    # 测试：python notify.py "测试标题" "测试内容"
    print(send(sys.argv[1] if len(sys.argv) > 1 else "测试通知",
               sys.argv[2] if len(sys.argv) > 2 else "notify.py 自检，请忽略"))
