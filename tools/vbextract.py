# -*- coding: utf-8 -*-
"""从 VBA 模块里抽出某个过程/函数的源码。"""
import re
import sys

SRC = r"D:\P\cad\eg\Drawing Module.vb"


def load():
    return open(SRC, "rb").read().decode("utf-8")


def extract(name, text=None):
    txt = text if text is not None else load()
    lines = txt.splitlines()
    start = None
    for i, l in enumerate(lines):
        if re.match(r"\s*(?:Public |Private )?(?:Sub|Function)\s+%s\b" % re.escape(name), l):
            start = i
            break
    if start is None:
        return None
    # 从下一行起找同级的 End Sub / End Function
    end = None
    for j in range(start + 1, len(lines)):
        if re.match(r"\s*End (Sub|Function)\b", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end + 1]) if end else "\n".join(lines[start:])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    name = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
    body = extract(name)
    if body is None:
        print("找不到过程:", name)
    else:
        lines = body.splitlines()
        print("=== %s（%d 行）===" % (name, len(lines)))
        for l in lines[:limit]:
            print(l)
        if len(lines) > limit:
            print("...（还有 %d 行）" % (len(lines) - limit))
