#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成程序图标 assets/cadbridge.ico。

图形是一个线框立方体 —— 同时点出「CAD」和「三维实体建模」两件事。
按 4 倍分辨率绘制再降采样，得到平滑边缘；输出多尺寸 ico（16~256）。
"""

import os

from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "assets", "cadbridge.ico")

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4                      # 超采样倍数

BG_TOP = (27, 58, 92)       # 深海军蓝
BG_BOTTOM = (14, 32, 54)
EDGE = (232, 244, 255)      # 近白
ACCENT = (86, 204, 242)     # 青色高光


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((size, size))


def make(size):
    s = size * SS
    img = gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 立方体的等轴测顶点（按 256 的画布设计，再按比例缩放）
    def P(x, y):
        k = s / 256.0
        return (x * k, y * k)

    T = P(128, 52)
    R = P(196, 92)
    L = P(60, 92)
    C = P(128, 132)
    B = P(128, 212)
    BR = P(196, 172)
    BL = P(60, 172)

    d = ImageDraw.Draw(img)
    w = max(2, int(s * 0.038))

    # 三条汇聚到中心的棱用青色，其余用近白 —— 让立方体有前后层次
    def line(a, b, color=EDGE, width=w):
        d.line([a, b], fill=color + (255,), width=width, joint="curve")

    # 顶面
    line(T, R)
    line(T, L)
    # 侧棱（青色，突出「桥接」的中心）
    line(C, T, ACCENT)
    line(C, L, ACCENT)
    line(C, R, ACCENT)
    # 左面
    line(L, BL)
    line(BL, B)
    # 右面
    line(R, BR)
    line(BR, B)
    # 底棱
    line(C, B)

    img = img.resize((size, size), Image.LANCZOS)
    img.putalpha(rounded_mask(size, radius=int(size * 0.22)))
    return img


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames = [make(n) for n in SIZES]
    frames[0].save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
    print("已生成 %s（%s）" % (OUT, ", ".join("%dpx" % n for n in SIZES)))


if __name__ == "__main__":
    main()
