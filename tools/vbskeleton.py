# -*- coding: utf-8 -*-
"""提炼 VBA 过程的绘图骨架：图层定义 + 各类 Add* 调用 + 坐标模式。

2300 行的 VBA 里大半是变量声明和赋值样板，真正决定「画什么」的
是 Layers.Add 和 ModelSpace.Add* 那些调用。先看骨架再决定怎么移植。

    python tools/vbskeleton.py slopeSupport
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vbextract import extract  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    name = sys.argv[1]
    body = extract(name)
    if not body:
        print("找不到过程:", name)
        return 1
    lines = body.splitlines()
    print("=== %s（%d 行）===\n" % (name, len(lines)))

    print("--- 图层定义 ---")
    for l in lines:
        if "Layers.Add" in l:
            print("   ", l.strip())

    print("\n--- 各类绘图调用统计 ---")
    ops = collections.Counter()
    for l in lines:
        for m in re.finditer(r"\.(Add\w+|InsertBlock|Offset|Boolean|Explode)\s*\(", l):
            ops[m.group(1)] += 1
    for k, v in ops.most_common():
        print("    %-22s %d" % (k, v))

    print("\n--- 用到的块 ---")
    for l in lines:
        m = re.search(r'InsertBlock\([^,]+,\s*"([^"]+)"', l)
        if m:
            print("   ", m.group(1))

    print("\n--- 关键赋值（出现最多的变量）---")
    assigns = collections.Counter()
    for l in lines:
        m = re.match(r"\s*(\w+)\s*=\s*[^=]", l)
        if m and not m.group(1) in ("i", "j", "k", "n"):
            assigns[m.group(1)] += 1
    for k, v in assigns.most_common(25):
        print("    %-20s %d 次" % (k, v))

    print("\n--- 带注释的段落标题 ---")
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("'") and len(s) > 3 and not s.startswith("'" * 3):
            if any(ch in s for ch in "画绘插建标注层"):
                print("    %4d| %s" % (i, s[:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
