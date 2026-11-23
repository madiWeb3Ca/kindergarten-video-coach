#!/usr/bin/env python3
"""单条诊断报告渲染器（教练侧工具，数据／模板／帧清单分离）。

设计要点（D4）：
  · 数据在外部 JSON，模板在本脚本，帧清单在 manifest 目录，三者解耦；
  · 按名单条渲染：--stem 只渲染指定条目，不全量重写已有报告；
  · 帧图按清单文件名从 manifest 目录取，base64 内嵌；缺帧跳过并标注缺口，不假装贴图；
  · 缺字段的段落整段省略，不崩；中性配色，不固化园所品牌。

输入 JSON（单对象，或条目数组；条目字段均可缺省）：
  stem / title / orientation(16:9|9:16) / kind(finished|raw|unknown)
  specs:{键:值}  audience:[…]
  value:{who,actual,verdict}  arch:{pos,struct,select,judge}
  merits:[{t,desc,keep}]  merit_frames:[{t,file,note}]
  issues:[{level,name,what,std,fix,owner,tc,frame:{t,file,note},audio_note,pending}]
  upgrades:[{no,name,what,why,frame:{t,file,note}}]
  grip:[[标题,说明]]  appendix:[[编号,条文短名]]
  first_fix / verdict / ceiling

用法：
  python report_render.py --data <诊断.json> [--manifest <帧目录>] [--stem <片子标识>] --out <报告.html>
"""

import argparse
import base64
import html
import io
import json
import os
import sys

