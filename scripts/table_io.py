#!/usr/bin/env python3
"""三档表格读写适配层。

上层业务只调 read/append，不关心底层是云端多维表格、本地 Excel 还是 Markdown。

档位：
  L1_cloud  在线多维表格（由 Agent 用 在线表能力建表，本脚本只记录坐标）
  L2_excel  本地 xlsx（需要 openpyxl，缺库自动降 L3）
  L3_md     Markdown 表（零依赖兜底）

档位写在 <project>/05_初始化记录.md 的「表格档位:」一行，续会话按记录走，不重新探测，
避免一次抖动把同一份档案拆成两套。

用法：
  python table_io.py probe   --project <dir> --env cloud|local
  python table_io.py init    --project <dir>
  python table_io.py state   --project <dir>
  python table_io.py append  --project <dir> --table diagnosis --row '{"诊断编号":"D-01"}'
  python table_io.py read    --project <dir> --table diagnosis --limit 20
"""

import argparse
import json
import os
import re
import sys

STATE_FILE = "05_初始化记录.md"
TABLE_DIR = "表格"
TIER_RE = re.compile(r"表格档位:\s*(L[123]_(?:cloud|excel|md))")
TIER_LABEL = {"L1_cloud": "在线多维表格", "L2_excel": "本地 Excel", "L3_md": "Markdown 表"}

# ---------- 错误码（对外只给人话与下一步，不甩 Traceback／英文异常名） ----------
ERR_OPENPYXL_MISSING = "E_OPENPYXL_MISSING"
ERR_TABLE_CORRUPT = "E_TABLE_CORRUPT"
ERR_DIR_NOT_WRITABLE = "E_DIR_NOT_WRITABLE"
ERR_SCHEMA_MISMATCH = "E_SCHEMA_MISMATCH"
ERR_FIELD_UNKNOWN = "E_FIELD_UNKNOWN"
ERR_ROW_INVALID = "E_ROW_INVALID"
ERR_STATE_BROKEN = "E_STATE_BROKEN"

ERR_HUMAN = {
    ERR_OPENPYXL_MISSING: "这台机器缺表格组件，已自动改用 Markdown 表兜底。",
    ERR_TABLE_CORRUPT: "这张表文件读不出来，可能已损坏。",
    ERR_DIR_NOT_WRITABLE: "当前目录写不进去，需要换到可写位置。",
    ERR_SCHEMA_MISMATCH: "表头和档案骨架对不上。",
    ERR_FIELD_UNKNOWN: "有字段名不在这张表的骨架里。",
    ERR_ROW_INVALID: "要写入的一行不是有效的记录。",
    ERR_STATE_BROKEN: "初始化记录读不出来，需要先备份再重建。",
}

ERR_NEXT = {
    ERR_TABLE_CORRUPT: "把坏表改名 *.bak 留档，按 tables/schema.json 重建该表，再从诊断案例库补最近记录；不要直接删旧文件。",
    ERR_DIR_NOT_WRITABLE: "换到项目内可写的子目录，把实际路径告诉老师，不假装建成了。",
    ERR_SCHEMA_MISMATCH: "对照 schema.json 核对表头，缺的字段补上；改前先把旧表备份成 .bak。",
    ERR_STATE_BROKEN: "先备份 05_初始化记录.md，再重跑 bootstrap；已有档案行不覆盖。",
}


def _err(code, table=None, detail="", next_step=""):
    e = {"code": code, "message": ERR_HUMAN.get(code, "操作没成功。")}
    if table:
        e["table"] = table
    if detail:
        e["detail"] = detail
    e["next"] = next_step or ERR_NEXT.get(code, "")
    return {"error": e}


# ---------- 骨架 ----------
def load_schema():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "tables", "schema.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(json.dumps(
            _err(ERR_SCHEMA_MISMATCH, detail="schema.json 读不出来：%s" % e,
                 next_step="对照 tables/schema.json 核对骨架文件，改前先备份旧表"),
            ensure_ascii=False))


