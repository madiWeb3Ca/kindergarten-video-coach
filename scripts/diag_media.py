#!/usr/bin/env python3
"""诊断前置：扫描目录内视频，一次出元数据、切点、响度清单（json）。

不硬编码片名；时长、分辨率、帧率、编码全部走 ffprobe 实测，不手填。

用法：
  python diag_media.py scan --dir <片子目录> [--out <报告.json>] [--threshold 0.25] [--kind raw|finished|unknown]

输出：每条片一组，含 duration/width/height/fps/orientation/codec、
segments/avg_shot_s/cuts、mean_db/max_db、kind（实录素材／成片／未标明）。
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ffmpeg  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scan"])
    ap.add_argument("--dir", required=True, help="片子所在目录")
    ap.add_argument("--out", help="报告 json 落点；默认 04_技术中间件/media_report.json")
    ap.add_argument("--threshold", type=float, default=0.25, help="场景切点灵敏度")
    ap.add_argument("--kind", choices=["raw", "finished", "unknown"], default="unknown",
                    help="raw=未剪实录素材，finished=成片，unknown=未标明；脚本不臆断")
    args = ap.parse_args()

    videos = _ffmpeg.scan_videos(args.dir)
    if not videos:
        print("目录内未找到视频（支持 mp4/mov/m4v/avi）：%s" % args.dir)
        sys.exit(0)

    report = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
              "source_dir": os.path.abspath(args.dir), "videos": {}}

    for v in videos:
        stem = os.path.splitext(os.path.basename(v))[0]
        meta = _ffmpeg.probe_meta(v)
        cuts = _ffmpeg.scene_cuts(v, args.threshold)
        loud = _ffmpeg.loudness(v)
        report["videos"][stem] = {
            "file": os.path.basename(v),
            "kind": args.kind,
            "meta": meta,
            "cuts": cuts,
            "loudness": loud,
        }
        print("%-28s %6.1fs  %s  %2d 段  均镜 %4.1fs  响度 %s/%s dB" % (
            stem, meta["duration"], meta["orientation"], cuts["segments"],
            cuts["avg_shot_s"], loud["mean_db"], loud["max_db"]))

    if args.out:
        out = args.out
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    else:
        mid = os.path.join(os.path.dirname(os.path.abspath(args.dir)), "04_技术中间件")
        os.makedirs(mid, exist_ok=True)
        out = os.path.join(mid, "media_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("报告已写：%s" % out)


if __name__ == "__main__":
    main()
