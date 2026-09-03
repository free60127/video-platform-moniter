# -*- coding: utf-8 -*-
"""全平台跨屏数据统计器 - Flask 看板服务（127.0.0.1:8766）"""
import builtins
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request, send_from_directory

from collector import MODULES, run_all
from store import (init_db, save_snapshot, latest_snapshot, latest_fans,
                   last_collect_time, fans_history, DB_PATH, work_history, video_titles)
import notify as NOTIFY

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


PLATFORM_NAMES = {"bilibili": "B站", "kuaishou": "快手", "douyin": "抖音",
                  "tencent": "视频号", "xiaohongshu": "小红书"}


def _worker(platforms=None):
    """逐平台独立子进程采集（隔离 Chromium 实例，防止 2GiB 小内存服务器多实例退化）。
    Popen 逐行实时转发日志，避免 capture 管道缓冲问题。结束时发微信日报/失败告警。"""
    ok_plats, fail_info = [], {}
    try:
        cwd = str(Path(__file__).resolve().parent)
        plats = platforms or list(MODULES.keys())
        for pf in plats:
            cmd = [sys.executable, "-B", "-m", "collector.collect_cli", pf]
            pf_ok = None
            try:
                proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace")
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        log_line(line)
                    if line.startswith(f"[{pf}] ✓"):
                        pf_ok = True
                    elif line.startswith(f"[{pf}] ✗") or line.startswith(f"[{pf}] 采集失败"):
                        pf_ok = False
                try:
                    proc.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    log_line(f"[{pf}] 采集超时(30min)，已终止")
                    pf_ok = False
            except Exception as e:
                log_line(f"[{pf}] 子进程错误: {type(e).__name__}: {e}")
                pf_ok = False
                continue
            if proc.returncode not in (0, None):
                log_line(f"[{pf}] 子进程异常 exit={proc.returncode}")
                pf_ok = False
            if pf_ok:
                ok_plats.append(pf)
            else:
                fail_info[pf] = f"采集失败(exit={proc.returncode})"
    except Exception as e:
        log_line(f"采集异常: {type(e).__name__}: {e}")
    # 微信日报/失败告警
    try:
        _notify_collect(ok_plats, fail_info)
    except Exception as e:
        log_line(f"通知发送失败: {e}")


def _notify_collect(ok_plats, fail_info):
    fans = latest_fans()
    lines = [f"**采集日报 · {datetime.now().strftime('%m-%d %H:%M')}**"]
    names = PLATFORM_NAMES
    for pf in list(MODULES.keys()):
        f = fans.get(pf, {})
        nm = names.get(pf, pf)
        if pf in fail_info:
            lines.append(f"- ❌ {nm}：**{fail_info[pf]}**")
        else:
            delta = f.get("fans_delta")
            fan = f.get("fans")
            dstr = f"（涨 {delta:+d}）" if delta is not None else ""
            fstr = f"{fan}" if fan is not None else "--"
            lines.append(f"- ✅ {nm}：粉丝 {fstr}{dstr}")
    if fail_info:
        lines.append("")
        lines.append("> 失败平台将在下次自动采集时重试（自动保留上次成功数据）")
    NOTIFY.send("✅ 采集日报完成" if not fail_info else "⚠️ 采集日报：部分失败",
                "\n".join(lines), log=log_line)


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


@app.route("/api/videos")
def api_videos():
    """已知视频标题列表（供趋势页选择）"""
    return jsonify({"titles": video_titles()})


@app.route("/api/trend")
def api_trend():
    """单条视频趋势：?video=标题关键词 → {platform: [{fetch_at,views,likes,...}...]}"""
    q = request.args.get("video", "").strip()
    if not q:
        return jsonify({"error": "缺少 video 参数"}), 400
    return jsonify({"video": q, "history": work_history(q)})


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
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=8766, debug=False, use_reloader=False)
