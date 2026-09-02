# -*- coding: utf-8 -*-
"""采集器统一入口：run_platform(name) / run_all()

登录态约定：cookies/<platform>_uploader/account.json
  - Playwright storage_state 格式：{"cookies": [...], "origins": [...]}
  - B站兼容 biliup 格式：{"cookie_info": {"cookies": [...]}}
用 login.py 或自行导出（如 social-auto-upload 项目）均可。
"""
import asyncio
import inspect
import os
import sys
from pathlib import Path

from . import bilibili, kuaishou, douyin, xiaohongshu, tencent
from .base import log

COOKIES_ROOT = Path(os.environ.get("VPM_COOKIES_DIR") or
                    (Path(__file__).resolve().parent.parent / "cookies"))

MODULES = {
    "bilibili": (bilibili, "bilibili_uploader"),
    "kuaishou": (kuaishou, "ks_uploader"),
    "douyin": (douyin, "douyin_uploader"),
    "tencent": (tencent, "tencent_uploader"),
    "xiaohongshu": (xiaohongshu, "xiaohongshu_uploader"),
}


async def run_platform(platform, cookies_root=None):
    mod, subdir = MODULES[platform]
    root = Path(cookies_root) if cookies_root else COOKIES_ROOT
    func = mod.collect
    if asyncio.iscoroutinefunction(func):
        return await func(root / subdir)
    return await asyncio.to_thread(func, root / subdir)


def run_all(platforms=None, cookies_root=None):
    """串行采集所有平台，返回 {platform: result}"""
    targets = platforms or list(MODULES.keys())
    results = {}
    for pf in targets:
        if pf not in MODULES:
            results[pf] = {"platform": pf, "works": [], "fans": None, "extra": {},
                           "ok": False, "error": f"未知平台 {pf}"}
            continue
        log(f"\n===== {pf} =====")
        try:
            results[pf] = asyncio.run(run_platform(pf, cookies_root))
        except Exception as e:
            results[pf] = {"platform": pf, "works": [], "fans": None, "extra": {},
                           "ok": False, "error": f"{type(e).__name__}: {e}"}
            log(f"[{pf}] ✗ 严重: {e}")
    return results


if __name__ == "__main__":
    import json
    plats = sys.argv[1:] if len(sys.argv) > 1 else None
    res = run_all(plats)
    print(json.dumps(res, ensure_ascii=False, indent=2))
