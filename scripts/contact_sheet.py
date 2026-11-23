#!/usr/bin/env python3
"""观察帧接触览图：按固定间隔抽帧，拼带时间码的网格表（教练侧自检用，不进交付件）。

用法：
  python contact_sheet.py make --video <片.mp4> [--interval 5] [--cell 360] [--cols 4] [--out-dir <dir>]

输出：out-dir/<stem>/f_###.jpg 与 sheet_1.jpg、sheet_2.jpg ……
"""

import argparse
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ffmpeg  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("缺 Pillow：请先在运行环境安装 pillow，再跑接触览图。")


def fmt(t):
    return "%d:%02d" % (int(t // 60), int(t % 60))


def font():
    for f in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(f):
            return ImageFont.truetype(f, 18)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["make"])
    ap.add_argument("--video", required=True)
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--cell", type=int, default=360)
    ap.add_argument("--cols", type=int, default=None,
                    help="网格列数；不传时按片子宽高比自动选：竖版 9:16 用 2 列，横版 16:9 用 4 列")
    ap.add_argument("--out-dir", help="默认 04_技术中间件/<stem>")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        raise SystemExit("片子不存在：%s" % args.video)
    stem = os.path.splitext(os.path.basename(args.video))[0]
    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(args.video))),
        "04_技术中间件", stem)
    fdir = os.path.join(out_dir, "frames_obs")
    os.makedirs(fdir, exist_ok=True)

    meta = _ffmpeg.probe_meta(args.video)
    if args.cols is None:
        args.cols = 2 if meta["orientation"] == "9:16" else 4
    ff = _ffmpeg.ffmpeg_path()
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", args.video,
                    "-vf", "fps=1/%d,scale=%d:-2" % (args.interval, args.cell),
                    "-q:v", "4", os.path.join(fdir, "f_%03d.jpg")], check=True)

    frames = sorted(os.listdir(fdir))
    imgs = []
    for i, fn in enumerate(frames):
        t = i * args.interval
        im = Image.open(os.path.join(fdir, fn)).convert("RGB")
        bar = Image.new("RGB", (args.cell, 28), (40, 40, 40))
        ImageDraw.Draw(bar).text((8, 4), fmt(t), fill=(255, 220, 120), font=font())
        combo = Image.new("RGB", (args.cell, im.height + 28), (255, 255, 255))
        combo.paste(bar, (0, 0))
        combo.paste(im, (0, 28))
        imgs.append(combo)

    per = args.cols * 6
    for s in range(math.ceil(len(imgs) / per)):
        batch = imgs[s * per:(s + 1) * per]
        rows = math.ceil(len(batch) / args.cols)
        ch = max(i.height for i in batch)
        sheet = Image.new("RGB", (args.cols * args.cell, rows * ch), (230, 230, 230))
        for j, im in enumerate(batch):
            sheet.paste(im, ((j % args.cols) * args.cell, (j // args.cols) * ch))
        sheet.save(os.path.join(out_dir, "sheet_%d.jpg" % (s + 1)), quality=82)

    print("观察帧 %d 张，接触览图 %d 张：%s" % (
        len(frames), math.ceil(len(imgs) / per), out_dir))
    print("时长 %.1fs，间隔 %ds" % (meta["duration"], args.interval))


if __name__ == "__main__":
    main()
