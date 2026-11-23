#!/usr/bin/env python3
"""证据帧抽取、候选比对、定稿核对与清单管理。

安全约定（P0）：
- `pick` 只写本片帧，默认不删除任何旧帧；跨片历史证据帧不受影响。
- 清理只能走 `clean` 子命令，默认 dry-run 列清单写日志，加 `--confirm` 才真删。
- manifest 与帧目录双向核对：登记缺失文件判 hard，目录多帧未登记判 soft。

用法：
  python frame_picker.py pick   --video <片.mp4> --frame-dir <目录> --frames '[{...}]' [--frames-file <json>]
  python frame_picker.py probe  --video <片.mp4> --frame-dir <目录> --secs 0,15,45 [--cell 240]
  python frame_picker.py verify --frame-dir <目录> [--stem <片名>]
  python frame_picker.py check  --frame-dir <目录>
  python frame_picker.py clean  --frame-dir <目录> [--stem <片名>] [--confirm]

frames 清单字段：sec(秒,必填)、t(时间码标签,如 0:15)、width(可选,默认 720)。
"""

import argparse
import datetime
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ffmpeg  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("缺 Pillow：请先在运行环境安装 pillow，再跑帧脚本。")

MANIFEST = "frames_manifest.json"


def manifest_path(frame_dir):
    return os.path.join(frame_dir, MANIFEST)


def load_manifest(frame_dir):
    p = manifest_path(frame_dir)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(frame_dir, man):
    with open(manifest_path(frame_dir), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)


def frame_name(stem, label):
    return "%s_%s.jpg" % (stem, label.replace(":", ""))


def fmt(t):
    return "%d:%02d" % (int(t // 60), int(t % 60))


def font(size=16):
    for f in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def extract(video, sec, out, width):
    ff = _ffmpeg.ffmpeg_path()
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(sec),
                    "-i", video, "-frames:v", "1",
                    "-vf", "scale=%d:-2" % width, "-q:v", "3", out], check=True)


def cmd_pick(args):
    stem = os.path.splitext(os.path.basename(args.video))[0]
    os.makedirs(args.frame_dir, exist_ok=True)
    frames = json.loads(args.frames) if args.frames else json.load(open(args.frames_file, encoding="utf-8"))

    man = load_manifest(args.frame_dir)
    man[stem] = []
    for item in frames:
        sec = float(item["sec"])
        label = item.get("t") or fmt(sec)
        width = int(item.get("width", 720))
        fn = frame_name(stem, label)
        out = os.path.join(args.frame_dir, fn)
        extract(args.video, sec, out, width)
        man[stem].append({"t": label, "sec": sec, "file": fn,
                          "size": os.path.getsize(out)})
    save_manifest(args.frame_dir, man)
    print("已抽 %d 帧 → %s（未删除任何旧帧）" % (len(frames), args.frame_dir))


def _sheet(stem, files, out_path, cell):
    ims = []
    for fp, label in files:
        im = Image.open(fp).convert("RGB")
        w = cell
        h = int(im.height * w / im.width)
        im = im.resize((w, h))
        bar = Image.new("RGB", (w, 22), (40, 40, 40))
        ImageDraw.Draw(bar).text((6, 3), label, fill=(255, 220, 120), font=font())
        c = Image.new("RGB", (w, h + 22), (255, 255, 255))
        c.paste(bar, (0, 0))
        c.paste(im, (0, 22))
        ims.append(c)
    cols = 3
    rows = (len(ims) + cols - 1) // cols
    ch = max(i.height for i in ims)
    sheet = Image.new("RGB", (cols * cell, rows * ch), (230, 230, 230))
    for j, im in enumerate(ims):
        sheet.paste(im, ((j % cols) * cell, (j // cols) * ch))
    sheet.save(out_path, quality=85)


def cmd_probe(args):
    stem = os.path.splitext(os.path.basename(args.video))[0]
    cand_dir = os.path.join(args.frame_dir, "_probe")
    os.makedirs(cand_dir, exist_ok=True)
    secs = [float(x) for x in args.secs.split(",") if x.strip()]
    files = []
    for s in secs:
        fn = os.path.join(cand_dir, "%s_%s.jpg" % (stem, fmt(s).replace(":", "")))
        extract(args.video, s, fn, args.cell)
        files.append((fn, "%s %ss" % (stem, fmt(s))))
    out = os.path.join(cand_dir, stem + "_probe.jpg")
    _sheet(stem, files, out, args.cell)
    print("候选比对表：%s" % out)


def cmd_verify(args):
    man = load_manifest(args.frame_dir)
    targets = [args.stem] if args.stem else list(man.keys())
    for stem in targets:
        items = man.get(stem, [])
        files = [(os.path.join(args.frame_dir, i["file"]), "%s %s" % (stem, i["t"]))
                 for i in items if os.path.exists(os.path.join(args.frame_dir, i["file"]))]
        if not files:
            print("无定稿帧：%s" % stem)
            continue
        out = os.path.join(args.frame_dir, stem + "_verify.jpg")
        _sheet(stem, files, out, 320)
        print("定稿核对表：%s" % out)


def cmd_check(args):
    man = load_manifest(args.frame_dir)
    hard, soft = [], []
    on_disk = {}
    for f in glob.glob(os.path.join(args.frame_dir, "*.jpg")):
        on_disk[os.path.basename(f)] = os.path.getsize(f)
    registered = {i["file"] for v in man.values() for i in v}
    for fn in on_disk:
        if fn not in registered:
            soft.append({"level": "soft", "msg": "帧已落盘但清单未登记: %s" % fn})
    for stem, items in man.items():
        for i in items:
            if i["file"] not in on_disk:
                hard.append({"level": "hard", "msg": "清单登记但帧不存在: %s" % i["file"]})
    result = {"frame_dir": os.path.abspath(args.frame_dir),
              "hard": hard, "soft": soft, "pass": not hard}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if hard else 0


def cmd_clean(args):
    man = load_manifest(args.frame_dir)
    registered = {i["file"] for v in man.values() for i in v}
    on_disk = sorted(glob.glob(os.path.join(args.frame_dir, "*.jpg")))
    if args.stem:
        on_disk = [f for f in on_disk if os.path.basename(f).startswith(args.stem + "_")]
    doomed = [f for f in on_disk if os.path.basename(f) not in registered]

    log = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
           "confirm": bool(args.confirm), "to_delete": [os.path.basename(f) for f in doomed]}
    log_dir = os.path.join(os.path.dirname(os.path.abspath(args.frame_dir)), "04_技术中间件")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "clean_log.json"), "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    if not doomed:
        print("没有待清理帧。")
        return 0
    print("待清理 %d 帧（默认 dry-run，日志已写）：" % len(doomed))
    for f in doomed:
        print("  -", os.path.basename(f))
    if not args.confirm:
        print("加 --confirm 才会真删；登记在 manifest 里的证据帧不会被删。")
        return 0
    for f in doomed:
        os.remove(f)
    print("已删除 %d 帧。" % len(doomed))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["pick", "probe", "verify", "check", "clean"])
    ap.add_argument("--video")
    ap.add_argument("--frame-dir", required=True)
    ap.add_argument("--frames")
    ap.add_argument("--frames-file")
    ap.add_argument("--secs")
    ap.add_argument("--cell", type=int, default=240)
    ap.add_argument("--stem")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    if args.command == "pick":
        cmd_pick(args)
    elif args.command == "probe":
        cmd_probe(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "clean":
        sys.exit(cmd_clean(args))


if __name__ == "__main__":
    main()
