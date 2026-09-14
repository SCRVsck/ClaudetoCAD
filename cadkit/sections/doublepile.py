# -*- coding: utf-8 -*-
"""双排桩支护剖面（对应 VB 的 `DoublePileSupport`，771 行）。

与单排桩的区别：前后两排桩 + 顶部冠梁把两排连起来 + 中部连梁，
两排之间是**桩间土**（起固结作用），有的还带桩排间加固。
"""

import math

from . import base
from .base import (draw_drainage, draw_excavation_outline, draw_guardrail,
                   draw_notes_and_title, draw_soil_dims, draw_soils,
                   draw_surcharge, fill_titleblock, setup_sheet)


def draw(ctx):
    P = ctx.P
    d = P.get("桩排间距", 2400.0)        # 前后排净距
    beam_h = P.get("连梁高", 600.0)

    setup_sheet(ctx)
    draw_soils(ctx)
    print("[3] 双排桩 / 冠梁 / 连梁 / 桩间土")

    draw_excavation_outline(ctx)
    draw_guardrail(ctx)
    draw_drainage(ctx)

    # 前排（临坑侧）与后排
    front_back = ctx.X_PILE_FACE - P["桩径"]
    rear_face = front_back - d
    rear_back = rear_face - P["桩径"]
    top = ctx.Y_BEAM_BOT
    bot = ctx.Y_PILE_BOT

    for (xa, xb), tag in (((front_back, ctx.X_PILE_FACE), "前排"),
                          ((rear_back, rear_face), "后排")):
        h = ctx.poly([(xa, top), (xb, top), (xb, bot), (xa, bot)], "支护桩")
        ctx.hatch(h, "AR-CONC", 8.0, 256, "支护桩")

    # 桩间土（两排之间）
    hs = ctx.poly([(rear_face, top), (front_back, top),
                   (front_back, ctx.Y_BOT + 2000), (rear_face, ctx.Y_BOT + 2000)],
                  "桩排间加固")
    ctx.hatch(hs, "ANSI31", 20.0, 30, "桩排间加固")
    ctx.text("桩间土", ((rear_face + front_back) / 2 - 600,
                       (top + ctx.Y_BOT) / 2 + 1500))

    # 冠梁：盖住两排桩
    w = rear_face - rear_back + d + (ctx.X_PILE_FACE - front_back)
    bx0 = rear_back - P["冠梁外扩"]
    hb = ctx.poly([(bx0, ctx.Y_PILE_TOP), (ctx.X_PILE_FACE + P["冠梁外扩"], ctx.Y_PILE_TOP),
                   (ctx.X_PILE_FACE + P["冠梁外扩"], ctx.Y_BEAM_BOT),
                   (bx0, ctx.Y_BEAM_BOT)], "冠梁")
    ctx.hatch(hb, "AR-CONC", 8.0, 256, "冠梁")

    # 连梁（中部，把两排连起来）
    ly = ctx.Y_BOT + 3000.0
    hl = ctx.poly([(rear_back, ly), (ctx.X_PILE_FACE, ly),
                   (ctx.X_PILE_FACE, ly - beam_h), (rear_back, ly - beam_h)], "腰梁")
    ctx.hatch(hl, "AR-CONC", 8.0, 256, "腰梁")

    print("    双排桩 Φ%.0f@%.0f，排距 %.0fmm，L=%.1fm"
          % (P["桩径"], P["桩间距"], d, P["桩长"]))
    ctx.text("双排桩 Φ%.0f@%.0f" % (P["桩径"], P["桩间距"]),
             (ctx.X_PILE_FACE + 1200, top - 1200))
    ctx.text("排距 %.1fm" % (d / 1000.0), (ctx.X_PILE_FACE + 1200, top - 2200))
    ctx.text("连梁 %.0f×%.0f" % (ctx.X_PILE_FACE - rear_back, beam_h),
             (ctx.X_PILE_FACE + 1200, ly - 300))

    draw_surcharge(ctx)

    print("[5] 尺寸标注")
    dx = ctx.X_RIGHT + 1600
    ctx.dim((ctx.X_PLAT_END, ctx.Y_TOP), (ctx.X_PLAT_END, ctx.Y_BOT),
            (dx, (ctx.Y_TOP + ctx.Y_BOT) / 2), math.pi / 2)
    ctx.dim((ctx.X_PILE_FACE, ctx.Y_BEAM_BOT), (ctx.X_PILE_FACE, ctx.Y_PILE_BOT),
            (dx + 2600, (ctx.Y_BEAM_BOT + ctx.Y_PILE_BOT) / 2), math.pi / 2)
    ctx.dim((rear_back, ctx.Y_PILE_TOP), (ctx.X_PILE_FACE, ctx.Y_PILE_TOP),
            ((rear_back + ctx.X_PILE_FACE) / 2, ctx.Y_PILE_TOP + 2600), 0)
    draw_soil_dims(ctx)

    ctx.text("基底标高 %.3fm" % P["基底标高"], (ctx.X_PLAT_END + 1200, ctx.Y_BOT + 900))
    draw_notes_and_title(ctx)
    fill_titleblock(ctx)
