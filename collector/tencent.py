# -*- coding: utf-8 -*-
"""腾讯视频号采集：首页概览（关注者/视频数/昨日数据）+ 内容管理视频列表 —— Playwright
登录态：持久 profile（profile_tencent，需先跑 启动视频号统计登录.bat 扫码一次）
"""
import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

HOME = "https://channels.weixin.qq.com/platform"
PROFILE = Path(__file__).resolve().parent.parent / "profile_tencent"
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"


async def _evaluate(page, expr):
    """evaluate 带硬超时（本版 Playwright evaluate 不支持 timeout 参数）"""
    return await asyncio.wait_for(page.evaluate(expr), 8)


async def collect(cookies_dir) -> dict:
    out = {"platform": "tencent", "works": [], "fans": None, "extra": {}, "ok": False, "error": None}
    if not PROFILE.exists():
        out["error"] = "profile_tencent 不存在，请先双击 启动视频号统计登录.bat 扫码登录一次"
        log(f"[tencent] ✗ {out['error']}")
        return out
    try:
        async with async_playwright() as p:
            # headed + 窗口移出屏幕：微信对 headless/自动化识别严格，
            # 持久 profile（用户扫码一次）+ 真 headed 指纹最稳；offscreen 不打扰
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE), headless=False,
                executable_path=CHROME,
                viewport={"width": 1440, "height": 900}, locale="zh-CN",
                args=["--window-position=-32000,-32000", "--start-minimized"])
            ctx = browser
            await clean_ctx(ctx)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            # 捕获 XHR：内容管理视频列表接口
            xhr_urls = []

            def on_response(resp):
                try:
                    u = resp.url
                    if "/platform" in u and any(k in u for k in ("post", "video", "list", "finder")):
                        if u not in xhr_urls:
                            xhr_urls.append(u)
                except Exception:
                    pass

            page.on("response", on_response)
            try:
                await asyncio.wait_for(
                    page.goto(HOME, wait_until="domcontentloaded"), 60)
            except Exception as e:
                log(f"[tencent] goto 超时/异常: {str(e)[:60]}")
            body = ""
            for i in range(10):
                await page.wait_for_timeout(2000)
                try:
                    body = await _evaluate(page, "() => document.body.innerText")
                except Exception:
                    continue
                if "关注者" in body and len(body) > 600:
                    break
            found_xhr = None
            # 点击内容管理 → 视频（列表在 iframe: micro/content/post/list）
            try:
                await page.get_by_text("内容管理", exact=False).first.click(timeout=6000)
                await page.wait_for_timeout(5000)
            except Exception as e:
                log(f"[tencent] 点击 内容管理 失败: {str(e)[:80]}")
            try:
                await page.get_by_text("视频", exact=True).first.click(timeout=6000)
                await page.wait_for_timeout(12000)
            except Exception as e:
                log(f"[tencent] 点击 视频 失败: {str(e)[:80]}")
            # 从 iframe 取列表（iframe 出现较慢，轮询等待）
            for wait_i in range(8):
                await page.wait_for_timeout(2000)
                hit = None
                for fr in page.frames:
                    if "micro/content/post/list" in fr.url:
                        hit = fr
                        break
                if hit is None:
                    continue
                try:
                    fbody = await _evaluate(hit, "() => document.body ? document.body.innerText : ''")
                except Exception:
                    continue
                if fbody and len(fbody) > 300:
                    out["works"] = _parse_video_list(
                        [ln.strip() for ln in fbody.split("\n") if ln.strip()])
                    break
            out["fans"], out["extra"] = _parse_home(body)
            out["extra"]["xhr_candidates"] = xhr_urls
            out["ok"] = True
            log(f"[tencent] ✓ 作品 {len(out['works'])} 条, 粉丝 {out['fans']}")
            await ctx.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log(f"[tencent] ✗ {out['error']}")
    return out


def _parse_home(body):
    """首页：『视频5 / 关注者7』粘连行 + 昨日数据"""
    fans = None
    extra = {}
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        m = re.search(r"视频\s*(\d+)", ln)
        if m and "视频号" not in ln and "ID" not in ln:
            extra.setdefault("video_count", int(m.group(1)))
        m2 = re.search(r"关注者\s*(\d+)", ln)
        if m2 and fans is None:
            fans = int(m2.group(1))
        if ln == "视频号ID:" and i + 1 < len(lines):
            extra["video_id"] = lines[i + 1]
    # 昨日数据
    y = {}
    for i, ln in enumerate(lines):
        if ln in ("净增关注", "新增播放", "新增评论", "新增") and i + 1 < len(lines):
            v = to_int(lines[i + 1])
            if v is not None:
                key = "new_fans" if ln == "净增关注" else ("new_views" if ln == "新增播放" else ("new_comments" if ln == "新增评论" else "new_interactions"))
                y[key] = v
    if y:
        extra["yesterday"] = y
    return fans, extra


def _parse_video_list(lines):
    """内容管理 iframe 列表：标题 → 日期 → 5 数字（播放/点赞/评论/转发/收藏）→ 操作按钮组"""
    works = []
    n = len(lines)
    DATE_RE = re.compile(r"^\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}$")
    SKIP_HEAD = {"视频管理", "特效创作工具", "发表视频", "合集 (0)"}
    i = 0
    while i < n:
        if DATE_RE.match(lines[i]):
            title = lines[i - 1] if i - 1 >= 0 else ""
            vals = []
            j = i + 1
            while j < n and len(vals) < 5:
                if re.fullmatch(r"\d+", lines[j]):
                    vals.append(int(lines[j]))
                elif lines[j] in ("置顶", "分享", "弹幕管理", "评论管理", "修改描述和封面", "可见权限", "删除"):
                    break
                j += 1
            works.append({"title": title, "pub_datetime": lines[i],
                          "views": vals[0] if len(vals) > 0 else None,
                          "likes": vals[1] if len(vals) > 1 else None,
                          "comments": vals[2] if len(vals) > 2 else None,
                          "collects": vals[4] if len(vals) > 4 else None,
                          "shares": vals[3] if len(vals) > 3 else None})
        i += 1
    dedup = []
    seen = set()
    for w in reversed(works):
        if w["title"] and w["title"] not in seen:
            seen.add(w["title"])
            dedup.append(w)
    return dedup if works else []


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    import json
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "tencent_uploader"))
    print(json.dumps(r, ensure_ascii=False, indent=2))
