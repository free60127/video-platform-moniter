# -*- coding: utf-8 -*-
"""采集器公共设施：cookie 加载 / 文本解析工具"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg):
    print(msg, flush=True)


def to_int(s):
    """'175' / '1,350' / '-' / 'None' -> int | None"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "--", "None", "null", "暂无"):
        return None
    m = re.search(r"-?\d+", s)
    return int(m.group(0)) if m else None


def load_cookie(path):
    """读 account.json：biliup 格式（cookie_info.cookies）与 Playwright storage_state 格式均返回原 dict"""
    if not path.exists():
        raise FileNotFoundError(f"cookie 文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


async def clean_ctx(ctx):
    """通用抗检测浏览器上下文初始化（最小化，不过度干预）"""
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return ctx
