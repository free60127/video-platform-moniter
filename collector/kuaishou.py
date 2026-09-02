# -*- coding: utf-8 -*-
"""快手采集：作品管理列表（标题/播放/点赞/评论）—— Playwright"""
import re

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

URL = "https://cp.kuaishou.com/article/manage/video"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
DUR_RE = re.compile(r"^\d{1,2}:\d{2}$")
SKIP = {"已发布", "已上线", "待发布", "播放", "点赞", "评论", "全部作品", "时间范围",
        "共365天", "流量助推", "审核中", "未通过"}


async def collect(cookies_dir) -> dict:
    out = {"platform": "kuaishou", "works": [], "fans": None, "extra": {}, "ok": False, "error": None}
    try:
        load_cookie(cookies_dir / "account.json")
    except Exception as e:
        out["error"] = str(e)
        log(f"[kuaishou] ✗ {e}")
        return out
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=str(cookies_dir / "account.json"))
            await clean_ctx(ctx)
            page = await ctx.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            body = ""
            prev = ""
            stable = 0
            for i in range(15):
                await page.wait_for_timeout(2000)
                body = await page.evaluate("() => document.body.innerText")
                if body == prev:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                prev = body
                if "已发布" in body and len(body) > 800:
                    continue
            lines = [ln.strip() for ln in body.split("\n")]
            lines = [ln for ln in lines if ln]
            out["works"] = _parse(lines)
            out["ok"] = True
            log(f"[kuaishou] ✓ 作品 {len(out['works'])} 条")
            await browser.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log(f"[kuaishou] ✗ {out['error']}")
    return out


def _parse(lines):
    """行结构：时长 → 标题(含描述) → 已发布 → 日期 → 播放 点赞 评论"""
    works = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i] == "已发布":
            # 结构：时长 → 标题 → 已发布 → 日期 → 播放 点赞 评论
            pub = lines[i + 1] if (i + 1 < n and DATE_RE.match(lines[i + 1])) else None
            t = i - 1
            while t >= 0 and (DUR_RE.match(lines[t]) or lines[t] in SKIP or to_int(lines[t]) is not None):
                t -= 1
            title = lines[t] if t >= 0 else ""
            # 数字：日期后连续 3 个数字行（跳过日期行与流量助推行）
            vals = []
            m = i + 1
            while m < n and len(vals) < 3:
                ln = lines[m]
                if DATE_RE.match(ln) or ln == "流量助推":
                    m += 1
                    continue
                v = to_int(ln)
                if v is not None:
                    vals.append(v)
                m += 1
            works.append({
                "title": title,
                "pub_datetime": pub,
                "views": vals[0] if len(vals) > 0 else None,
                "likes": vals[1] if len(vals) > 1 else None,
                "comments": vals[2] if len(vals) > 2 else None,
                "collects": None, "shares": None,
            })
            i = max(i + 1, m - 1)
        i += 1
    # 去重+反序（列表从上到下=最新）
    seen, dedup = set(), []
    for w in reversed(works):
        key = w["title"]
        if key and key not in seen:
            seen.add(key)
            dedup.append(w)
    return dedup if works else []


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "ks_uploader"))
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
