# -*- coding: utf-8 -*-
"""小红书采集：新版笔记管理 /new/note-manager（观看/评论/点赞/收藏/分享）+ 首页粉丝概览 —— Playwright"""
import asyncio
import re
import json

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

HOME = "https://creator.xiaohongshu.com/"
MANAGE = "https://creator.xiaohongshu.com/new/note-manager"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
DUR_RE = re.compile(r"^\d{1,2}:\d{2}$")


async def _evaluate(page, expr):
    return await asyncio.wait_for(page.evaluate(expr), 8)


async def collect(cookies_dir) -> dict:
    out = {"platform": "xiaohongshu", "works": [], "fans": None, "extra": {}, "ok": False, "error": None}
    try:
        load_cookie(cookies_dir / "account.json")
    except Exception as e:
        out["error"] = str(e)
        log(f"[xiaohongshu] ✗ {e}")
        return out
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=str(cookies_dir / "account.json"))
            await clean_ctx(ctx)
            page = await ctx.new_page()
            # 1) 笔记管理列表（小红书偶发慢，60s 超时+重试一次）
            for attempt in (1, 2):
                try:
                    await page.goto(MANAGE, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    log(f"[xiaohongshu] 打开笔记管理超时，重试…")
            body = ""
            for i in range(15):
                await page.wait_for_timeout(2000)
                try:
                    body = await _evaluate(page, "() => document.body.innerText")
                except Exception:
                    continue
                if "已发布" in body and len(body) > 300:
                    break
            lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
            out["works"] = _parse(lines)
            # 2) 首页概览（粉丝/关注/近7日）
            for attempt in (1, 2):
                try:
                    await page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    log(f"[xiaohongshu] 打开首页超时，重试…")
            hbody = ""
            for i in range(10):
                await page.wait_for_timeout(2000)
                try:
                    hbody = await _evaluate(page, "() => document.body.innerText")
                except Exception:
                    continue
                if "粉丝" in hbody or "粉丝数" in hbody:
                    break
            out["fans"], out["extra"] = _parse_home(hbody)
            out["ok"] = True
            log(f"[xiaohongshu] ✓ 笔记 {len(out['works'])} 条, 粉丝 {out['fans']}")
            await browser.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log(f"[xiaohongshu] ✗ {out['error']}")
    return out


def _parse(lines):
    """行结构：时长 → 标题 → 日期 → 5 数字（观看/评论/点赞/收藏/分享）"""
    works = []
    n = len(lines)
    i = 0
    header_end = 0
    for idx, ln in enumerate(lines):
        if ln in ("已发布", "审核中", "未通过"):
            header_end = idx + 1
    while i < n:
        if DATE_RE.match(lines[i]):
            # 标题在前
            t = i - 1
            title = None
            while t >= header_end:
                if DUR_RE.match(lines[t]):
                    t -= 1
                    continue
                title = lines[t]
                break
            vals = []
            j = i + 1
            while j < n and len(vals) < 5 and not DATE_RE.match(lines[j]):
                v = to_int(lines[j])
                if v is not None:
                    vals.append(v)
                j += 1
            works.append({
                "title": title or "",
                "pub_datetime": lines[i],
                "views": vals[0] if len(vals) > 0 else None,
                "comments": vals[1] if len(vals) > 1 else None,
                "likes": vals[2] if len(vals) > 2 else None,
                "collects": vals[3] if len(vals) > 3 else None,
                "shares": vals[4] if len(vals) > 4 else None,
            })
            i = j
        else:
            i += 1
    dedup = []
    seen = set()
    for w in reversed(works):
        if w["title"] and w["title"] not in seen:
            seen.add(w["title"])
            dedup.append(w)
    return dedup


def _parse_home(body):
    """首页：关注数 12 / 粉丝数 19 / 获赞与收藏 21（值在标签前一行）+ 近7日数据（值在标签后一行）"""
    fans = None
    extra = {}
    if not body:
        return fans, extra
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        if ln in ("关注数", "粉丝数", "粉丝", "获赞与收藏"):
            # 值在标签前一行：... 12 关注数
            v = to_int(lines[i - 1]) if i > 0 else None
            if v is not None:
                if ln == "关注数":
                    extra["follows"] = v
                elif ln in ("粉丝数", "粉丝"):
                    fans = v
                else:
                    extra["total_likes_collects"] = v
        # 近7日指标
        for key, label in [("exposure", "曝光数"), ("views", "观看数"), ("likes", "点赞数"),
                           ("comments", "评论数"), ("collects", "收藏数"), ("shares", "分享数"),
                           ("net_fans", "净涨粉"), ("new_follows", "新增关注"), ("cancel_follows", "取消关注"),
                           ("home_visitors", "主页访客")]:
            if ln == label and i + 1 < len(lines):
                v = lines[i + 1].split("\n")[0].strip()
                if v and not v.startswith("环比"):
                    num = to_int(v)
                    if num is not None:
                        extra.setdefault("last7", {})[key] = num
    if fans is None:
        # 兜底：粘连形式（如『粉丝 20』）
        m = re.search(r"(?:粉丝数|粉丝)\s*：?\s*(\d[\d,]*)", body)
        if m:
            fans = to_int(m.group(1))
    return fans, extra


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "xiaohongshu_uploader"))
    print(json.dumps(r, ensure_ascii=False, indent=2))
