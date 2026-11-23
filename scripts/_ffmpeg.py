#!/usr/bin/env python3
"""ffmpeg / ffprobe 公共查找与封装（脚本内部复用，不单独交付）。

查找顺序：PATH 环境变量 → 常见安装位置 → 调用方显式传入的路径。
找不到时抛 SystemExit 给出人话提示，不甩 Traceback。
"""

import os
import re
import shutil
import subprocess

FFMPEG_CANDIDATES = [
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    "/usr/local/bin",
    "/usr/bin",
]


def _find(bin_name):
    found = shutil.which(bin_name)
    if found:
        return found
    for base in FFMPEG_CANDIDATES:
        cand = os.path.join(base, bin_name + (".exe" if os.name == "nt" else ""))
        if os.path.exists(cand):
            return cand
    raise SystemExit("未找到 %s，请先把 ffmpeg 加入 PATH，或在调用时传入路径。" % bin_name)


def ffmpeg_path():
    return _find("ffmpeg")


def ffprobe_path():
    return _find("ffprobe")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="ignore", **kw)


def probe_meta(video):
    """返回时长(秒)、宽高、帧率、编码、音频采样率与声道。"""
    fp = ffprobe_path()
    r = run([fp, "-v", "error",
             "-show_entries", "format=duration,size,bit_rate",
             "-show_entries", "stream=codec_name,width,height,r_frame_rate,sample_rate,channels",
             "-of", "default=noprint_wrappers=1", video])
    out = r.stderr + r.stdout
    def num(key):
        m = re.search(key + r"=([0-9.]+)", out)
        return m.group(1) if m else None
    duration = float(num("duration") or 0)
    w = int(num("width") or 0)
    h = int(num("height") or 0)
    mfr = re.search(r"r_frame_rate=([0-9]+)/([0-9]+)", out)
    if mfr and int(mfr.group(2)):
        fps = round(int(mfr.group(1)) / int(mfr.group(2)), 2)
    else:
        fps = 0
    codec = re.search(r"codec_name=(\w+)", out)
    sr = num("sample_rate")
    ch = num("channels")
    return {
        "duration": round(duration, 2),
        "width": w, "height": h, "fps": fps,
        "orientation": "9:16" if h >= w else "16:9",
        "codec": codec.group(1) if codec else None,
        "sample_rate": sr, "channels": ch,
        "size_bytes": int(num("size") or 0),
    }


def scene_cuts(video, threshold=0.25):
    """返回切点秒数列表、段数、平均镜长。"""
    ff = ffmpeg_path()
    r = run([ff, "-hide_banner", "-i", video, "-vf",
             "select='gt(scene,%.2f)',showinfo" % threshold, "-f", "null", "-"])
    ts = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr + r.stdout)]
    meta = probe_meta(video)
    segments = len(ts) + 1
    avg = round(meta["duration"] / segments, 1) if segments else 0
    return {"cuts": [round(t, 1) for t in ts], "segments": segments, "avg_shot_s": avg}


def loudness(video):
    """返回 mean / max 响度(dB)；取不到给 None，不编造。"""
    ff = ffmpeg_path()
    r = run([ff, "-hide_banner", "-i", video, "-af", "volumedetect", "-f", "null", "-"])
    out = r.stderr + r.stdout
    mean = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", out)
    mx = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", out)
    return {"mean_db": mean.group(1) if mean else None,
            "max_db": mx.group(1) if mx else None}


def scan_videos(directory, exts=(".mp4", ".mov", ".m4v", ".avi")):
    """扫描目录下的视频文件（不递归子目录），按文件名排序。"""
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, f) for f in sorted(os.listdir(directory))
            if os.path.splitext(f)[1].lower() in exts]
