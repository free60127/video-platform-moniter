# -*- coding: utf-8 -*-
"""独立采集进程（每平台一个，隔离 Chromium/browser 实例）：
python -m collector.collect_cli <platform>
日志打印到 stdout（供 Flask 服务转发进日志轮询），采集结果直接写入 SQLite（store）。"""
import sys

from . import run_all
from store import init_db, save_snapshot

if __name__ == "__main__":
    plats = sys.argv[1:] or None
    init_db()
    res = run_all(plats)
    save_ok = []
    for pf, r in res.items():
        if r.get("ok"):
            save_snapshot(pf, r["works"], fans=r.get("fans"),
                          follows=r.get("extra", {}).get("follows"), extra=r.get("extra"))
            save_ok.append(pf)
        else:
            print(f"[{pf}] 采集失败: {r.get('error')}")
    print(f"—— 采集完成: {'/'.join(save_ok) if save_ok else '无成功平台'} ——")