CSS = """
:root{
  --deep:#33424D; --main:#4A5D6A; --gold:#A99B7E; --gold-deep:#7A6E57;
  --paper:#FAF6EE; --ink:#2B2620; --gray:#6B5F52; --line:#E4D8BE; --white:#fff;
  --serif:"Noto Serif SC","Source Han Serif SC","Songti SC","SimSun",Georgia,serif;
  --sans:"Microsoft YaHei","PingFang SC","Noto Sans SC",system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%}
.wrap{max-width:900px;margin:0 auto;padding:32px 24px 64px}
header{border-bottom:2px solid var(--main);padding-bottom:16px;margin-bottom:22px}
.brand{font-size:12.5px;letter-spacing:.18em;color:var(--gold-deep);margin-bottom:10px}
h1{font-family:var(--serif);font-size:27px;line-height:1.3;color:var(--deep);font-weight:800}
.sub{font-family:var(--serif);font-size:14.5px;color:var(--gray);margin-top:7px}
h2{font-family:var(--serif);font-size:18px;color:var(--deep);font-weight:800;margin:30px 0 12px;padding-left:11px;border-left:4px solid var(--gold)}
h3{font-family:var(--serif);font-size:15px;color:var(--deep);margin:16px 0 8px}
p{margin:0 0 9px}
.card{background:var(--white);border:1px solid var(--line);border-radius:3px;padding:15px 17px;margin-bottom:12px}
.verdict{background:var(--deep);color:var(--paper);border-radius:4px;padding:16px 18px;margin:14px 0}
.verdict .t{font-family:var(--serif);color:var(--gold);font-size:12.5px;letter-spacing:.16em;margin-bottom:7px}
.verdict p{margin:0;font-size:14.5px;line-height:1.75}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.specs{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.spec{border:1px solid var(--line);background:var(--white);border-radius:3px;padding:11px 13px}
.spec .k{color:var(--gray);font-size:12px;margin-bottom:3px}
.spec .v{font-family:var(--serif);font-size:15px;color:var(--deep);font-weight:700;line-height:1.4}
figure{background:var(--white);border:1px solid var(--line);border-radius:3px;overflow:hidden;margin:9px 0}
figure img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover}
figure.v img{aspect-ratio:9/16}
figcaption{padding:7px 10px;font-size:11.5px;color:var(--gray);line-height:1.5}
figcaption b{color:var(--ink)}
.badge{display:inline-block;font-family:var(--serif);font-size:12px;padding:2px 9px;border-radius:3px;letter-spacing:.04em;margin-right:8px}
.b-p0{background:var(--main);color:#fff}
.b-p1{background:var(--gold);color:#2B2620}
.b-p2{background:#F3EADA;color:var(--gold-deep);border:1px solid var(--line)}
.b-pending{background:#EDEDED;color:var(--gray);border:1px dashed var(--line)}
.item{border:1px solid var(--line);background:var(--white);border-radius:3px;padding:14px 16px;margin-bottom:12px}
.item .head{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:7px}
.item .name{font-weight:700;color:var(--deep);font-size:14.5px}
.item .tc{font-family:Georgia,serif;color:var(--gold-deep);font-size:12.5px;margin-left:auto}
.item .row{margin:0 0 6px;font-size:13.5px}
.item .row .lk{color:var(--gray);font-size:12px}
.audio-note{font-size:12.5px;color:var(--gray);border-left:3px solid var(--line);padding-left:9px;margin-top:6px}
.pending-note{font-size:12.5px;color:var(--gold-deep);border-left:3px solid var(--gold);padding-left:9px;margin-top:6px}
.merit{border:1px solid var(--line);background:var(--white);border-radius:3px;padding:14px 16px}
.merit h4{font-family:var(--serif);font-size:14.5px;color:var(--deep);margin-bottom:6px}
.merit p{font-size:13.5px;color:var(--gray);margin:0}
.grip{border:1px solid var(--line);border-left:4px solid var(--gold);background:var(--white);padding:15px 17px;border-radius:3px}
.grip ol{counter-reset:g;list-style:none;margin:0}
.grip ol li{counter-increment:g;position:relative;padding-left:30px;margin-bottom:9px;font-size:14px}
.grip ol li::before{content:counter(g);position:absolute;left:0;top:2px;font-family:var(--serif);font-size:12.5px;color:var(--gold-deep);border:1px solid var(--line);width:21px;height:21px;line-height:19px;text-align:center;border-radius:50%}
.appendix{font-size:12.5px;color:var(--gray)}
.appendix table{width:100%;border-collapse:collapse;margin-top:8px}
.appendix th,.appendix td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
.appendix th{background:#F3EADA;color:var(--deep)}
footer{margin-top:36px;border-top:1px solid var(--line);padding-top:13px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12.5px;color:var(--gray)}
@media (max-width:700px){
  .wrap{padding:20px 15px 46px}
  h1{font-size:21px} h2{font-size:16.5px}
  .grid2,.grid3{grid-template-columns:1fr}
  .specs{grid-template-columns:repeat(2,1fr)}
  .item .tc{margin-left:0;flex-basis:100%}
}
"""

LEVEL_BADGE = {"P0": "b-p0", "P1": "b-p1", "P2": "b-p2", "pending": "b-pending"}
LEVEL_LABEL = {"P0": "必改", "P1": "建议改", "P2": "加分项", "pending": "待确认"}


def _esc(v):
    return html.escape("" if v is None else str(v))


