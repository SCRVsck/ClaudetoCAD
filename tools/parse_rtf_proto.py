# -*- coding: utf-8 -*-
"""原型：把天汉软件输出的计算书 RTF 解析成结构化参数。

只为验证可行性 —— 不做完整实现。跑法：
    python tools/parse_rtf_proto.py "eg/桩悬臂.rtf"
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rtftext import rtf_text  # noqa: E402


def sections(text):
    """按「AB段_N ...」切段，返回 {标题: [行, ...]}"""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^(\S*?段_\d+(?:\.\d+)?)\s+(.*)$", line)
        if m:
            cur = "%s %s" % (m.group(1), m.group(2).strip())
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return out


def pairs(lines):
    """「项目 值 项目 值」的两列键值对 -> dict"""
    d = {}
    for line in lines:
        if re.match(r"^(项目|序号|单位)\b", line):
            continue
        toks = line.split()
        # 两列：(k1 v1 k2 v2)；也可能单列 (k v)
        if len(toks) >= 4 and len(toks) % 2 == 0:
            half = len(toks) // 2
            for i in (0, half):
                d[toks[i]] = " ".join(toks[i + 1:half if i == 0 else len(toks)])
        elif len(toks) == 2:
            d[toks[0]] = toks[1]
    return d


def num(s):
    """从 '23.000m' / '-2.500m(20.5m)' / '1.2' 里取数"""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s))
    return float(m.group(0)) if m else None


def soil_table(lines):
    """土层信息表 -> [{编号,名称,层底埋深,C,φ}, ...]"""
    rows = []
    for line in lines:
        toks = line.split()
        # 形如： 1 ① 杂填土 1.5 8 10 1800 30
        if len(toks) >= 6 and re.match(r"^\d+$", toks[0]) and "土" in line or "岩" in line:
            try:
                rows.append({"序号": int(toks[0]), "编号": toks[1], "名称": toks[2],
                             "层底埋深": float(toks[3]), "C": float(toks[4]),
                             "φ": float(toks[5])})
            except (ValueError, IndexError):
                continue
    return rows


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else r"D:\P\cad\eg\桩悬臂.rtf"
    secs = sections(rtf_text(path))
    print("切出 %d 个段落：\n" % len(secs))

    for title, lines in secs.items():
        if "土层信息" in title:
            rows = soil_table(lines)
            print("[%s] 解析出 %d 层土：" % (title, len(rows)))
            for r in rows:
                print("    %s %-8s 层底 %5.1fm  C=%-5g φ=%g"
                      % (r["编号"], r["名称"], r["层底埋深"], r["C"], r["φ"]))
        elif "综合信息" in title or "桩排信息" in title or "冠梁信息" in title:
            d = pairs(lines)
            print("[%s] 解析出 %d 项：" % (title, len(d)))
            for k, v in list(d.items())[:8]:
                print("    %-16s = %-22s (数值 %s)" % (k, v, num(v)))
        else:
            print("[%s]（%d 行，未解析）" % (title, len(lines)))
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
