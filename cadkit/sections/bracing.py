# -*- coding: utf-8 -*-
"""内支撑 + 格构柱（对应 VB 的 `SupportSystemMaker`）。

原 VB 那一版是**平面图**的交互式做法：提示用户在图上选线、再按交点
归并成杆件，而且算法部分（交点排序）代码是空的、没写完。
剖面图里的内支撑要简单得多，所以这里按剖面画：

    水平内支撑（腰梁/围檩）+ 立柱（格构柱）+ 立柱桩

内支撑沿基坑竖向可设多道，格构柱插在支撑交点处往下扎进立柱桩。
"""

import math

from . import base

TXT = base.TXT


def draw(ctx):
    """内支撑通常叠加在剖面图上，所以**不插图框**。"""
    P = ctx.P
    print("[B] 内支撑 / 格构柱")

    n = max(1, int(P.get("支撑道数", 1)))
    top = P.get("首道支撑埋深", 1500.0)          # 坡顶以下 mm
    step = P.get("支撑竖向间距", 3000.0)
    sec_w = P.get("支撑截面宽", 800.0)
    sec_h = P.get("支撑截面高", 800.0)

    x_in = ctx.X_PLAT_END                        # 坑内
    x_out = min(ctx.X_RIGHT, ctx.X_PLAT_END + 9000.0)

    for i in range(n):
        y = -top - i * step
        if y <= ctx.Y_BOT:
            break
        # 围檩（贴坑壁）
        ctx.poly([(x_in - 300, y + sec_h / 2), (x_in + 300, y + sec_h / 2),
                  (x_in + 300, y - sec_h / 2), (x_in - 300, y - sec_h / 2)],
                 "腰梁")
        # 水平支撑
        hs = ctx.poly([(x_in, y + sec_h / 2), (x_out, y + sec_h / 2),
                       (x_out, y - sec_h / 2), (x_in, y - sec_h / 2)], "内支撑")
        ctx.hatch(hs, "AR-CONC", 6.0, 256, "内支撑")
        ctx.text("第%d道支撑 %.0f×%.0f" % (i + 1, sec_w, sec_h),
                 (x_in + 1500, y + 500), h=350)

        # 格构柱：从支撑交点往下扎进立柱桩
        cx = x_in + 4500.0
        cw = P.get("格构柱宽", 480.0)
        col_bot = ctx.Y_BOT - P.get("立柱桩长", 6000.0)
        hc = ctx.poly([(cx - cw / 2, y), (cx + cw / 2, y),
                       (cx + cw / 2, col_bot), (cx - cw / 2, col_bot)],
                      "格构柱")
        # 格构柱的缀板（每隔一段一道横线，示意格构式）
        yy = y - 600.0
        while yy > col_bot:
            ctx.line((cx - cw / 2, yy), (cx + cw / 2, yy), "格构柱")
            yy -= 600.0

    # 立柱桩
    if n:
        cx = x_in + 4500.0
        dw = P.get("立柱桩径", 800.0)
        pb = ctx.Y_BOT - P.get("立柱桩长", 6000.0)
        hp = ctx.poly([(cx - dw / 2, ctx.Y_BOT), (cx + dw / 2, ctx.Y_BOT),
                       (cx + dw / 2, pb), (cx - dw / 2, pb)], "支护桩")
        ctx.hatch(hp, "AR-CONC", 8.0, 256, "支护桩")
        ctx.text("立柱桩 Φ%.0f，L=%.1fm" % (dw, P.get("立柱桩长", 6000.0) / 1000.0),
                 (cx + 1200, pb + 1200), h=350)

    ctx.text("内支撑：共%d道，%s" % (n, P.get("支撑材料", "钢筋混凝土支撑")),
             (x_in + 1500, ctx.Y_BOT + 1500), h=350)
    print("    %d 道支撑 + 格构柱 + 立柱桩" % n)
