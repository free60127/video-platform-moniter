# -*- coding: utf-8 -*-
"""B站采集：member API（archives 列表 + view 统计）+ 账号累计统计 —— 纯 requests，无需浏览器"""
import json
import re
import time

import requests

from .base import load_cookie, log

BASE = "https://member.bilibili.com/x/web"
VIEW = "https://api.bilibili.com/x/web-interface/view"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://member.bilibili.com/",
}


def _cookies_from_biliup(data):
    ck = data.get("cookie_info", {}).get("cookies", [])
    if not ck and data.get("cookies"):  # storage_state 兼容
        ck = data["cookies"]
    return {c["name"]: c["value"] for c in ck}


def collect(cookies_dir) -> dict:
    data = load_cookie(cookies_dir / "account.json")
    jar = _cookies_from_biliup(data)
    out = {"platform": "bilibili", "works": [], "fans": None, "extra": {}, "ok": False, "error": None}
    try:
        r = requests.get(f"{BASE}/archives", params={"status": "is_pub", "pn": 1, "ps": 30},
                         cookies=jar, headers=HEADERS, timeout=20)
        body = r.json()
        if body.get("code") != 0:
            out["error"] = f"archives API: {body.get('code')} {body.get('message')}"
            log(f"[bilibili] archives API 失败: {out['error']}")
            return out
        data_list = body.get("data", {})
        # 兼容两种字段：archives（旧）与 arc_audits[].Archive（新）
        entries = []
        for arc in (data_list.get("archives") or []) + [a.get("Archive") for a in (data_list.get("arc_audits") or []) if a.get("Archive")]:
            entries.append(arc)
        seen = set()
        for arc in entries:
            bvid = arc.get("bvid")
            if not bvid or bvid in seen:
                continue
            seen.add(bvid)
            pub = None
            if arc.get("pubdate"):
                pub = time.strftime("%Y-%m-%d %H:%M", time.localtime(arc["pubdate"]))
            elif arc.get("ftime"):
                pub = time.strftime("%Y-%m-%d %H:%M", time.localtime(arc["ftime"]))
            w = {"title": arc.get("title", ""), "pub_datetime": pub,
                 "views": None, "likes": None, "comments": None, "collects": None, "shares": None}
            try:
                vr = requests.get(VIEW, params={"bvid": bvid}, cookies=jar, headers=HEADERS, timeout=15)
                vd = vr.json().get("data") or {}
                st = vd.get("stat", {})
                w["views"] = st.get("view")
                w["likes"] = st.get("like")
                w["comments"] = st.get("reply")
                w["collects"] = st.get("favorite")
                w["shares"] = st.get("share")
                w["pub_datetime"] = w["pub_datetime"] or time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(vd.get("pubdate", 0)))
            except Exception as e:
                log(f"[bilibili] view API {bvid} 失败: {e}")
            out["works"].append(w)
            time.sleep(0.4)
        # 账号累计
        try:
            st = requests.get(f"{BASE}/index/stat", cookies=jar, headers=HEADERS, timeout=15).json().get("data", {})
            out["fans"] = st.get("total_fans")
            out["extra"] = {
                "total_views": st.get("total_click"),
                "total_likes": st.get("total_like"),
                "total_favorites": st.get("total_fav"),
                "total_comments": st.get("total_reply"),
                "total_shares": st.get("total_share"),
                "total_coins": st.get("total_coin"),
                "total_videos": st.get("total_av", st.get("total_videolist")),
            }
        except Exception as e:
            log(f"[bilibili] index/stat 失败: {e}")
        out["ok"] = True
        log(f"[bilibili] ✓ 作品 {len(out['works'])} 条, 粉丝 {out['fans']}")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log(f"[bilibili] ✗ {out['error']}")
    return out
