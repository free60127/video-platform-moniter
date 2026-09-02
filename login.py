# -*- coding: utf-8 -*-
"""登录态采集工具：打开浏览器 → 用户扫码/登录 → 自动保存 storage_state 到 cookies/<platform>_uploader/account.json

用法: python login.py douyin
      python login.py kuaishou tencent xiaohongshu
登录成功后页面会提示"登录成功，请关闭浏览器窗口"；关闭窗口即保存。最长等待 10 分钟。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

COOKIES_ROOT = Path(__file__).resolve().parent / "cookies"

# 各平台创作者中心入口（登录后会跳转到该域）
ENTRIES = {
    "douyin": "https://creator.douyin.com/creator-micro/content/manage",
    "kuaishou": "https://cp.kuaishou.com/article/manage/video",
    "tencent": "https://channels.weixin.qq.com/platform/post/list",
    "xiaohongshu": "https://creator.xiaohongshu.com/new/note-manager",
}
# 判定"已登录"的特征文本
LOGIN_OK = {
    "douyin": ["内容管理", "作品发布"],
    "kuaishou": ["作品管理", "发布作品"],
    "tencent": ["视频号·助手", "内容管理"],
    "xiaohongshu": ["笔记管理", "发布笔记"],
}


async def login_one(platform, browser):
    entry = ENTRIES[platform]
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 860},
        locale="zh-CN",
    )
    page = await ctx.new_page()
    print(f"[{platform}] 打开 {entry}\n请在弹出的浏览器中扫码/登录，成功后关闭窗口（最多等 10 分钟）")
    try:
        await page.goto(entry, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"[{platform}] 打开页面异常（忽略，继续等待登录）: {e}")
    saved = False
    for i in range(120):  # 10 分钟
        await page.wait_for_timeout(5000)
        try:
            if page.is_closed():
                break
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            if any(k in text for k in LOGIN_OK.get(platform, [])):
                saved = True
                break
        except Exception:
            break
    try:
        if not saved:
            # 用户关闭窗口 = 允许保存已建立的登录态
            await page.wait_for_timeout(3000)
        out_dir = COOKIES_ROOT / f"{platform}_uploader"
        out_dir.mkdir(parents=True, exist_ok=True)
        await ctx.storage_state(path=str(out_dir / "account.json"))
        print(f"[{platform}] cookie 已保存到 {out_dir / 'account.json'}")
    except Exception as e:
        print(f"[{platform}] 保存失败: {e}")
    finally:
        try:
            await ctx.close()
        except Exception:
            pass


async def main():
    plats = sys.argv[1:]
    if not plats:
        print("用法: python login.py douyin|kuaishou|tencent|xiaohongshu [...]")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        for platform in plats:
            if platform not in ENTRIES:
                print(f"未知平台 {platform}")
                continue
            await login_one(platform, browser)
        await browser.close()
    print("全部完成。可运行 app.py 启动看板，或 python collector 手动采集。")


if __name__ == "__main__":
    asyncio.run(main())
