# -*- coding: utf-8 -*-
"""抖音采集：创作者中心作品管理（播放/点赞/评论/分享/收藏/完播率）—— Playwright"""
import re

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

URL = "https://creator.douyin.com/creator-micro/content/manage"
DATE_RE = re.compile(r"^\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}$")
DUR_RE = re.compile(r"^\d{1,2}:\d{2}$")
LABELS = {"播放", "点赞", "评论", "分享", "收藏", "完播率", "2秒跳出率", "吸粉量", "粉丝增量"}
SKIP = {"编辑作品", "设置权限", "作品置顶", "删除作品", "已发布", "审核中", "私密",
        "合集管理移到这里啦", "知道了", "加载中…", "没有更多作品", "暂无作品",
        "全部", "已发布作品", "所有时间", "导出数据", "作品", "作品合集", "体裁"}


async def collect(cookies_dir) -> dict:
    out = {"platform": "douyin", "works": [], "fans": None, "extra": {}, "ok": False, "error": None}
    try:
        load_cookie(cookies_dir / "account.json")
    except Exception as e:
        out["error"] = str(e)
        log(f"[douyin] ✗ {e}")
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
            for i in range(20):
                await page.wait_for_timeout(2000)
                body = await page.evaluate("() => document.body.innerText")
                if body == prev:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                prev = body
            lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
            out["works"] = _parse(lines)
            out["ok"] = True
            log(f"[douyin] ✓ 作品 {len(out['works'])} 条")
            await browser.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log(f"[douyin] ✗ {out['error']}")
    return out


def _parse(lines):
    works = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i] == "播放":
            # 块 = 上一个播放之后 ~ i
            start = i
            # 日期行=向前找最后一个日期正则行
            pub = None
            k = i - 1
            while k >= 0 and k > start - 20:
                if DATE_RE.match(lines[k]):
                    pub = lines[k]
                    break
                k -= 1
            # 标题=块内第一个非跳过行（跳过时长/按钮/纯数字/日期/标签行）
            title = None
            t = (k - 1) if pub else (i - 1)
            while t >= 0:
                ln = lines[t]
                if (ln in SKIP or ln in LABELS or DUR_RE.match(ln) or DATE_RE.match(ln)
                        or re.fullmatch(r"\d+", ln) or ln == "-" or ln.startswith("已智能生成")):
                    t -= 1
                    continue
                title = ln
                break
            # 值：播放行是锚=第一个标签，其后按标签驱动；遇到日期/时长行=块边界停
            vals = {}
            j = i + 1
            cur = "播放"
            while j < n and len(vals) < 5:
                ln = lines[j]
                if DUR_RE.match(ln) or DATE_RE.match(ln):
                    break
                if ln in LABELS:
                    cur = ln
                elif cur and cur in ("播放", "点赞", "评论", "分享", "收藏"):
                    v = to_int(ln)
                    if v is not None:
                        vals[cur] = v
                    cur = None
                j += 1
            if title:
                works.append({
                    "title": title, "pub_datetime": pub,
                    "views": vals.get("播放"), "likes": vals.get("点赞"),
                    "comments": vals.get("评论"), "collects": vals.get("收藏"),
                    "shares": vals.get("分享"),
                })
        i += 1
    seen, dedup = set(), []
    for w in reversed(works):
        key = (w["title"], w["pub_datetime"])
        if key not in seen:
            seen.add(key)
            dedup.append(w)
    return dedup if works else []


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "douyin_uploader"))
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
