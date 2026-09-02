# -*- coding: utf-8 -*-
"""全平台跨屏数据统计器 - Flask 看板服务（127.0.0.1:8766）"""
import builtins
import json
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request, send_from_directory

from collector import run_all
from store import (init_db, save_snapshot, latest_snapshot, latest_fans,
                   last_collect_time, fans_history, DB_PATH)

app = Flask(__name__, static_folder="templates", static_url_path="")

LOG_Q = deque(maxlen=3000)   # 历史环形
LOG_SEQ = 0                  # 全局序号
LOG_LOCK = threading.Lock()
_orig_print = builtins.print


def log_line(msg):
    global LOG_SEQ
    stripped = str(msg).strip()
    if not stripped:
        return
    with LOG_LOCK:
        LOG_SEQ += 1
        LOG_Q.append((LOG_SEQ, datetime.now().strftime("%H:%M:%S"), stripped))
    _orig_print(stripped, flush=True)


# 转发采集器日志到队列
def _capture_print(*args, **kwargs):
    _orig_print(*args, **kwargs)
    txt = " ".join(str(a) for a in args)
    if txt and "=====" not in txt:
        log_line(txt)
builtins.print = _capture_print


def _worker(platforms=None):
    try:
        res = run_all(platforms)
        save_ok = []
        for pf, r in res.items():
            if r.get("ok"):
                save_snapshot(pf, r["works"], fans=r.get("fans"),
                              follows=r.get("extra", {}).get("follows"), extra=r.get("extra"))
                save_ok.append(pf)
            else:
                log_line(f"[{pf}] 采集失败: {r.get('error')}")
        log_line(f"—— 采集完成: {'/'.join(save_ok) if save_ok else '无成功平台'} ——")
    except Exception as e:
        log_line(f"采集异常: {type(e).__name__}: {e}")


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/api/dashboard")
def dashboard():
    snap = latest_snapshot()
    fans = latest_fans()
    groups = {}
    platforms = ["douyin", "kuaishou", "tencent", "xiaohongshu", "bilibili"]
    names = {"douyin": "抖音", "kuaishou": "快手", "tencent": "腾讯视频号",
             "xiaohongshu": "小红书", "bilibili": "B站"}
    for pf in platforms:
        groups[pf] = {
            "name": names.get(pf, pf),
            "works": snap.get(pf, []),
            "fans_info": fans.get(pf, {"fans": None, "fans_delta": None, "extra": {}}),
            "history": fans_history(pf, 45),
        }
    return jsonify({
        "last_collect": last_collect_time(),
        "groups": groups,
        "platforms": platforms,
    })


@app.route("/api/collect", methods=["POST"])
def collect():
    body = request.get_json(silent=True) or {}
    platforms = body.get("platforms")
    t = threading.Thread(target=_worker, args=(platforms,), daemon=True)
    t.start()
    return jsonify({"ok": True, "msg": "采集已启动"})


@app.route("/api/logs", methods=["GET"])
def logs():
    idx = int(request.args.get("idx", 0))
    with LOG_LOCK:
        items = [(s, tm, msg) for (s, tm, msg) in LOG_Q if s > idx]
        last = LOG_SEQ
    return jsonify({"items": items, "last": last})


if __name__ == "__main__":
    init_db()
    if not DB_PATH.exists() or last_collect_time() is None:
        log_line("首次启动，自动采集一次…")
        threading.Thread(target=_worker, daemon=True).start()
    # 每日自动采集：每 6 小时检查一次，距上次采集 >20 小时则采
    def _daily_check():
        while True:
            time.sleep(3600 * 6)
            t = last_collect_time()
            if t is None:
                continue
            last_dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_dt).total_seconds() > 20 * 3600:
                log_line("每日自动采集触发…")
                threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_daily_check, daemon=True).start()
    log_line("统计器已启动: http://127.0.0.1:8766")
    app.run(host="127.0.0.1", port=8766, debug=False, use_reloader=False)
