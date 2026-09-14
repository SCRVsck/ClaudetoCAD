# -*- coding: utf-8 -*-
"""被动区加固（对应 VB 的 `passiveZoneReinforcement`，372 行）。

在**坑底以下**用水泥土搅拌桩 / 三轴搅拌桩 / 高压旋喷桩把土体加固，
提高被动区抗力、控制坑底隆起。按台阶级数布置，从上往下逐级收窄。

原 VB 还处理「高喷过渡」（两种桩型之间的过渡段），这里也留着。
"""

from . import base

TXT = base.TXT


def _pile_kind(ctx):
    """加固桩类型 -> (宽度 mm, 显示名)。"""
    k = ctx.P.get("加固桩型", "水泥土搅拌桩")
    if "三轴" in k:
        return 850.0, "三轴水泥土搅拌桩"
    if "旋喷" in k or "高喷" in k:
        return 600.0, "高压旋喷桩"
    return 700.0, "水泥土搅拌桩"


def draw(ctx):
    """被动区加固通常叠加在剖面图上，所以**不插图框**。"""
    P = ctx.P
    print("[P] 被动区加固")

    total_h = P.get("加固深度", 4000.0)        # 加固总深（基底以下）
    top_w = P.get("加固宽度", 6000.0)          # 加固总宽
    n_step = max(1, int(P.get("加固台阶数", 1)))
    pw, pname = _pile_kind(ctx)

    widths = [top_w * (n_step - i) / n_step for i in range(n_step)]
    x0 = ctx.X_PLAT_END                      # 加固区从坑壁起
    y0 = ctx.Y_BOT

    # 加固区外框
    pts = [(x0, y0)]
    yy = y0
    for w in widths:
        pts.append((x0 + w, yy))
        yy -= total_h / n_step
        pts.append((x0 + w, yy))
    pts.append((x0, yy))
    hp = ctx.poly(pts, "被动区加固")
    ctx.hatch(hp, "ANSI37", 25.0, 9, "被动区加固")

    # 加固桩：每级台阶内按桩宽排布
    n_pile = 0
    yy = y0
    for w in widths:
        h = total_h / n_step
        cnt = max(1, int(w // (pw * 1.05)))
        gap = w / cnt
        for i in range(cnt):
            cx = x0 + gap * (i + 0.5)
            ctx.poly([(cx - pw / 2, yy), (cx + pw / 2, yy),
                      (cx + pw / 2, yy - h), (cx - pw / 2, yy - h)],
                     "被动区加固")
            n_pile += 1
        yy -= h

    # 高喷过渡段（两种桩型交界）
    if ctx.P.get("高喷过渡"):
        ctx.poly([(x0 + widths[0], y0), (x0 + widths[0] + 600, y0),
                  (x0 + widths[0] + 600, yy), (x0 + widths[0], yy)],
                 "被动区加固")
        ctx.text("高喷过渡", (x0 + widths[0] + 800, y0 - 800), h=300)

    ctx.text("被动区加固：%s，深%.1fm，宽%.1fm，%d级台阶"
             % (pname, total_h / 1000.0, top_w / 1000.0, n_step),
             (x0 + 1000, y0 - total_h - 1200))
    ctx.text("加固区", (x0 + top_w * 0.35, y0 - total_h / 2), h=400)
    print("    %s，%d 级台阶，%d 根" % (pname, n_step, n_pile))
