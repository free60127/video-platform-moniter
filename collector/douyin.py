# -*- coding: utf-8 -*-
"""抖音采集：创作者中心作品管理（播放/点赞/评论/分享/收藏/完播率）—— Playwright"""
import re

from playwright.async_api import async_playwright

from .base import load_cookie, clean_ctx, log, to_int

URL = "https://creator.douyin.com/creator-micro/content/manage"
DATA_URL = "https://creator.douyin.com/creator-micro/data-center/operation"
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
            # 抖音页面加载极慢/间歇性超时：90s × 3 次；全败后仍尝试抓 body（可能部分渲染）
            ok = False
            for attempt in (1, 2, 3):
                try:
                    await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
                    ok = True
                    break
                except Exception as e:
                    log(f"[douyin] 打开作品管理超时({str(e)[:50]}), 第{attempt}次…")
            body = ""
            if ok:
                prev = ""
                stable = 0
                for i in range(25):
                    await page.wait_for_timeout(2000)
                    body = await page.evaluate("() => document.body.innerText")
                    if not body.strip():
                        # 页面还在加载：空 body 不视为稳定，防止提前退出
                        stable = 0
                        continue
                    if body == prev:
                        stable += 1
                        if stable >= 3:
                            break
                    else:
                        stable = 0
                    prev = body
            else:
                # goto 全部超时：页面可能仍在加载，尝试直接读取
                try:
                    body = await page.evaluate("() => document.body.innerText")
                except Exception:
                    body = ""
                if len(body) < 200:
                    raise TimeoutError(f"抖音作品管理页在 3 次 {90000}ms 内未加载 (body={len(body)})")
            lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
            out["works"] = _parse(lines)
            # 数据中心：总粉丝量/粉丝净增/吸粉量/脱粉量 + 数据总览
            try:
                for attempt in (1, 2):
                    try:
                        await page.goto(DATA_URL, wait_until="domcontentloaded", timeout=60000)
                        break
                    except Exception as e:
                        if attempt == 2:
                            raise e
                        log(f"[douyin] 打开数据中心超时({str(e)[:60]}), 重试…")
                for i in range(12):
                    await page.wait_for_timeout(2000)
                    dbody = await page.evaluate("() => document.body.innerText")
                    if "总粉丝量" in dbody:
                        break
                out["fans"], out["extra"] = _parse_data_center(dbody)
            except Exception as e:
                log(f"[douyin] 数据中心抓取失败: {e}")
            out["ok"] = True
            log(f"[douyin] ✓ 作品 {len(out['works'])} 条, 粉丝 {out['fans']}")
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


def _parse_data_center(body):
    """数据中心 /data-center/operation：
    总粉丝量 5 / 粉丝净增 -1 / 吸粉量 0 / 脱粉量 1 / 回访粉丝量 3
    数据总览: 播放量 400 / 互动率/L / 完播率 2.1% / 作品数 4
    作品数据: 总播放量 400 / 总点赞量 7 / 总分享量 0 / 总评论量 6"""
    fans = None
    extra = {}
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        if ln in ("总粉丝量", "粉丝净增", "吸粉量", "脱粉量", "回访粉丝量"):
            v = to_int(lines[i + 1]) if i + 1 < len(lines) else None
            if v is not None:
                if ln == "总粉丝量":
                    fans = v
                else:
                    extra.setdefault("fans_metrics", {})[ln] = v
        if ln in ("总播放量", "总点赞量", "总评论量", "总分享量", "平均播放时长"):
            v = lines[i + 1] if i + 1 < len(lines) else None
            if v:
                if ln == "总播放量":
                    extra["total_views"] = to_int(v)
                elif ln == "总点赞量":
                    extra["total_likes"] = to_int(v)
                elif ln == "总评论量":
                    extra["total_comments"] = to_int(v)
                elif ln == "总分享量":
                    extra["total_shares"] = to_int(v)
                else:
                    extra["avg_play_seconds"] = v
    return fans, extra


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    r = asyncio.run(collect(Path(__file__).resolve().parent.parent.parent / "social-auto-upload" / "cookies" / "douyin_uploader"))
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
