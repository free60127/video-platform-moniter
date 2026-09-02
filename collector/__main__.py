# -*- coding: utf-8 -*-
"""python -m collector [platform ...]"""
import json
import sys

from . import run_all

if __name__ == "__main__":
    plats = sys.argv[1:] if len(sys.argv) > 1 else None
    print(json.dumps(run_all(plats), ensure_ascii=False, indent=2))
