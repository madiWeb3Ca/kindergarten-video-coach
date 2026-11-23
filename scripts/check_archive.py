#!/usr/bin/env python3
"""档案表完整性自检：文件在不在、能不能打开、表头对不对、有没有落在临时目录。

和 check_output.py 的分工：
  · check_output.py 查交付物（HTML 自包含、截帧落盘）；
  · 本脚本查档案表（10 张底座表）的长期可用性，对应“长期使用文件打不开”的排查。

用法：
  python check_archive.py --project <项目目录>

退出码：
  0  没有 hard 级问题（可有 soft 提醒）
  1  有 hard 级问题：表缺失／损坏／表头对不上／落在临时目录
  2  只有 soft 提醒

输出 JSON：pass、hard_count、soft_count、issues、tables、tier。
hard 问题按 issue.next 处置；脚本只报告与建议，不自动删旧表、不覆盖数据。
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import table_io  # noqa: E402

TEMP_HINTS = ("\\tmp", "/tmp", "\\temp", "/temp", "sandbox", "沙箱", "AppData\\Local\\Temp")


def _is_temporary(path):
    low = path.lower()
    return any(h.lower() in low for h in TEMP_HINTS)


def _header_diff(table, header):
    names = [f["name"] for f in table["fields"]]
    header = [str(h).strip() if h is not None else "" for h in (header or [])]
    missing = [n for n in names if n not in header]
    extra = [h for h in header if h and h not in names]
    return missing, extra


def check_table(project, table, tier):
    """返回 (entry, issues)。issues 为该表上的 hard／soft 问题列表。"""
    issues = []
    if tier == "L1_cloud":
        entry = {"name": table["name"], "tier": "L1_cloud", "exists": True,
                 "header_ok": None, "rows": None,
                 "note": "在线表由端上在线表能力维护，脚本侧无法回读；请在端上确认坐标已写回初始化记录"}
        issues.append({"level": "soft", "code": "E_L1_PENDING", "table": table["name"],
                       "msg": "在线表需在端上回读确认；脚本不能替你核验",
                       "next": "打开在线表核对 10 张表与字段齐全，再把链接／坐标写回 05_初始化记录.md"})
        return entry, issues

    v = (table_io.verify_xlsx_table(project, table) if tier == "L2_excel"
         else table_io.verify_md_table(project, table))
    entry = {"name": table["name"], "tier": tier, "exists": v["exists"],
             "header_ok": v["header_ok"], "rows": v["rows"], "path": v.get("path")}

    if not v["exists"]:
        issues.append({"level": "hard", "code": "E_MISSING", "table": table["name"],
                       "msg": "档案表文件不存在",
                       "next": "先核对档位是否记岔（跑 table_io.py state）；确认应为本档后按 schema.json 重建该表，已有记录从案例库兜底补回"})
        return entry, issues

    if _is_temporary(v["path"]):
        issues.append({"level": "hard", "code": "E_TEMP_PATH", "table": table["name"],
                       "msg": "表文件落在临时目录，换会话就会丢",
                       "next": "把表文件移回项目内「表格」目录，并在记录里写项目内相对路径"})

    if v["error"] == table_io.ERR_TABLE_CORRUPT:
        issues.append({"level": "hard", "code": table_io.ERR_TABLE_CORRUPT, "table": table["name"],
                       "msg": "表文件损坏，读不出来",
                       "next": table_io.ERR_NEXT[table_io.ERR_TABLE_CORRUPT]})
    elif v["error"] == table_io.ERR_SCHEMA_MISMATCH:
        missing, extra = _header_diff(table, v.get("header"))
        issues.append({"level": "hard", "code": table_io.ERR_SCHEMA_MISMATCH, "table": table["name"],
                       "msg": "表头与档案骨架对不上（缺：%s；多：%s）" % ("、".join(missing) or "无", "、".join(extra) or "无"),
                       "next": table_io.ERR_NEXT[table_io.ERR_SCHEMA_MISMATCH]})
    elif v["error"] == table_io.ERR_OPENPYXL_MISSING:
        issues.append({"level": "soft", "code": table_io.ERR_OPENPYXL_MISSING, "table": table["name"],
                       "msg": "本机缺 openpyxl，无法打开 xlsx 校验",
                       "next": "补装 openpyxl 后复跑；或确认该表已按 Markdown 兜底保存"})
    return entry, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()

    project = os.path.abspath(a.project)
    schema = table_io.load_schema()
    recon = table_io.reconcile_tier(project, schema)
    tier = recon["tier"]

    result = {"project": project, "tier": tier, "tier_label": table_io.TIER_LABEL.get(tier, "未初始化"),
              "consistent": recon["consistent"], "warning": recon["warning"],
              "suggest": recon["suggest"], "tables": [], "issues": []}

    if tier is None:
        result["issues"].append({"level": "soft", "code": "E_NOT_INIT", "table": None,
                                 "msg": "项目尚未初始化，先跑 bootstrap.py",
                                 "next": "首次使用先执行一键初始化，再跑本自检"})
    else:
        for table in schema["tables"]:
            entry, issues = check_table(project, table, tier)
            result["tables"].append(entry)
            result["issues"] += issues
        if recon["consistent"] is False and recon.get("suggest"):
            result["issues"].append({"level": "soft", "code": "E_TIER_MISMATCH", "table": None,
                                    "msg": recon["warning"], "next": recon["suggest"]["reason"] +
                                    "；核对清楚前不要自动重建另一套表"})

    hard = [i for i in result["issues"] if i["level"] == "hard"]
    soft = [i for i in result["issues"] if i["level"] == "soft"]
    result["pass"] = not hard
    result["hard_count"] = len(hard)
    result["soft_count"] = len(soft)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if hard else (2 if soft else 0)


if __name__ == "__main__":
    sys.exit(main())
