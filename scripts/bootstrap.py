#!/usr/bin/env python3
"""一键项目初始化：建目录 → 建 10 表 → 灌 47+44 条 → 回读校验 → 写初始化记录。

幂等：已存在 05_初始化记录.md 且该记录未标「未完成」时直接返回 already_initialized=True，
不重复建表、不覆盖已有数据。

用法：
  python bootstrap.py --project <dir> --env cloud|local [--force]

多建一个项目 = 重新初始化一次、重新建档，这是「一人一项目一档案」的预期行为，不是故障。
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import table_io  # noqa: E402

DIRS = [
    ("00_待评片子", "刚拍完还没分析的片子放这里。名字不用改，传进来就行。"),
    ("01_已评片子", "诊断完的片子，连同诊断记录一起留着，方便以后回看。"),
    ("02_锚点片", "「这个样子就对」的示范片。留着当尺子，比口头描述管用。"),
    ("03_素材原件", "原始素材，剪过的、没剪的都留一份，别只留成片。"),
    ("04_技术中间件", "转码、音轨、抽帧等中间产物，可以随时清。"),
]

README = """# 这个项目是干什么的

这是幼儿视频拍摄与剪辑教练的工作区。片子在本地目录，档案在表里，两边分开存。

## 目录怎么用

| 目录 | 放什么 | 能不能删 |
|---|---|---|
| 00_待评片子 | 刚拍完，等分析的；新片直接粘对话框也由教练归档进来 | 分析完再挪走 |
| 01_已评片子 | 诊断过的片子，连同诊断记录一起留着回看 | 不要删 |
| 02_锚点片 | 自己觉得不错、要当样板的示范片 | 不要删 |
| 03_素材原件 | 当前在评片子要对照的原始片段，按需放，不做全量入库 | 归档后再清 |
| 04_技术中间件 | 转码、音轨、抽帧等中间产物，老师不用管 | 可以随时清 |
| 表格 | 档案表 | 不要删 |

## 片子怎么命名

- 格式：日期_题材_版本，例 `20261123_骑车_V1`。
- 一个活动只留一条记录，版本 V1→V2→V3 往后排；V1 评完留在 01 当对照物，不删不覆盖；改完的 V2 放 00 并写清 V2；改后重拍算同活动新版本，换活动换目标另算；同一问题改到 V3 仍未解决就停手，转拍摄侧调整。

## 新片子进来做三个动作

1. 拖进 00_待评片子，或直接粘到对话框；
2. 跟教练说一句这是不是改版、是哪个活动的第几版；
3. 等教练看完给诊断。

## 原件与旧片

- 片子复制或粘进项目即可，原件留在原处不用搬动，项目里这份是对照副本。
- 以前拍的旧片，想让点评的挑出来复制进 00_待评片子，走同一套待评流程。

## 云电脑模式三条

1. 沙箱只是当次工作区，不当长期档案库，不保证跨会话、换端保留；
2. 不把几百 MB 的成片搬进沙箱，归档只在档案表改状态、写明片子在哪儿；
3. 示例图只作当次对照，要长期留就另存或写进文档。

## 几条要紧的

