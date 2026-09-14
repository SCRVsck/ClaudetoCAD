# -*- coding: utf-8 -*-
"""桩身配筋详图（对应 VB 的 `Reinforcement`，1045 行）。

这是一张**独立的大样图**，不是剖面 —— 画在剖面的右侧空白处：
圆形桩截面 + 周边纵筋 + 箍筋 + 加劲箍 + 直径/保护层尺寸 + 配筋注释。

矩形截面（支撑梁）走另一条分支：矩形 + 上下两排纵筋 + 箍筋弯钩。
"""

import math

from . import base

TXT = base.TXT


def _round_section(ctx, cx, cy, d):
    """圆形桩截面配筋大样。"""
    r = d / 2.0
    cover = ctx.P.get("保护层", 50.0)
    rs = r - cover - 12.0            # 箍筋半径（再让出半个箍筋直径）

    ctx.circle((cx, cy), r, "截面配筋")                     # 桩身轮廓
    ctx.circle((cx, cy), rs, "截面配筋")                    # 箍筋
    ctx.circle((cx, cy), rs - 60.0, "截面配筋")             # 加劲箍

    n = int(ctx.P.get("纵筋根数", 20))
    dia = ctx.P.get("纵筋直径", 20)
    for i in range(n):
        a = 2 * math.pi * i / n
        x = cx + (rs - 60.0 - dia / 2.0) * math.cos(a)
        y = cy + (rs - 60.0 - dia / 2.0) * math.sin(a)
        ctx.circle((x, y), dia / 2.0, "截面配筋")

    # 尺寸：直径 + 保护层
    ctx.dim((cx - r, cy - r), (cx + r, cy - r), (cx, cy - r - 900), 0)
    ctx.dim((cx - r, cy - r), (cx - r, cy + r), (cx - r - 900, cy), math.pi / 2)

    # 注释
    n2 = int(ctx.P.get("箍筋直径", 8))
    tx = cx + r + 1200
    ctx.text("桩身配筋大样", (cx - r, cy + r + 1200), h=500)
    ctx.text("%dΦ%d 纵筋（%s）"
             % (n, dia, ctx.P.get("纵筋级别", "HRB400")), (tx, cy + r - 400))
    ctx.text("Φ%d@%d 螺旋箍筋" % (n2, int(ctx.P.get("箍筋间距", 200))),
             (tx, cy + r - 1200))
    ctx.text("Φ%d@2000 加劲箍" % int(ctx.P.get("加劲箍直径", 16)),
             (tx, cy + r - 2000))
    ctx.text("保护层 %dmm" % int(cover), (tx, cy + r - 2800))
    ctx.text("混凝土 %s" % ctx.P.get("砼标号", "C30"), (tx, cy + r - 3600))


def _rect_section(ctx, cx, cy, b, h):
    """矩形截面（支撑梁）配筋大样。"""
    cover = ctx.P.get("保护层", 50.0)
    ctx.poly([(cx - b / 2, cy - h / 2), (cx + b / 2, cy - h / 2),
              (cx + b / 2, cy + h / 2), (cx - b / 2, cy + h / 2)], "截面配筋")
    # 箍筋
    ctx.poly([(cx - b / 2 + cover, cy - h / 2 + cover),
              (cx + b / 2 - cover, cy - h / 2 + cover),
              (cx + b / 2 - cover, cy + h / 2 - cover),
              (cx - b / 2 + cover, cy + h / 2 - cover)], "截面配筋")
    # 上下两排纵筋
    n = max(2, int(ctx.P.get("纵筋根数", 6)))
    dia = ctx.P.get("纵筋直径", 25)
    for row, yy in (("上", cy + h / 2 - cover - dia / 2),
                    ("下", cy - h / 2 + cover + dia / 2)):
        for i in range(n):
            x = cx - b / 2 + cover + dia / 2 + \
                (b - 2 * cover - dia) * i / (n - 1)
            ctx.circle((x, yy), dia / 2.0, "截面配筋")
    ctx.dim((cx - b / 2, cy - h / 2), (cx + b / 2, cy - h / 2),
            (cx, cy - h / 2 - 900), 0)
    ctx.dim((cx - b / 2, cy - h / 2), (cx - b / 2, cy + h / 2),
            (cx - b / 2 - 900, cy), math.pi / 2)
    tx = cx + b / 2 + 1200
    ctx.text("支撑梁配筋大样", (cx - b / 2, cy + h / 2 + 1200), h=500)
    ctx.text("%dΦ%d 上下各%d根" % (n * 2, dia, n), (tx, cy + h / 2 - 400))
    ctx.text("Φ8@200 箍筋", (tx, cy + h / 2 - 1200))
    ctx.text("保护层 %dmm" % int(cover), (tx, cy + h / 2 - 2000))


def draw(ctx):
    """配筋详图通常附在剖面图右侧的空白处，所以这里**不插图框**。

    落位要留在图签栏左侧的绘图区里（图签栏自 x≈14944 起）——
    早先放在 X_RIGHT+9000，正好压到图签栏上。
    """
    P = ctx.P
    print("[R] 配筋详图")
    cx = ctx.X_RIGHT + 4200.0
    cy = ctx.Y_TOP - 3600.0

    shape = P.get("截面形式", "圆形")
    if shape == "矩形":
        b = P.get("截面宽", 800.0)
        h = P.get("截面高", 800.0)
        _rect_section(ctx, cx, cy, b, h)
    else:
        _round_section(ctx, cx, cy, P["桩径"])
    print("    %s截面 Φ%.0f，纵筋 %dΦ%s"
          % (shape, P["桩径"], int(P.get("纵筋根数", 20)),
             P.get("纵筋直径", 20)))
