# -*- coding: utf-8 -*-
"""数据存储：SQLite 快照库（作品表 + 粉丝表）"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "stats.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_at TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    pub_datetime TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    collects INTEGER,
    shares INTEGER,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_works_platform ON works(platform, fetch_at);
CREATE TABLE IF NOT EXISTS fans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_at TEXT NOT NULL,
    platform TEXT NOT NULL,
    fans INTEGER,
    follows INTEGER,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_fans_platform ON fans(platform, fetch_at);
"""


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(SCHEMA)


def save_snapshot(platform, works, fans=None, follows=None, extra=None):
    """保存一次采集快照。works=[{title,pub_datetime,views,likes,comments,collects,shares}...]"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock, _conn() as conn:
        for w in works:
            conn.execute(
                "INSERT INTO works(fetch_at,platform,title,pub_datetime,views,likes,comments,collects,shares,raw) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (now, platform, w.get("title"), w.get("pub_datetime"),
                 w.get("views"), w.get("likes"), w.get("comments"),
                 w.get("collects"), w.get("shares"),
                 json.dumps(w, ensure_ascii=False)[:4000]),
            )
        conn.execute("INSERT INTO fans(fetch_at,platform,fans,follows,extra) VALUES(?,?,?,?,?)",
                     (now, platform, fans, follows,
                      json.dumps(extra or {}, ensure_ascii=False)[:4000]))


def latest_snapshot(platform=None):
    """最新一次采集的作品快照（按 fetch_at 分组取每平台最新）"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT w.* FROM works w "
            "JOIN (SELECT platform, MAX(fetch_at) m FROM works GROUP BY platform) t "
            "ON w.platform=t.platform AND w.fetch_at=t.m "
            + (f"WHERE w.platform=? " if platform else "")
            + "ORDER BY w.platform, w.pub_datetime DESC",
            (platform,) if platform else ()).fetchall()
        out = {}
        for r in rows:
            out.setdefault(r["platform"], []).append({k: r[k] for k in r.keys()})
        return out


def latest_fans():
    """最新粉丝快照 per platform + 前一条用于计算涨粉"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT platform, fetch_at, fans, follows, extra FROM fans "
            "ORDER BY fetch_at ASC").fetchall()
    latest, prev = {}, {}
    for r in rows:
        p = r["platform"]
        prev[p] = latest.get(p)
        latest[p] = r
    out = {}
    for p, r in latest.items():
        d = {"fetch_at": r["fetch_at"], "fans": r["fans"], "follows": r["follows"],
             "extra": json.loads(r["extra"] or "{}")}
        if prev.get(p):
            d["fans_delta"] = (r["fans"] or 0) - (prev[p]["fans"] or 0) if (r["fans"] is not None and prev[p]["fans"] is not None) else None
            d["prev_fetch_at"] = prev[p]["fetch_at"]
        else:
            d["fans_delta"] = None
        out[p] = d
    return out


def last_collect_time():
    with _conn() as conn:
        r = conn.execute("SELECT MAX(fetch_at) m FROM fans").fetchone()
        return r["m"] if r and r["m"] else None


def fans_history(platform, limit=60):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT fetch_at, fans, follows FROM fans WHERE platform=? ORDER BY fetch_at DESC LIMIT ?",
            (platform, limit)).fetchall()
    return [{"fetch_at": r["fetch_at"], "fans": r["fans"], "follows": r["follows"]} for r in rows]


def work_history(keyword=None, limit=400):
    """某视频（标题模糊匹配）在各平台的历史数据序列（按 fetch_at 升序）。
    返回 {platform: [{fetch_at,title,views,likes,comments,collects,shares}...]} —— 用于单条视频趋势。"""
    with _conn() as conn:
        if keyword:
            rows = conn.execute(
                "SELECT fetch_at,platform,title,pub_datetime,views,likes,comments,collects,shares "
                "FROM works WHERE title LIKE ? ORDER BY fetch_at ASC",
                (f"%{keyword}%",)).fetchall()
        else:
            rows = conn.execute(
                "SELECT fetch_at,platform,title,pub_datetime,views,likes,comments,collects,shares "
                "FROM works ORDER BY fetch_at DESC LIMIT ?", (limit,)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["platform"], []).append({
            "fetch_at": r["fetch_at"], "title": r["title"], "pub_datetime": r["pub_datetime"],
            "views": r["views"], "likes": r["likes"], "comments": r["comments"],
            "collects": r["collects"], "shares": r["shares"],
        })
    return out


def video_titles(platform=None):
    """当前已知视频标题（按受欢迎程度排序：出现最多/最新）"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT title, COUNT(*) c, MAX(fetch_at) m FROM works "
            + (f"WHERE platform=? " if platform else "")
            + "GROUP BY title ORDER BY m DESC LIMIT 200").fetchall()
    return [{"title": r["title"], "seen": r["c"], "last": r["m"]} for r in rows]
