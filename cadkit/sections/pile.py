# -*- coding: utf-8 -*-
"""桩锚 / 悬臂桩支护剖面（对应 VB 的 `PileSupport`）。

分段：放坡 → 平台 → 冠梁 → 支护桩 → 坑壁 → 基底。
桩顶埋深、桩长、冠梁尺寸都来自参数；悬臂桩没有锚杆/内支撑，
靠嵌固段平衡，所以桩长明显大于开挖深度。
"""

import math

from . import base
from .base import (draw_drainage, draw_excavation_outline, draw_guardrail,
                   draw_notes_and_title, draw_soil_dims, draw_soils,
                   draw_surcharge, fill_titleblock, setup_sheet)


def draw(ctx):
    P = ctx.P
    dh, sh = 150.0, 80.0          # 地面硬化厚 / 喷射混凝土面层厚

    setup_sheet(ctx)
    draw_soils(ctx)
    print("[3] 开挖轮廓 / 冠梁 / 支护桩 / 面层 / 排水")

    draw_excavation_outline(ctx)
    draw_guardrail(ctx)
    draw_drainage(ctx)

    # 冠梁
    bx0 = ctx.X_PILE_FACE - ctx.X_BEAM_HALF
    w = 2 * ctx.X_BEAM_HALF
    hb = ctx.poly([(bx0, ctx.Y_PILE_TOP), (bx0 + w, ctx.Y_PILE_TOP),
                   (bx0 + w, ctx.Y_BEAM_BOT), (bx0, ctx.Y_BEAM_BOT)], "冠梁")
    ctx.hatch(hb, "AR-CONC", 8.0, 256, "冠梁")

    # 支护桩
    hp = ctx.poly([(ctx.X_PILE_BACK, ctx.Y_BEAM_BOT), (ctx.X_PILE_FACE, ctx.Y_BEAM_BOT),
                   (ctx.X_PILE_FACE, ctx.Y_PILE_BOT), (ctx.X_PILE_BACK, ctx.Y_PILE_BOT)],
                  "支护桩")
    ctx.hatch(hp, "AR-CONC", 8.0, 256, "支护桩")

    # 桩间挂网喷射混凝土面层（贴桩前面）
    ctx.poly([(ctx.X_PILE_FACE, ctx.Y_SLOPE_BOT), (ctx.X_PILE_FACE + sh, ctx.Y_SLOPE_BOT),
              (ctx.X_PILE_FACE + sh, ctx.Y_BOT), (ctx.X_PILE_FACE, ctx.Y_BOT)],
             "桩间挂网")

    print("    冠梁 %.0f×%.0f  桩 Φ%.0f@%.0f L=%.1fm  %s"
          % (w, P["冠梁高"], P["桩径"], P["桩间距"], P["桩长"], P["砼标号"]))

    draw_surcharge(ctx)

    print("[5] 尺寸标注")
    dx = ctx.X_RIGHT + 1600
    ctx.dim((ctx.X_PLAT_END, ctx.Y_TOP), (ctx.X_PLAT_END, ctx.Y_BOT),
            (dx, (ctx.Y_TOP + ctx.Y_BOT) / 2), math.pi / 2)
    ctx.dim((ctx.X_PILE_FACE, ctx.Y_TOP), (ctx.X_PILE_FACE, ctx.Y_PILE_TOP),
            (dx + 2600, (ctx.Y_TOP + ctx.Y_PILE_TOP) / 2), math.pi / 2)
    ctx.dim((ctx.X_PILE_FACE, ctx.Y_BEAM_BOT), (ctx.X_PILE_FACE, ctx.Y_PILE_BOT),
            (dx + 4200, (ctx.Y_BEAM_BOT + ctx.Y_PILE_BOT) / 2), math.pi / 2)
    ctx.dim((0.0, ctx.Y_TOP), (ctx.X_PLAT_END, ctx.Y_TOP),
            (ctx.X_PLAT_END / 2, ctx.Y_TOP + 2600), 0)
    draw_soil_dims(ctx)

    ctx.line((0.0, ctx.Y_TOP + 2500), (0.0, ctx.Y_PILE_BOT - 1500), "剖面图用轴线")
    ax = ctx.X_PLAT_END + 1200
    ctx.text("冠梁 %.0f×%.0f" % (w, P["冠梁高"]), (ax, ctx.Y_BEAM_BOT - 1200))
    ctx.text("支护桩 Φ%.0f@%.0f，L=%.1fm" % (P["桩径"], P["桩间距"], P["桩长"]),
             (ax, ctx.Y_PILE_BOT + 2500))
    ctx.text("基底标高 %.3fm" % P["基底标高"], (ax, ctx.Y_BOT + 900))

    draw_notes_and_title(ctx)
    fill_titleblock(ctx)
