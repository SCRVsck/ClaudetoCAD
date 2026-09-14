#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按工程图标准生成「基坑支护结构剖面图」。

    python draw_section.py CD段 --template           # 内置参数
    python draw_section.py --rtf eg/桩悬臂.rtf        # 一份计算书 → 一张图
    python draw_section.py --dir 计算书目录/           # 一批计算书 → 一册图
    python draw_section.py list                       # 看有哪些类型/工点

实现都在 `cadkit/draw.py` —— 这样打包进 exe 之后 `cadbridge draw` 能用同一份，
不必要求用户另外装 Python 才能绘图。
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from cadkit import draw  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    def opt(key):
        if key in argv:
            i = argv.index(key)
            if i + 1 < len(argv):
                return argv[i + 1]
        return None

    if "list" in argv:
        return draw.run(draw.CASES, list_only=True)

    rtf = opt("--rtf")
    folder = opt("--dir")
    template = opt("--template-dwg")
    outdir = opt("--out")
    named = [a for a in argv if not a.startswith("-")
             and a not in (rtf, folder, template, outdir)]

    if not (rtf or folder):
        name = named[0] if named else "CD段"
        if name not in draw.CASES:
            print("未知工点 %r，可选：%s" % (name, "、".join(draw.CASES)))
            print("（用 `python draw_section.py list` 看全部类型）")
            return 2
        case = draw.CASES[name]
    else:
        case = None

    return draw.run(case, rtf=rtf, folder=folder, template=template,
                    outdir=outdir)


if __name__ == "__main__":
    sys.exit(main())