- 一个项目只建一次。再新建项目等于另开一份档案。
- 片子大的留在本地，表格小可以上云。云空间满了不会自动清，但会传不上去。
- 写进档案的截帧必须落盘或挂进表，只写路径不给文件，以后就是死链。
"""


def build_dirs(project):
    created, kept = [], []
    for name, hint in DIRS:
        path = os.path.join(project, name)
        if os.path.isdir(path):
            kept.append(name)
        else:
            os.makedirs(path, exist_ok=True)
            created.append(name)
        keep = os.path.join(path, ".keep")
        if not os.path.exists(keep):
            with open(keep, "w", encoding="utf-8", newline="\n") as f:
                f.write("")
    readme = os.path.join(project, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8", newline="\n") as f:
            f.write(README)
        created.append("README.md")
    return {"created": created, "kept": kept}


def roundtrip_check(project):
    """写完回读一次：文件在不在、能不能打开、表头对不对。"""
    schema = table_io.load_schema()
    ok, detail = True, {}
    tier = table_io.read_tier(project)
    for t in schema["tables"]:
        if tier == "L1_cloud":
            detail[t["name"]] = "delegated(待端上回读确认)"
            continue
        v = (table_io.verify_xlsx_table(project, t) if tier == "L2_excel"
             else table_io.verify_md_table(project, t))
        if not v["exists"]:
            detail[t["name"]] = "missing"
            ok = False
        elif v["error"] == table_io.ERR_TABLE_CORRUPT:
            detail[t["name"]] = "corrupt"
            ok = False
        elif v["error"] == table_io.ERR_SCHEMA_MISMATCH:
            detail[t["name"]] = "header_mismatch"
            ok = False
        else:
            detail[t["name"]] = "ok"
    return ok, detail


def write_state(project, env, tier, table_result, seed_result, dirs_result, check_ok, check_detail, note="", env_warnings=None):
    path = os.path.join(project, table_io.STATE_FILE)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = 0
    for v in seed_result.values():
        if isinstance(v, dict):
            total += v.get("added", 0) or 0
    lines = [
        "# 初始化记录",
        "",
        "- 初始化时间: %s" % now,
        "- 运行环境: %s" % ("云电脑" if env == "cloud" else "本地电脑"),
        "表格档位: %s" % tier,
        "- 档位说明: %s" % table_io.TIER_LABEL.get(tier, "未知"),
        "- 环境档位核对: %s" % ("一致" if not env_warnings else "；".join(env_warnings)),
        "- 建表数量: %s" % table_result.get("count", "delegated"),
        "- 本次新灌条目: %s 条" % total,
        "- 回读校验: %s" % ("全部通过" if check_ok else "有缺项，见下"),
        "",
        "## 表位置",
        "",
    ]
    for name, st in check_detail.items():
        lines.append("- %s: %s" % (name, st))
    lines += ["", "## 灌库明细", ""]
    for k, v in seed_result.items():
        lines.append("- %s: %s" % (k, json.dumps(v, ensure_ascii=False)))
    if note:
        lines += ["", "## 待办", "", note]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _initialize(a, project):
    os.makedirs(project, exist_ok=True)
    dirs_result = build_dirs(project)

    init_result = table_io.init(project, env=a.env)
    tier = init_result.get("tier")
    table_result = {"tier": tier, "count": init_result.get("count", 0),
                    "delegated": init_result.get("delegated", False),
                    "pending_verify": init_result.get("pending_verify", False),
                    "tables": init_result.get("tables")}

    seed_result = table_io.seed(project)

    check_ok, check_detail = roundtrip_check(project)
    table_io.write_tier(project, tier)

    env_warnings = table_io.env_tier_consistency(a.env, tier)
    coord_written = table_io.l1_coord_written(project) if tier == "L1_cloud" else None

    note_parts = list(env_warnings)
    if init_result.get("downgraded"):
        d = init_result["downgraded"]
        note_parts.append("档位由 %s 降为 %s：%s" % (d["from"], d["to"], d["reason"]))
    if table_result["delegated"]:
        note_parts.append("在线表建成后须回读坐标（链接／表 ID）写回本记录；建不出来就逐级降本地 Excel／Markdown。")
    state_path = write_state(project, a.env, tier, table_result, seed_result,
                             dirs_result, check_ok, check_detail,
                             note="；".join(note_parts), env_warnings=env_warnings)

    out = {
        "already_initialized": False,
        "project": project,
        "env": a.env,
        "tier": tier,
        "tier_label": table_io.TIER_LABEL.get(tier, "未知"),
        "env_warnings": env_warnings,
        "coord_written": coord_written,
        "dirs": dirs_result,
        "seed": seed_result,
        "downgraded": init_result.get("downgraded"),
        "pending_verify": table_result["pending_verify"],
        "roundtrip_ok": check_ok,
        "roundtrip_detail": check_detail,
        "state_file": state_path,
        "next": "建档三问（A/B/C）；回读没通过的表先补齐再继续",
    }
    return out, check_ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--env", default="local", choices=["cloud", "local"])
    p.add_argument("--force", action="store_true", help="忽略已有记录，强制重建（不覆盖已有行）")
    a = p.parse_args()

    project = os.path.abspath(a.project)
    state = os.path.join(project, table_io.STATE_FILE)
    if os.path.exists(state) and not a.force:
        tier = table_io.read_tier(project)
        print(json.dumps({"already_initialized": True, "tier": tier,
                          "next": "直接进日常；要重建加 --force"}, ensure_ascii=False, indent=2))
        return 0

    try:
        out, check_ok = _initialize(a, project)
    except Exception as e:  # 兜底：不把 Traceback 甩给老师，detail 仅留给出错定位
        print(json.dumps({"fatal": True,
                          "message": "初始化没走完，已保留已建内容；先看下面的定位信息再决定是否重跑。",
                          "detail": str(e)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if check_ok else 2


if __name__ == "__main__":
    sys.exit(main())
