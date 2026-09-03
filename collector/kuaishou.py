# -*- coding: utf-8 -*-
"""快手采集：作品管理列表（标题/播放/点赞/评论）—— Playwright"""
import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

URL = "https://cp.kuaishou.com/article/manage/video"
HOME = "https://cp.kuaishou.com/profile"
# 用户长 ID（从 App 分享链接跳转 URL 的 userId 参数得出：3xp6xq5bwy736vw）
# www.kuaishou.com 个人主页（需 ks_web 登录态才能看粉丝数）
WEB_PROFILE = "https://www.kuaishou.com/profile/3xp6xq5bwy736vw"
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
            for attempt in (1, 2):
                try:
                    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    log(f"[kuaishou] 打开作品管理超时({str(e)[:50]}), 重试…")
            body = ""
            prev = ""
            stable = 0
            for i in range(25):
                await page.wait_for_timeout(2000)
                body = await page.evaluate("() => document.body.innerText")
                if not body.strip():
                    # 页面还在加载：空 body 不视为稳定
                    stable = 0
                    continue
                if body == prev:
                    stable += 1
                    if stable >= 3:
                        break
                else:
                    stable = 0
                prev = body
            lines = [ln.strip() for ln in body.split("\n")]
            lines = [ln for ln in lines if ln]
            out["works"] = _parse(lines)
            # 首页数据概览：昨日播放/点赞/净增粉丝/评论/分享（快手 CP 后台不展示总粉丝数）
            hbody = ""
            try:
                await page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                for i in range(10):
                    await page.wait_for_timeout(2000)
                    hbody = await page.evaluate("() => document.body.innerText")
                    if "净增粉丝量" in hbody:
                        break
                out["extra"] = _parse_overview(hbody)
            except Exception as e:
                log(f"[kuaishou] 数据概览抓取失败: {e}")
            # 总粉丝数：www.kuaishou.com 登录态主页（需 ks_web 登录态）
            # 登录态可能存放在两个位置（stats-platform 自有目录 或 与上传器 cookies 同级）
            web_state = None
            ks_candidates = [
                Path(__file__).resolve().parent.parent / "cookies" / "ks_web" / "account.json",
                cookies_dir.parent / "ks_web" / "account.json",
            ]
            for cand in ks_candidates:
                if cand.exists():
                    web_state = cand
                    break
            if web_state:
                try:
                    await page.context.close()
                except Exception:
                    pass
                ctx2 = await browser.new_context(storage_state=str(web_state),
                                                 viewport={"width": 1280, "height": 900}, locale="zh-CN",
                                                 user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                             "Chrome/136.0.0.0 Safari/537.36"))
                await clean_ctx(ctx2)
                page2 = await ctx2.new_page()
                try:
                    await asyncio.wait_for(page2.goto(WEB_PROFILE, wait_until="domcontentloaded"), 45)
                except Exception as e:
                    log(f"[kuaishou] 主页 goto 异常: {str(e)[:60]}")
                for i in range(8):
                    await page2.wait_for_timeout(2000)
                    try:
                        wb = await asyncio.wait_for(
                            page2.evaluate("() => document.body ? document.body.innerText : ''"), 8)
                    except Exception:
                        continue
                    if "粉丝" in wb:
                        break
                out["fans"] = _parse_web_profile(wb)
                await ctx2.close()
            if out["fans"] is None:
                # 兜底：手动口径（来自快手 App「我」页，用户可改 fans_manual.txt）
                for manual_p in [Path(__file__).resolve().parent.parent / "cookies" / "ks_web" / "fans_manual.txt",
                                 cookies_dir.parent / "ks_web" / "fans_manual.txt"]:
                    if manual_p.exists():
                        try:
                            v = to_int(manual_p.read_text(encoding="utf-8").strip())
                            if v is not None:
                                out["fans"] = v
                                log("[kuaishou] 使用手动粉丝数(快手App口径)")
                                break
                        except Exception:
                            pass
            out["ok"] = True
            log(f"[kuaishou] ✓ 作品 {len(out['works'])} 条, 粉丝 {out['fans']}")
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


def _parse_overview(body):
    """首页数据概览卡片：
    播放量 昨日 +837 846 / 点赞量 昨日 +5 5 / 净增粉丝量 昨日 +2 2
    完播率 0% / 评论量 昨日 +1 2 / 分享量 昨日 +0 0"""
    extra = {}
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    keys = {"播放量": "new_views", "点赞量": "new_likes", "净增粉丝量": "net_fans",
            "评论量": "new_comments", "分享量": "new_shares"}
    for i, ln in enumerate(lines):
        if ln in keys:
            # 结构：标签 → 昨日 → 增量(+N) → 总量
            total = to_int(lines[i + 3]) if i + 3 < len(lines) else None
            if total is not None:
                extra.setdefault("overview", {})[keys[ln]] = total
    return extra


def _parse_web_profile(body):
    """www.kuaishou.com 个人主页（登录态）：行如『关注 2 粉丝 5 获赞 8』或『5 粉丝』"""
    if not body or "粉丝" not in body:
        return None
    # 优先「粉丝 N」（页面实际格式：关注 2 粉丝 5 获赞 8）
    m = re.search(r"粉丝\s*：?\s*(\d[\d,]*)", body)
    if not m:
        # 兜底「N 粉丝」
        m = re.search(r"(\d[\d,]*)\s*粉丝", body)
    if m:
        v = to_int(m.group(1))
        if v is not None:
            return v
    # 兜底：粉丝独占一行，取上一行数字
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        if ln == "粉丝" and i > 0:
            v = to_int(lines[i - 1])
            if v is not None:
                return v
    return None


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "ks_uploader"))
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