def frame_uri(frame, manifest_dir):
    """按清单文件名取帧；找不到返回 None，由调用方标缺口。"""
    if not frame or not frame.get("file"):
        return None
    fn = frame["file"]
    cand = fn if os.path.isabs(fn) else os.path.join(manifest_dir or "", fn)
    if not os.path.exists(cand):
        cand = os.path.join(manifest_dir or "", os.path.basename(fn))
    if not os.path.exists(cand):
        return None
    with open(cand, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def figure(frame, manifest_dir, vertical):
    if not frame:
        return ""
    uri = frame_uri(frame, manifest_dir)
    t = _esc(frame.get("t", ""))
    note = _esc(frame.get("note", ""))
    cap = "<b>%s</b> · %s" % (t, note) if note else "<b>%s</b>" % t
    cls = ' class="v"' if vertical else ""
    if uri:
        return ('<figure%s><img src="%s" alt="%s %s"><figcaption>%s</figcaption></figure>'
                % (cls, uri, _esc(frame.get("file", "")), t, cap))
    return ('<figure%s><figcaption>%s<span class="src">｜帧文件未在清单目录找到：%s</span></figcaption></figure>'
            % (cls, cap, _esc(os.path.basename(frame.get("file", "")))))


def render_one(report, manifest_dir):
    vertical = report.get("orientation") == "9:16"
    stem = _esc(report.get("stem", ""))

    specs = "".join('<div class="spec"><div class="k">%s</div><div class="v">%s</div></div>'
                    % (_esc(k), _esc(v)) for k, v in (report.get("specs") or {}).items())
    audience = "".join("<p>%s</p>" % _esc(p) for p in report.get("audience") or [])

    val = report.get("value") or {}
    value = ""
    if val:
        value = ('<div class="grid3"><div class="card"><h3>给谁看</h3><p>%s</p></div>'
                 '<div class="card"><h3>实际传出去什么</h3><p>%s</p></div>'
                 '<div class="card"><h3>判断</h3><p>%s</p></div></div>'
                 % (_esc(val.get("who")), _esc(val.get("actual")), _esc(val.get("verdict"))))

    arch = report.get("arch") or {}
    arch_html = ""
    if arch:
        arch_html = ('<div class="grid2"><div class="card"><h3>① 定位</h3><p>%s</p></div>'
                     '<div class="card"><h3>② 结构</h3><p>%s</p></div>'
                     '<div class="card"><h3>③ 取舍与记忆点</h3><p>%s</p></div>'
                     '<div class="card"><h3>④ 总判断</h3><p>%s</p></div></div>'
                     % (_esc(arch.get("pos")), _esc(arch.get("struct")),
                        _esc(arch.get("select")), _esc(arch.get("judge"))))

    merits = ""
    for m in report.get("merits") or []:
        merits += ('<div class="merit"><h4>%s</h4><p>%s</p>'
                    '<p class="note">怎么留：%s</p></div>'
                    % (_esc(m.get("t")), _esc(m.get("desc")), _esc(m.get("keep"))))
    merit_frames = "".join(figure(f, manifest_dir, vertical)
                           for f in report.get("merit_frames") or [])

    issues = ""
    for it in report.get("issues") or []:
        level = it.get("level", "P1")
        badge = LEVEL_BADGE.get(level, "b-p1")
        label = LEVEL_LABEL.get(level, "建议改")
        rows = '<p class="row"><span class="lk">看到什么：</span>%s</p>' % _esc(it.get("what"))
        if it.get("std"):
            rows += '<p class="row"><span class="lk">对照标准：</span>%s</p>' % _esc(it["std"])
        if it.get("fix"):
            rows += '<p class="row"><span class="lk">怎么改：</span>%s</p>' % _esc(it["fix"])
        if it.get("owner"):
            rows += '<p class="row"><span class="lk">归属与成本：</span>%s</p>' % _esc(it["owner"])
        fig = figure(it.get("frame"), manifest_dir, vertical)
        if it.get("audio_note"):
            fig += '<p class="audio-note">%s</p>' % _esc(it["audio_note"])
        if it.get("pending"):
            fig += '<p class="pending-note">待确认：%s</p>' % _esc(it["pending"])
        tc = '<span class="tc">%s</span>' % _esc(it["tc"]) if it.get("tc") else ""
        issues += ('<div class="item"><div class="head"><span class="badge %s">%s %s</span>'
                   '<span class="name">%s</span>%s</div>%s%s</div>'
                   % (badge, _esc(level), _esc(label), _esc(it.get("name")), tc, rows, fig))

    ups = ""
    for u in report.get("upgrades") or []:
        fig = figure(u.get("frame"), manifest_dir, vertical)
        ups += ('<div class="item"><div class="head"><span class="name">%s</span></div>'
                '<p class="row"><span class="lk">做什么：</span>%s</p>'
                '<p class="row"><span class="lk">为什么值：</span>%s</p>%s</div>'
                % (_esc(u.get("name")), _esc(u.get("what")), _esc(u.get("why")), fig))

    grip = "".join("<li><b>%s</b>%s</li>" % (_esc(g[0]), _esc(g[1]))
                  for g in report.get("grip") or [])
    ap_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (_esc(a[0]), _esc(a[1]))
                      for a in report.get("appendix") or [])

    parts = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device, initial-scale=1">',
             '<title>成片诊断 · %s</title><style>%s</style></head><body><div class="wrap">'
             % (stem, CSS)]
    parts.append('<header><div class="brand">幼儿园视频教练 · 诊断报告</div>'
                 '<h1>%s</h1><div class="sub">先讲立得住的地方，再列可调整点；截帧均取自原片对应时间码</div></header>'
                 % _esc(report.get("title") or report.get("stem") or "成片诊断"))
    if specs:
        parts.append('<div class="specs">%s</div>' % specs)
    if report.get("first_fix"):
        parts.append('<div class="verdict"><div class="t">本轮先改哪处</div><p>%s</p></div>'
                     % _esc(report["first_fix"]))
    if audience:
        parts.append('<h2>一 · 观众感受</h2><div class="card">%s</div>' % audience)
    if value:
        parts.append('<h2>二 · 价值与定位</h2>%s' % value)
    if arch_html:
        parts.append('<h2>三 · 架构总评</h2>%s' % arch_html)
    if report.get("verdict"):
        parts.append('<div class="verdict"><div class="t">总判断</div><p>%s</p></div>' % _esc(report["verdict"]))
    if merits or merit_frames:
        parts.append('<h2>四 · 立得住的地方</h2><div class="grid2">%s</div><div class="grid2">%s</div>'
                     % (merits, merit_frames))
    if issues:
        parts.append('<h2>五 · 工艺清单</h2>%s' % issues)
    if ups:
        parts.append('<h2>六 · 拔高方向</h2>%s' % ups)
    if grip:
        parts.append('<h2>七 · 收尾抓手</h2><div class="grip"><ol>%s</ol></div>' % grip)
    if report.get("ceiling"):
        parts.append('<h2>八 · 上限在哪</h2><div class="card"><p>%s</p></div>' % _esc(report["ceiling"]))
    if ap_rows:
        parts.append('<h2>附录 · 依据条目</h2><div class="card appendix">'
                     '<table><tr><th>编号</th><th>条文短名</th></tr>%s</table></div>' % ap_rows)
    parts.append('<footer><span>成片诊断报告 · 截帧取自原片</span></footer></div></body></html>')
    return "".join(parts)


