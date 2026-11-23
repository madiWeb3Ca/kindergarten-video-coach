#!/usr/bin/env python3
"""环境探测：开工前先摸清工具链与本地转写可用性，再决定走哪条 ASR 路径。

输出 json 分级：ready / degraded / missing。本脚本只探测，不下载模型、不自动补装。

ASR 决策树（配合 main-prompt）：
  1. 模型直收音频（工具自带转写）→ 优先；
  2. 直收不可用：本地 ffmpeg 分离 16kHz 单声道音轨 → 云端转写；
  3. 云端也不可用：报告只记录可观察的声音现象（人声、环境声、响度），
     不编造台词，不填听写。

用法：
  python env_probe.py probe [--out <json>]
"""

import argparse
import importlib
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ffmpeg  # noqa: E402

WHISPER_CACHE = [
    os.path.expanduser(r"~\AppData\Local\whisper"),
    os.path.expanduser(r"~\.cache\whisper"),
]


def _check_bin(name):
    try:
        path = name()
        return {"status": "ready", "path": path}
    except SystemExit as e:
        return {"status": "missing", "msg": str(e)}


def _check_module(mod):
    try:
        importlib.import_module(mod)
        return {"status": "ready"}
    except ImportError:
        return {"status": "missing", "msg": "未安装 %s" % mod}


def _whisper():
    mod = _check_module("faster_whisper")
    if mod["status"] != "ready":
        return {"status": "missing", "note": "本地转写包不可用", "detail": mod.get("msg")}
    has_model = any(os.path.isdir(c) and os.listdir(c) for c in WHISPER_CACHE if os.path.isdir(c))
    if not has_model:
        return {"status": "degraded", "note": "包已装但模型权重未下载；本地转写不可用，走云端兜底"}
    return {"status": "ready", "note": "本地模型缓存存在，实测转写前仍需先跑小样验证"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["probe"])
    ap.add_argument("--out")
    args = ap.parse_args()

    report = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": _check_bin(_ffmpeg.ffmpeg_path),
        "ffprobe": _check_bin(_ffmpeg.ffprobe_path),
        "pillow": _check_module("PIL"),
        "openpyxl": _check_module("openpyxl"),
        "local_asr": _whisper(),
        "asr_policy": "直收优先 → 本地分离音轨上云转写 → 不可用只记声音现象，不编台词",
    }
    worst = "ready"
    for k, v in report.items():
        if isinstance(v, dict) and v.get("status") == "missing":
            worst = "missing"
        elif isinstance(v, dict) and v.get("status") == "degraded" and worst != "missing":
            worst = "degraded"
    report["overall"] = worst

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
