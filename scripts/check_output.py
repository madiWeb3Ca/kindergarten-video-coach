#!/usr/bin/env python3
"""交付前校验：截帧落盘、HTML 自包含、禁用措辞、占位符、真名、清单一致性。

用法：
  python check_output.py --project <dir> --html <file.html>
  python check_output.py --project <dir> --images <a.jpg> <b.jpg>
  python check_output.py --project <dir> --html <f.html> --manifest <帧目录> [--names 姓名1 姓名2]

退出码：0 通过；1 有硬问题必须改；2 只有提醒（脚本返回 0，仅 soft 时也算通过）。
"""

import argparse
import glob
import json
import os
import re
import sys

INLINE_RE = re.compile(r'src="data:image/')
SRC_RE = re.compile(r'src="([^"]+)"')
HREF_RE = re.compile(r'href="([^"#][^"]*)"')
TEMP_HINTS = ("\\tmp", "/tmp", "\\temp", "/temp", "sandbox", "沙箱", "AppData\\Local\\Temp")

# 明确贬义短语：命中即 hard（应换成“可以再调整的地方”一类口径）
HARD_BAD = ["缺点", "短板", "毛病", "能力不行", "技术不行", "做错了", "错误", "烂"]
# 单字/易误伤词：命中给 soft 并附上下文，人工复核是否为普通词（差异/拿掉/差不多等）
SOFT_BAD = ["不行", "差", "弱", "错"]
# 普通搭配白名单：命中位置落在这些词内不算违规复核
SOFT_WHITELIST = {
    "差": ["差异", "差别", "差距", "反差", "时差", "色差", "差不多", "相差", "落差", "偏差", "误差", "较差", "温差"],
    "错": ["不错", "差错", "错觉", "对错", "认错"],
}
PLACEHOLDERS = ["TODO", "TBD", "XXX", "xxx", "待补", "待填", "占位", "{{", "<待", "【待"]

TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
TEXT_RE = re.compile(r"<[^>]+>")


def html_text(text):
    text = TAG_RE.sub(" ", text)
    return TEXT_RE.sub(" ", text)


def context(text, word, span=12):
    i = text.find(word)
    if i < 0:
        return ""
    return text[max(0, i - span):i + len(word) + span].strip()


def _in_whitelist(plain, idx, w):
    for word in SOFT_WHITELIST.get(w, []):
        if plain[max(0, idx - len(word) + 1): idx + len(word)] == word:
            return True
        if plain[idx: idx + len(word)] == word:
            return True
    return False


def _covered(spans, idx, w):
    return any(a <= idx and idx + len(w) <= b for a, b in spans)


def check_language(text, names):
    issues = []
    plain = html_text(text)
    hard_spans = []
    for w in HARD_BAD:
        start = 0
        while True:
            idx = plain.find(w, start)
            if idx < 0:
                break
            start = idx + len(w)
            hard_spans.append((idx, idx + len(w)))
            issues.append({"level": "hard", "msg": "禁用措辞「%s」：%s" % (w, context(plain, w))})
    for w in SOFT_BAD:
        start = 0
        while True:
            idx = plain.find(w, start)
            if idx < 0:
                break
            start = idx + len(w)
            if _covered(hard_spans, idx, w):
                continue
            if _in_whitelist(plain, idx, w):
                continue
            issues.append({"level": "soft", "msg": "复核用词「%s」，确认不是普通词：%s" % (w, context(plain, w))})
    for w in PLACEHOLDERS:
        if w in plain:
            issues.append({"level": "soft", "msg": "疑似未填完的占位符「%s」：%s" % (w, context(plain, w))})
    for n in names:
        if n and n in plain:
            issues.append({"level": "hard", "msg": "正文出现真名「%s」，应改用昵称" % n})
    return issues


def check_manifest(frame_dir):
    issues = []
    man_path = os.path.join(frame_dir, "frames_manifest.json")
    if not os.path.exists(man_path):
        return issues, 0, 0
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)
    on_disk = {os.path.basename(x) for x in glob.glob(os.path.join(frame_dir, "*.jpg"))}
    registered = {i["file"] for v in man.values() for i in v}
    for fn in on_disk - registered:
        issues.append({"level": "soft", "msg": "帧已落盘但清单未登记: %s" % fn})
    for stem, items in man.items():
        for i in items:
            if i["file"] not in on_disk:
                issues.append({"level": "hard", "msg": "清单登记但帧不存在: %s" % i["file"]})
    return issues, len(on_disk), len(registered)


def check_html(html, project, names):
    issues = []
    if not os.path.exists(html):
        return {"file": html, "issues": [{"level": "hard", "msg": "文件不存在"}]}
    with open(html, encoding="utf-8") as f:
        text = f.read()
    inline = len(INLINE_RE.findall(text))
    externals = [s for s in SRC_RE.findall(text) if not s.startswith("data:")]
    anchors = [h for h in HREF_RE.findall(text) if not h.startswith(("http://", "https://", "mailto:", "data:"))]
    for s in externals:
        issues.append({"level": "hard", "msg": "图片指向外部文件，会随源文件丢失: %s" % s})
    for a in anchors:
        issues.append({"level": "soft", "msg": "含相对链接，内嵌预览环境可能点不开: %s" % a})
    if inline == 0 and externals:
        issues.append({"level": "hard", "msg": "没有内嵌图，全靠外链"})
    issues += check_language(text, names)
    return {"file": os.path.basename(html), "inline_images": inline,
            "external_images": len(externals), "relative_links": len(anchors), "issues": issues}


def check_images(images, project):
    issues = []
    per = []
    root = os.path.abspath(project)
    for img in images:
        cand = img if os.path.isabs(img) else os.path.join(root, img)
        exists = os.path.exists(cand)
        inside = os.path.abspath(cand).startswith(root)
        tmp = any(h.lower() in cand.lower() for h in TEMP_HINTS)
        entry = {"image": img, "exists": exists, "inside_project": inside, "looks_temporary": tmp}
        if not exists:
            issues.append({"level": "hard", "msg": "截帧不在落盘位置，以后打开是死链: %s" % img})
        elif tmp:
            issues.append({"level": "hard", "msg": "截帧落在临时目录，会随沙箱一起丢: %s" % img})
        elif not inside:
            issues.append({"level": "soft", "msg": "截帧在项目目录之外，换机器可能找不到: %s" % img})
        per.append(entry)
    return {"checked": len(images), "items": per, "issues": issues}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--html", default=None)
    p.add_argument("--images", nargs="*", default=[])
    p.add_argument("--manifest", default=None, help="帧目录，做清单双向核对")
    p.add_argument("--names", nargs="*", default=[], help="需在正文中规避的真名名单")
    a = p.parse_args()

    result = {"project": os.path.abspath(a.project), "issues": []}
    if a.html:
        r = check_html(a.html, a.project, a.names)
        result["html"] = r
        result["issues"] += r["issues"]
    if a.images:
        r = check_images(a.images, a.project)
        result["images"] = r
        result["issues"] += r["issues"]
    if a.manifest:
        issues, on_disk, registered = check_manifest(a.manifest)
        result["manifest"] = {"frames_on_disk": on_disk, "registered": registered}
        result["issues"] += issues

    hard = [i for i in result["issues"] if i["level"] == "hard"]
    result["pass"] = not hard
    result["hard_count"] = len(hard)
    result["soft_count"] = len(result["issues"]) - len(hard)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not hard else 1


if __name__ == "__main__":
    sys.exit(main())