def load_entries(path):
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="单条诊断 JSON，或含多条的数组")
    ap.add_argument("--manifest", help="帧清单目录（按 file 取帧）；不传则帧位置留缺口标注")
    ap.add_argument("--stem", help="只渲染该片子标识；不传则渲染数据内全部条目")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    a = ap.parse_args()

    entries = load_entries(a.data)
    if a.stem:
        entries = [e for e in entries if e.get("stem") == a.stem]
    if not entries:
        raise SystemExit("没有可渲染的条目（stem=%s）" % a.stem)

    manifest_dir = a.manifest or os.path.dirname(os.path.abspath(a.data))
    # 单条直接出目标文件；多条时按 stem 各写一份，--out 视为目录前缀
    if len(entries) == 1:
        html_text = render_one(entries[0], manifest_dir)
        out = a.out
    else:
        out_dir = a.out if os.path.isdir(a.out) else os.path.dirname(os.path.abspath(a.out))
        os.makedirs(out_dir, exist_ok=True)
        written = []
        for e in entries:
            p = os.path.join(out_dir, "%s.html" % _esc(e.get("stem", "report")))
            io.open(p, "w", encoding="utf-8", newline="\n").write(render_one(e, manifest_dir))
            written.append(p)
        print("已渲染 %d 条：%s" % (len(written), ", ".join(written)))
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="\n").write(html_text)
    print("已渲染：%s（%d 条目）" % (out, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
