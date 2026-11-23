"""文档一致性自校验 / 自动同步。

用途：SKILL.md 里的底库数字、表名、建档字段，容易和 schema.json、底库源文件脱节。
本脚本以 schema.json 与 references 里的两份底库为唯一事实源，重算后：
  · 校验模式（默认）：不一致就列出问题并非零退出
  · 修复模式（--fix）：把 SKILL.md 的数字块与相关句子重写成正确值

用法：
  python scripts/check_consistency.py
  python scripts/check_consistency.py --fix
"""
import argparse
import importlib.util
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")

MARK_START = "<!-- AUTO:counts"
MARK_END = "<!-- /AUTO:counts -->"


def load_tio():
    spec = importlib.util.spec_from_file_location("table_io_c", os.path.join(HERE, "table_io.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read(path):
    return io.open(path, encoding="utf-8").read()


def counts():
    tio = load_tio()
    std = tio.parse_standards(read(os.path.join(REF, "standards-library.md")))
    cap_txt = read(os.path.join(REF, "capcut-knowledge.md"))
    cap = tio.parse_capcut(cap_txt)
    tab = tio.parse_taboos(cap_txt)
    pen = tio.parse_pending(cap_txt)
    head = tio.parse_head(cap_txt)
    return {"standards": len(std), "capcut": len(cap), "taboos": len(tab),
            "pending": len(pen), "head": len(head),
            "total": len(std) + len(cap) + len(tab) + len(pen) + len(head)}


def citation_ids():
    """底库实际存在的条文编号集合（标准 Sx-xx、剪映 Jxx），供引用回查。"""
    tio = load_tio()
    std = tio.parse_standards(read(os.path.join(REF, "standards-library.md")))
    cap = tio.parse_capcut(read(os.path.join(REF, "capcut-knowledge.md")))
    return {x["编号"] for x in std} | {x["编号"] for x in cap}


# 只回查引用方文件；两份底库自身是编号定义处，不作为引用扫描对象
_CITE_FILES = ["SKILL.md", "references/main-prompt.md", "references/init-prompt.md",
               "references/delivery-rules.md", "references/red-lines.md",
               "references/troubleshooting.md"]


def auto_block(c):
    return (MARK_START + " 由 scripts/check_consistency.py 生成，勿手改 -->\n"
            "底库合计 **%d** 条：标准 %d／剪映 %d／禁忌 %d／待核验 %d／库头索引 %d；档案表 **%d** 张。\n"
            % (c["total"], c["standards"], c["capcut"], c["taboos"], c["pending"], c["head"], c_tables())
            + MARK_END)


_C_TABLES = [None]


def c_tables():
    return _C_TABLES[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="把 SKILL.md 的数字与句子重写为正确值")
    a = ap.parse_args()

    schema = json.loads(read(os.path.join(ROOT, "tables", "schema.json")))
    _C_TABLES[0] = len(schema["tables"])
    c = counts()
    skill_path = os.path.join(ROOT, "SKILL.md")
    skill = read(skill_path)
    issues = []

    # 1) AUTO 数字块
    block = auto_block(c)
    if MARK_START not in skill:
        if a.fix:
            anchor = "本 skill 是**装好就用**的教练包"
            idx = skill.find(anchor)
            if idx < 0:
                issues.append("找不到插入 AUTO 块的位置")
            else:
                end = skill.find("\n\n", idx)
                skill = skill[:end + 2] + block + "\n\n" + skill[end + 2:]
        else:
            issues.append("SKILL.md 缺 AUTO:counts 数字块（用 --fix 生成）")
    else:
        old = skill[skill.index(MARK_START): skill.index(MARK_END) + len(MARK_END)]
        if old != block:
            if a.fix:
                skill = skill.replace(old, block)
            else:
                issues.append("AUTO 数字块与实际条数不符：%s" % old.replace("\n", " ")[:90])

    # 2) 正文散落的数字句
    rules = [
        (r"灌 \d+ 条底库", "灌 %d 条底库" % c["total"]),
        (r"灌底库——标准 \d+ 条、剪映 \d+ 条、禁忌 \d+ 条、待核验 \d+ 项、库头与索引 \d+ 行",
         "灌底库——标准 %d 条、剪映 %d 条、禁忌 %d 条、待核验 %d 项、库头与索引 %d 行"
         % (c["standards"], c["capcut"], c["taboos"], c["pending"], c["head"])),
        (r"灌底库 \d+ 条（标准 \d+／剪映 \d+／禁忌 \d+／待核验 \d+／库头索引 \d+，",
         "灌底库 %d 条（标准 %d／剪映 %d／禁忌 %d／待核验 %d／库头索引 %d，" %
         (c["total"], c["standards"], c["capcut"], c["taboos"], c["pending"], c["head"])),
        (r"底库灌好了（\d+ 条：标准 \d+／剪映 \d+／禁忌 \d+／待核验 \d+／库头索引 \d+）",
         "底库灌好了（%d 条：标准 %d／剪映 %d／禁忌 %d／待核验 %d／库头索引 %d）" %
         (c["total"], c["standards"], c["capcut"], c["taboos"], c["pending"], c["head"])),
    ]
    for pat, want in rules:
        m = re.search(pat, skill)
        if not m:
            issues.append("SKILL.md 里找不到这句（可能被改写）：%s" % pat[:30])
            continue
        if m.group(0) != want:
            if a.fix:
                skill = skill.replace(m.group(0), want)
            else:
                issues.append("数字过期：「%s」应为「%s」" % (m.group(0), want))

    # 3) 已废弃写法
    for bad in ("47＋44", "91 条"):
        if bad in skill:
            issues.append("SKILL.md 残留旧口径「%s」" % bad)

    # 4) init-prompt 的十表名单 vs schema（只看「建在线档案库」那一节，避免抓到开头使用说明的编号）
    init = read(os.path.join(REF, "init-prompt.md"))
    sec_start = init.find("建档案库")
    sec_end = init.find("兜底：", sec_start if sec_start >= 0 else 0)
    sec = init[sec_start:sec_end] if sec_start >= 0 and sec_end > sec_start else ""
    listed = re.findall(r"^\s*(\d+)\.\s*([^\s：:（]+)", sec, re.M)
    order = [name for num, name in listed if 1 <= int(num) <= 10]
    names = [t["name"] for t in schema["tables"]]
    if order[:10] != names:
        issues.append("init-prompt 十表名单与 schema 不一致：%s vs %s" % (order[:10], names))

    # 5) SKILL.md 建档表里点到的学员档案字段必须都在 schema 里
    prof = [t for t in schema["tables"] if t["name"] == "学员档案"][0]
    field_names = [f["name"] for f in prof["fields"]]
    for line in skill.splitlines():
        if line.startswith("|") and "学员档案：" in line:
            seg = line.split("学员档案：", 1)[1]
            for f in re.split(r"[、／|]", seg):
                f = f.strip()
                if not f or f.startswith("卡片") or "字段名" in f:
                    continue
                if f not in field_names:
                    issues.append("建档表字段「%s」不在学员档案里（可用：%s）" % (f, " / ".join(field_names[:8])))

    # 6) 表头数字（10 张）
    if ("%d 张" % c_tables()) not in skill and ("%d 表" % c_tables()) not in skill:
        issues.append("SKILL.md 未出现表数量 %d" % c_tables())

    # 7) 条文引用回查：引用方文件里出现的 Sx-xx / Jxx 必须在底库编号集合内（C3）
    valid = citation_ids()
    for rel in _CITE_FILES:
        txt = read(os.path.join(ROOT, rel))
        for ref in sorted(set(re.findall(r"S\d-\d+|J\d\d", txt))):
            if ref not in valid:
                issues.append("条文编号悬空：%s（%s 不在标准库／剪映库）" % (ref, rel))

    if a.fix:
        io.open(skill_path, "w", encoding="utf-8", newline="\n").write(skill)
        print(json.dumps({"fixed": True, "counts": c, "tables": c_tables(),
                          "remaining_issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not issues else 1

    print(json.dumps({"ok": not issues, "counts": c, "tables": c_tables(),
                      "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