def table_by_key(schema, key):
    for t in schema["tables"]:
        if t["key"] == key:
            return t
    raise SystemExit("未知表: %s，可用: %s" % (key, ", ".join(t["key"] for t in schema["tables"])))


# ---------- 档位 ----------
def read_tier(project):
    path = os.path.join(project, STATE_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = TIER_RE.search(f.read())
    return m.group(1) if m else None


def write_tier(project, tier):
    path = os.path.join(project, STATE_FILE)
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    line = "表格档位: %s" % tier
    if TIER_RE.search(text):
        text = TIER_RE.sub(line, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + line + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def has_openpyxl():
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


def probe(project, env):
    """真探测，不拍脑袋。已有记录直接沿用。"""
    existing = read_tier(project)
    if existing:
        return {"tier": existing, "reason": "沿用初始化记录，不重新探测", "reused": True}
    if env == "cloud":
        return {"tier": "L1_cloud", "reason": "云电脑环境，优先在线多维表格；若建表失败改 L2"}
    if has_openpyxl():
        return {"tier": "L2_excel", "reason": "本地环境且 openpyxl 可用"}
    return {"tier": "L3_md", "reason": "本地环境但缺 openpyxl，降 Markdown 表"}


def _local_files(project, tier, schema):
    """列出某档位下每张表对应的本地文件是否存在（L1 在线表无本地文件）。"""
    found = {}
    for t in schema["tables"]:
        if tier == "L2_excel":
            p = xlsx_path(project, t)
        elif tier == "L3_md":
            p = md_path(project, t)
        else:
            found[t["name"]] = None
            continue
        found[t["name"]] = p if os.path.exists(p) else None
    return found


def reconcile_tier(project, schema=None):
    """核对记录档位与本地实际文件是否一致；只给建议，不擅自改记录、不重建两套表。

    返回：tier（记录档位）、consistent、warning、suggest（建议档位与原因）。
    L1 在线表无本地文件可核对，标记待端上回读确认。
    """
    schema = schema or load_schema()
    tier = read_tier(project)
    if tier is None:
        return {"tier": None, "consistent": None, "warning": "未初始化", "suggest": None}
    if tier == "L1_cloud":
        coord = l1_coord_written(project)
        warning = ("在线表需在端上回读确认；" if coord else "在线表坐标（链接／表 ID）尚未写回初始化记录，建成后须补写；") \
                  + "脚本侧无法替你核验线上表内容"
        return {"tier": tier, "consistent": True, "coord_written": coord,
                "warning": warning, "suggest": None}
    files = _local_files(project, tier, schema)
    missing = [n for n, p in files.items() if not p]
    other = "L3_md" if tier == "L2_excel" else "L2_excel"
    other_files = _local_files(project, other, schema)
    other_present = [n for n, p in other_files.items() if p]
    if not missing:
        return {"tier": tier, "consistent": True, "warning": "", "suggest": None}
    suggest = {"tier": other,
               "reason": "记录为 %s，但本地缺 %d 张表；%s 已有 %d 张，先核对是否档位记岔"
                         % (TIER_LABEL.get(tier, tier), len(missing),
                            TIER_LABEL.get(other, other), len(other_present))}
    return {"tier": tier, "consistent": False, "warning": "本地表不齐全：%s" % "、".join(missing),
            "suggest": suggest}


def env_tier_consistency(env, tier):
    """校验命令行环境与探测档位是否匹配；返回 warning 列表（空=一致）。

    cloud 允许逐级降到 L2/L3（L1 建不成），但必须在记录标明降级原因；
    local 不应记为 L1。仅给核对提醒，不擅自改档位、不重建两套表。
    """
    warnings = []
    if env == "cloud" and tier in ("L2_excel", "L3_md"):
        warnings.append("云电脑环境落到本地表（%s）；应优先 L1 在线表，若为逐级降级须在记录标明原因"
                         % TIER_LABEL.get(tier, tier))
    if env == "local" and tier == "L1_cloud":
        warnings.append("本地环境记为 L1 在线表；本地无在线表能力，先核对是否档位记岔")
    return warnings


def l1_coord_written(project):
    """L1 在线表建成后，坐标（链接／表 ID）应回写进初始化记录。脚本侧只查记录有无坐标痕迹。"""
    path = os.path.join(project, STATE_FILE)
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return ("http://" in text or "https://" in text or "表 ID" in text
            or "坐标" in text or "tbl" in text)


# ---------- 写入 ----------
def md_escape(v):
    return str(v).replace("|", "\\|").replace("\n", "<br>")


def md_path(project, table):
    return os.path.join(project, TABLE_DIR, table["name"] + ".md")


def xlsx_path(project, table):
    return os.path.join(project, TABLE_DIR, table["name"] + ".xlsx")


def init_md(project, table):
    os.makedirs(os.path.join(project, TABLE_DIR), exist_ok=True)
    path = md_path(project, table)
    if os.path.exists(path):
        return path
    names = [f["name"] for f in table["fields"]]
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("<!-- 档位: L3_md | 表: %s | 粒度: %s -->\n\n" % (table["name"], table.get("grain", "")))
            f.write("| " + " | ".join(names) + " |\n")
            f.write("|" + "|".join([" --- "] * len(names)) + "|\n")
    except OSError as e:
        raise SystemExit(json.dumps(_err(ERR_DIR_NOT_WRITABLE, table["name"], str(e)), ensure_ascii=False))
    return path


def init_xlsx(project, table):
    from openpyxl import Workbook
    os.makedirs(os.path.join(project, TABLE_DIR), exist_ok=True)
    path = xlsx_path(project, table)
    if os.path.exists(path):
        return path
    wb = Workbook()
    ws = wb.active
    ws.title = table["name"][:31]
    ws.append([f["name"] for f in table["fields"]])
    ws.freeze_panes = "A2"
    try:
        wb.save(path)
    except OSError as e:
        raise SystemExit(json.dumps(_err(ERR_DIR_NOT_WRITABLE, table["name"], str(e)), ensure_ascii=False))
    return path


def append_md(project, table, row):
    path = md_path(project, table)
    if not os.path.exists(path):
        init_md(project, table)
    names = [f["name"] for f in table["fields"]]
    cells = [md_escape(row.get(n, "")) for n in names]
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("| " + " | ".join(cells) + " |\n")
    except OSError as e:
        return dict(_err(ERR_DIR_NOT_WRITABLE, table["name"], str(e)), path=None)
    return path


def append_xlsx(project, table, row):
    from openpyxl import load_workbook
    path = xlsx_path(project, table)
    if not os.path.exists(path):
        init_xlsx(project, table)
    try:
        wb = load_workbook(path)
        ws = wb[table["name"][:31]]
        ws.append([row.get(f["name"], "") for f in table["fields"]])
        wb.save(path)
    except Exception as e:
        return dict(_err(ERR_TABLE_CORRUPT, table["name"], str(e)), path=None)
    return path


def append_batch(project, table, rows):
    """批量追加：xlsx 只 load/save 一次，md 一次写完。单行 append 每行约 50ms，批量后接近常数。"""
    if not rows:
        return {"added": 0, "path": None, "tier": read_tier(project) or "L2_excel"}
    tier = read_tier(project) or "L2_excel"
    if tier == "L1_cloud":
        return {"delegated": True, "tier": tier, "added": 0,
                "instruction": "用 在线表能力向「%s」批量写入 %d 行，字段顺序: %s" %
                               (table["name"], len(rows), " / ".join(f["name"] for f in table["fields"]))}
    if tier == "L2_excel" and has_openpyxl():
        from openpyxl import load_workbook
        path = xlsx_path(project, table)
        if not os.path.exists(path):
            init_xlsx(project, table)
        try:
            wb = load_workbook(path)
            ws = wb[table["name"][:31]]
            names = [f["name"] for f in table["fields"]]
            for row in rows:
                ws.append([row.get(n, "") for n in names])
            wb.save(path)
        except Exception as e:
            return dict(_err(ERR_TABLE_CORRUPT, table["name"], str(e)), tier=tier, added=0)
        return {"path": path, "tier": tier, "added": len(rows)}
    path = md_path(project, table)
    if not os.path.exists(path):
        init_md(project, table)
    names = [f["name"] for f in table["fields"]]
    lines = ["| " + " | ".join(md_escape(row.get(n, "")) for n in names) + " |" for row in rows]
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return {"path": path, "tier": "L3_md", "added": len(rows)}


def append(project, table, row):
    tier = read_tier(project) or "L2_excel"
    if tier == "L1_cloud":
        return {"delegated": True, "tier": tier,
                "instruction": "用 在线表能力向「%s」追加一行，字段顺序: %s" %
                               (table["name"], " / ".join(f["name"] for f in table["fields"]))}
    if tier == "L2_excel" and has_openpyxl():
        r = append_xlsx(project, table, row)
        if isinstance(r, dict) and r.get("error"):
            return dict(r, tier=tier)
        return {"path": r, "tier": tier}
    r = append_md(project, table, row)
    if isinstance(r, dict) and r.get("error"):
        return dict(r, tier="L3_md")
    return {"path": r, "tier": "L3_md"}


def read_md(project, table, limit):
    path = md_path(project, table)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or line.startswith("<!--"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[0] == table["fields"][0]["name"] or cells[0].replace(" ", "") == "---":
                continue
            if set(cells[0]) <= set("- "):
                continue
            names = [f["name"] for f in table["fields"]]
            rows.append(dict(zip(names, cells)))
    return rows[-limit:] if limit else rows


def read_xlsx(project, table, limit):
    from openpyxl import load_workbook
    path = xlsx_path(project, table)
    if not os.path.exists(path):
        return []
    try:
        wb = load_workbook(path, read_only=True)
        ws = wb[table["name"][:31]]
        names = [f["name"] for f in table["fields"]]
        rows = [dict(zip(names, [c for c in r])) for r in ws.iter_rows(min_row=2, values_only=True)]
    except Exception as e:
        return {"_error": (ERR_TABLE_CORRUPT, table["name"], str(e))}
    return rows[-limit:] if limit else rows


def _header_match(table, header):
    names = [f["name"] for f in table["fields"]]
    return [str(h).strip() if h is not None else "" for h in header] == names


def verify_xlsx_table(project, table):
    """校验一张 xlsx：存在、能打开、表头与 schema 一致、行数。损坏不抛异常。"""
    path = xlsx_path(project, table)
    if not os.path.exists(path):
        return {"exists": False, "header_ok": False, "rows": 0, "error": "E_MISSING", "path": path}
    if not has_openpyxl():
        return {"exists": True, "header_ok": None, "rows": 0, "error": ERR_OPENPYXL_MISSING, "path": path}
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True)
        ws = wb[table["name"][:31]]
        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        rows = ws.max_row - 1 if ws.max_row else 0
        ok = _header_match(table, header)
        return {"exists": True, "header_ok": ok, "rows": max(rows, 0),
                "error": None if ok else ERR_SCHEMA_MISMATCH, "path": path, "header": header}
    except Exception as e:
        return {"exists": True, "header_ok": False, "rows": 0, "error": ERR_TABLE_CORRUPT,
                "detail": str(e), "path": path}


def verify_md_table(project, table):
    """校验一张 md 表：存在、表头与 schema 一致、数据行数。损坏不抛异常。"""
    path = md_path(project, table)
    if not os.path.exists(path):
        return {"exists": False, "header_ok": False, "rows": 0, "error": "E_MISSING", "path": path}
    names = [f["name"] for f in table["fields"]]
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip().startswith("|")]
    except OSError as e:
        return {"exists": True, "header_ok": False, "rows": 0, "error": ERR_TABLE_CORRUPT,
                "detail": str(e), "path": path}
    header, data_rows = None, 0
    for ln in lines:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if header is None and cells == names:
            header = cells
            continue
        if header is not None and set("".join(cells)) <= set("- "):
            continue
        if header is not None:
            data_rows += 1
    ok = header is not None
    return {"exists": True, "header_ok": ok, "rows": data_rows,
            "error": None if ok else ERR_SCHEMA_MISMATCH, "path": path,
            "header": header}


def read(project, table, limit):
    tier = read_tier(project) or "L2_excel"
    if tier == "L1_cloud":
        return {"delegated": True, "tier": tier,
                "instruction": "用 在线表能力读「%s」，取最近 %s 行" % (table["name"], limit)}
    if tier == "L2_excel" and has_openpyxl():
        rows = read_xlsx(project, table, limit)
        if isinstance(rows, dict) and rows.get("_error"):
            code, tname, detail = rows["_error"]
            return dict(_err(code, tname, detail), tier=tier, rows=[])
        return {"rows": rows, "tier": tier}
    return {"rows": read_md(project, table, limit), "tier": "L3_md"}


# ---------- 初始化 ----------
def init(project, tier=None, env=None):
    schema = load_schema()
    if tier is None:
        t = read_tier(project)
        tier = t if t else probe(project, env or "local")["tier"]
    if tier == "L1_cloud":
        write_tier(project, tier)
        return {"tier": tier, "delegated": True, "pending_verify": True,
                "verify_note": "在线表由端上在线表能力建成后，须回读坐标写回 05_初始化记录.md；建不出来就降 L2／L3",
                "tables": [{"name": t["name"], "fields": [f["name"] for f in t["fields"]]} for t in schema["tables"]]}
    downgraded = False
    if tier == "L2_excel" and not has_openpyxl():
        tier = "L3_md"
        downgraded = True
    created = []
    for t in schema["tables"]:
        created.append(init_md(project, t) if tier == "L3_md" else init_xlsx(project, t))
    write_tier(project, tier)
    out = {"tier": tier, "count": len(created), "files": created}
    if downgraded:
        out["downgraded"] = {"from": "L2_excel", "to": "L3_md",
                             "reason": ERR_HUMAN[ERR_OPENPYXL_MISSING]}
    return out


# ---------- 灌库 ----------
def strip_md_marks(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    return s.strip()


def parse_standards(text):
    out, layer = [], ""
    for line in text.splitlines():
        m = re.match(r"^##\s*层(\d)\s*", line.strip())
        if m:
            layer = "层" + m.group(1)
            continue
        m = re.match(r"^###\s*(S\d-\d+)", line.strip())
        if m:
            out.append({"编号": m.group(1), "条文": "", "层级": layer, "出处": "", "局限": "", "状态": "生效", "_buf": []})
            continue
        if not out:
            continue
        cur = out[-1]
        body = line.strip()
        if body.startswith("**条文**"):
            cur["条文"] = strip_md_marks(body.split("：", 1)[-1])
        elif body.startswith("- 出处"):
            cur["出处"] = body.split("：", 1)[-1].strip()
        elif body.startswith("- 局限"):
            cur["局限"] = body.split("：", 1)[-1].strip()
        elif body.startswith("- 状态"):
            st = body.split("：", 1)[-1].strip()
            cur["状态"] = "待校准" if ("待校准" in st or "待核" in st) else ("已归档" if "弃用" in st else "生效")
        elif body and body not in ("*",) and not cur["条文"]:
            cur["_buf"].append(strip_md_marks(body))
    for r in out:
        if not r["条文"]:
            r["条文"] = " ".join(r.pop("_buf"))
        else:
            r.pop("_buf", None)
    return out


def parse_capcut(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        # 走到「不适用／慎用清单」「待核验清单」这些附录章节就停，不往回灌进最后一条
        if s.startswith("## ") and ("不适用" in s or "待核验" in s):
            break
        m = re.match(r"^###\s*(J\d\d)\s*(.*)$", s)
        if m:
            num = m.group(1)
            out.append({"编号": num, "条目": m.group(2).strip(), "适用端": "共享",
                        "分层": "判据层" if int(num[1:]) <= 20 else "操作底图层",
                        "操作路径": "", "参数建议": "", "多源一致度": "",
                        "对园所片子的适用性": "", "核验状态": "待核验"})
            continue
        if not out:
            continue
        cur = out[-1]
        body = s
        if body.startswith("- 适用端"):
            v = body.split("：", 1)[-1].strip()
            cur["适用端"] = {"共享": "共享", "两端通用": "共享", "两端": "共享",
                             "APP": "APP", "手机版": "APP",
                             "PC": "PC", "专业版": "PC"}.get(v, "共享")
        elif body.startswith("- 操作路径"):
            cur["操作路径"] = body.split("：", 1)[-1].strip()
        elif body.startswith("- 参数建议"):
            cur["参数建议"] = body.split("：", 1)[-1].strip()
        elif body.startswith("- 多源一致度"):
            v = body.split("：", 1)[-1].strip()
            cur["多源一致度"] = ("一致" if "部分" not in v and "单一" not in v and "冲突" not in v
                               else ("部分一致" if "部分" in v else ("冲突" if "冲突" in v else "单一来源")))
        elif body.startswith("- 对园所片子") or body.startswith("- 对园所片子的适用性"):
            cur["对园所片子的适用性"] = body.split("：", 1)[-1].strip()
        elif body.startswith("- 核验状态"):
            v = body.split("：", 1)[-1].strip()
            cur["核验状态"] = "待核验" if ("待" in v or "核验" in v) else "已核验"
        elif body.startswith("- "):
            cur["条目"] += "\n" + strip_md_marks(body[2:])
    return out


def parse_taboos(text):
    out, in_sec = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_sec = ("不适用" in s)
            continue
        if not in_sec or not s.startswith("- "):
            continue
        body = strip_md_marks(s[2:])
        name, why = (body.split("：", 1) + [""])[:2] if "：" in body else (body, "")
        out.append({"类别": "剪映不适用慎用", "条目": name.strip(),
                    "原因": why.strip(), "来源": "剪映知识包 v1 · 不适用／慎用清单"})
    return out


def parse_pending(text):
    out, in_sec = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_sec = ("待核验" in s)
            continue
        if not in_sec:
            continue
        m = re.match(r"^(\d+)\.\s*(J\d\d)\s*(.*)$", s)
        if m:
            out.append({"编号": "V" + m.group(1).zfill(2),
                        "涉及条目": m.group(2), "待核验事项": m.group(3).strip(),
                        "核验结果": "", "核验日期": ""})
    return out


def parse_head(text):
    out, cur_heading, in_body = [], "", False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_body = True
            continue
        if s.startswith("### "):
            cur_heading = s[4:].strip()
            continue
        if s.startswith("> ") and not in_body:
            out.append({"类型": "总规矩", "名称": "库头总规矩", "内容或链接": s[2:].strip()})
            continue
        if s.startswith("合集链接：") and cur_heading:
            out.append({"类型": "官方课程索引", "名称": cur_heading,
                        "内容或链接": s.split("：", 1)[-1].strip()})
            cur_heading = ""
    return out


def seed(project):
    here = os.path.dirname(os.path.abspath(__file__))
    ref = os.path.join(here, "..", "references")
    schema = load_schema()
    result = {}
    jobs = []
    with open(os.path.join(ref, "standards-library.md"), encoding="utf-8") as f:
        std_text = f.read()
    with open(os.path.join(ref, "capcut-knowledge.md"), encoding="utf-8") as f:
        cap_text = f.read()
    jobs = [("standards", "标准条目库", parse_standards(std_text)),
            ("capcut", "剪映知识包", parse_capcut(cap_text)),
            ("taboos", "禁忌清单", parse_taboos(cap_text)),
            ("pending_verify", "待核验清单", parse_pending(cap_text)),
            ("capcut_head", "剪映库头与索引", parse_head(cap_text))]
    for key, tname, rows in jobs:
        table = table_by_key(schema, key)
        existing = read(project, table, 0)
        if isinstance(existing, dict) and existing.get("delegated"):
            result[key] = {"delegated": True, "rows": len(rows), "expected": len(rows),
                           "instruction": "在线表灌库前先按主键（首列）拉取已有记录去重，只追加缺失项；"
                                          "灌完回读条数应等于 %d，不一致即告警，不重复整批灌" % len(rows)}
            continue
        key_field = table["fields"][0]["name"]
        seen = {r.get(key_field) for r in existing.get("rows", [])}
        fresh = [r for r in rows if r.get(key_field) not in seen]
        append_batch(project, table, fresh)
        result[key] = {"parsed": len(rows), "added": len(fresh), "skipped": len(rows) - len(fresh)}
    return result


# ---------- CLI ----------
def _dispatch(a):
    if a.cmd == "probe":
        return probe(a.project, a.env)
    if a.cmd == "init":
        return init(a.project, a.tier, getattr(a, "env", None))
    if a.cmd == "seed":
        return seed(a.project)
    if a.cmd == "state":
        r = reconcile_tier(a.project)
        r["label"] = TIER_LABEL.get(r["tier"], "未初始化")
        return r
    if a.cmd == "append":
        if a.row_file:
            with open(a.row_file, encoding="utf-8") as f:
                row = json.load(f)
        elif a.row:
            row = json.loads(a.row)
        else:
            raise SystemExit("append 需要 --row-file 或 --row")
        if not isinstance(row, dict):
            raise SystemExit(json.dumps(_err(ERR_ROW_INVALID, next_step="一行记录应是 JSON 对象，例如 {\"称呼\": \"老师\"}"),
                                       ensure_ascii=False))
        return append(a.project, table_by_key(load_schema(), a.table), row)
    if a.cmd == "append-batch":
        with open(a.rows_file, encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise SystemExit("--rows-file 里应为 JSON 数组，不是单个对象")
        table = table_by_key(load_schema(), a.table)
        names = {f["name"] for f in table["fields"]}
        bad = sorted({k for row in rows if isinstance(row, dict) for k in row.keys() if k not in names})
        if bad:
            raise SystemExit("字段名不在「%s」里：%s。可用字段：%s" %
                             (table["name"], " / ".join(bad), " / ".join(sorted(names))))
        return append_batch(a.project, table, rows)
    return read(a.project, table_by_key(load_schema(), a.table), a.limit)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("probe"); q.add_argument("--project", required=True); q.add_argument("--env", default="local", choices=["cloud", "local"])
    q = sub.add_parser("init"); q.add_argument("--project", required=True); q.add_argument("--tier", default=None); q.add_argument("--env", default=None, choices=["cloud", "local"])
    q = sub.add_parser("seed"); q.add_argument("--project", required=True)
    q = sub.add_parser("state"); q.add_argument("--project", required=True)
    q = sub.add_parser("append"); q.add_argument("--project", required=True); q.add_argument("--table", required=True)
    q.add_argument("--row", default=None, help="直接给 JSON 字符串（引号易被 shell 吃掉，优先用 --row-file）")
    q.add_argument("--row-file", default=None, help="从文件读一行 JSON，推荐")
    q = sub.add_parser("append-batch"); q.add_argument("--project", required=True); q.add_argument("--table", required=True)
    q.add_argument("--rows-file", required=True, help="从文件读 JSON 数组（多行批量，推荐）")
    q = sub.add_parser("read"); q.add_argument("--project", required=True); q.add_argument("--table", required=True); q.add_argument("--limit", type=int, default=20)
    a = p.parse_args()

    try:
        r = _dispatch(a)
    except SystemExit:
        raise
    except Exception as e:
        print(json.dumps(_err(ERR_STATE_BROKEN, detail=str(e),
                              next_step="把报错第一行反馈给教练；先备份已有档案，再决定是否重跑"),
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 1 if isinstance(r, dict) and r.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
