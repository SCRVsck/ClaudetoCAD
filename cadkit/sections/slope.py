# -*- coding: utf-8 -*-
"""放坡土钉支护剖面（对应 VB 的 `slopeSupport`，2309 行）。

和桩锚最大的不同：**开挖轮廓是多级台阶**，不是「单坡+竖壁」。
所以这里覆盖 `profile_x` / `profile_breaks` / `profile_break_inner`，
土层多边形会自动跟着台阶走。

图上画：多级坡面（内/外双线）+ 坡面喷砼填充 + 坡面土钉 + 坡顶土钉 +
泄水管 + 截水沟/排水沟 + 坡比注释 + 锚杆信息表 + 尺寸。
"""

import math

from . import base
from .base import (draw_notes_and_title, draw_soil_dims, draw_soils,
                   fill_titleblock, setup_sheet)

TXT = base.TXT


class SlopeCtx(base.Ctx):
    """放坡专用上下文：把开挖轮廓换成多级台阶。"""

    def __init__(self, params, **kw):
        super().__init__(params, **kw)
        self._build_steps()

    def _build_steps(self):
        """台阶表：[{顶, 底, 坡脚x, 平台外x}, ...]（自上而下）。"""
        P = self.P
        depth = -self.Y_BOT
        h0 = P["放坡总高"]
        w0 = P["放坡坡宽"]
        p0 = P["放坡平台宽"]

        if P.get("放坡台阶"):
            spec = list(P["放坡台阶"])
        else:
            # 没给台阶表就按「坡高/坡宽/平台宽」重复到坑底
            spec, y = [], 0.0
            while depth - y > 1.0:
                h = min(h0, depth - y)
                k = h / h0 if h0 else 1.0
                spec.append((h, w0 * k, p0 if depth - y > h + 1.0 else 0.0))
                y += h
        steps, y, x = [], 0.0, 0.0
        for h, w, p in spec:
            top = -y
            y += h
            x += w
            steps.append({"顶": top, "底": -y, "坡脚x": x, "平台外x": x + p})
            x += p
        self.STEPS = steps
        self.X_TOE = x                    # 坡脚最外沿

    # ---- 轮廓 ----
    def profile_x(self, y):
        if y <= self.Y_BOT:
            return self.X_RIGHT
        if y >= self.Y_TOP:
            return 0.0
        for s in self.STEPS:
            if y >= s["底"]:
                # 在该级内：按坡比插值（1:1 时 x = -y 也成立）
                t = (s["顶"] - y) / (s["顶"] - s["底"]) if s["顶"] != s["底"] else 0.0
                x_top = s["坡脚x"] - (s["坡脚x"] - self._x_at_top(s))
                return self._x_at_top(s) + (s["坡脚x"] - self._x_at_top(s)) * t
            if y >= s["底"]:
                break
        # 落在某级平台上
        for s in self.STEPS:
            if abs(y - s["底"]) < 1e-6:
                return s["平台外x"]
        return self.STEPS[-1]["平台外x"]

    def _x_at_top(self, step):
        i = self.STEPS.index(step)
        return 0.0 if i == 0 else self.STEPS[i - 1]["平台外x"]

    def profile_breaks(self):
        """每级坡脚 + 每级平台外沿都是转折点。"""
        out = []
        for s in self.STEPS:
            out += [s["底"], s["底"]]
        return out

    def profile_break_inner(self, y):
        for s in self.STEPS:
            if abs(y - s["底"]) < 1e-6:
                return s["坡脚x"]      # 坡脚（内侧）；平台外沿是外侧
        return None

    def pit_wall_x(self):
        """放坡的坑底边线在最下一级的坡脚处。"""
        return self.STEPS[-1]["坡脚x"]


# ---------------------------------------------------------------- 绘制
def _draw_slope_face(ctx):
    """坡面内外双线 + 喷砼填充。"""
    pts = [(ctx._x_at_top(s), s["顶"]) for s in ctx.STEPS]
    pts.append((ctx.STEPS[-1]["坡脚x"], ctx.STEPS[-1]["底"]))
    ctx.poly(pts, "边坡线", closed=False)
    # 外线（往土体内偏移一个面层厚）
    sh = 100.0
    out = [(x + sh, y) for x, y in pts]
    ctx.poly(out, "边坡线", closed=False)
    # 面层填充
    band = pts + list(reversed(out))
    hb = ctx.poly(band, "桩间挂网")
    ctx.hatch(hb, "AR-CONC", 6.0, 256, "桩间挂网")


def _draw_nails(ctx):
    """坡面土钉 + 坡顶土钉。"""
    P = ctx.P
    ln = P.get("土钉长", 6000.0)
    n_row = int(P.get("土钉排数", 0)) or max(1, len(ctx.STEPS))
    total = 0
    for s in ctx.STEPS:
        h = s["顶"] - s["底"]
        # 每级按坡高定排数，至少 1 排
        rows = max(1, int(round(h / 1500.0)))
        for r in range(rows):
            t = (r + 0.5) / rows
            y = s["顶"] - h * t
            x0 = ctx._x_at_top(s) + (s["坡脚x"] - ctx._x_at_top(s)) * t
            # 土钉水平打入土体
            ctx.line((x0, y), (x0 - ln, y), "土钉")
            # 端头小横线（插筋标识）
            ctx.line((x0, y - 150), (x0, y + 150), "土钉")
            total += 1
    # 坡顶土钉
    for i in range(2):
        x = -(i + 1) * 1500.0
        ctx.line((x, ctx.Y_TOP), (x - ln * 0.8, ctx.Y_TOP), "土钉")
        ctx.line((x, ctx.Y_TOP - 150), (x, ctx.Y_TOP + 150), "土钉")
        total += 1
    ctx.text("土钉 Φ110@1500，L=%.1fm，入射角15°" % (ln / 1000.0),
             (ctx.X_LEFT + 700, ctx.Y_TOP - 3200))
    print("    土钉 %d 根" % total)
    return total


def _draw_weep_holes(ctx):
    """泄水管：按坡高布设。"""
    n = 0
    for s in ctx.STEPS:
        h = s["顶"] - s["底"]
        cnt = max(1, int(round(h / 2000.0)))
        for r in range(cnt):
            t = (r + 0.5) / cnt
            y = s["顶"] - h * t
            x0 = ctx._x_at_top(s) + (s["坡脚x"] - ctx._x_at_top(s)) * t
            ctx.line((x0, y), (x0 - 400, y), "其它")
            ctx.line((x0 - 400, y - 120), (x0 - 400, y + 120), "其它")
            n += 1
    if n:
        ctx.text("泄水管 Φ50@2000，外倾5%%", (ctx.X_LEFT + 700, ctx.Y_TOP - 3900))
    print("    泄水管 %d 个" % n)


def _draw_anchor_table(ctx):
    """锚杆（土钉）信息表 —— 原图放在坡脚右侧的空白处。"""
    rows = ctx.P.get("土钉表") or []
    if not rows:
        return
    x0 = ctx.X_TOE + 2500.0
    y1 = ctx.Y_BOT + 1000.0
    rh = 700.0
    cols = [1400, 1600, 1600, 1600, 1600]
    tw = sum(cols)

    def cell(r, c):
        return (x0 + sum(cols[:c]), y1 - rh * r)

    for r in range(len(rows) + 1):
        ctx.line(cell(r, 0), (x0 + tw, y1 - rh * r), "其它")
    for c in range(len(cols) + 1):
        x = x0 + sum(cols[:c])
        ctx.line((x, y1), (x, y1 - rh * (len(rows) + 1)), "其它")
    hdr = ["排号", "竖向间距", "水平间距", "长度", "入射角"]
    for c, t in enumerate(hdr):
        ctx.text(t, (cell(0, c)[0] + 150, y1 - rh + 180), h=300)
    for r, row in enumerate(rows, 1):
        for c, v in enumerate(row[:len(cols)]):
            ctx.text(str(v), (cell(r, c)[0] + 150, y1 - rh * (r + 1) + 180), h=300)
    ctx.text("锚杆（土钉）信息表", (x0, y1 + 500), h=380)


def draw(ctx):
    P = ctx.P
    setup_sheet(ctx)
    draw_soils(ctx)
    print("[3] 坡面 / 土钉 / 泄水管")

    _draw_slope_face(ctx)
    _draw_nails(ctx)
    _draw_weep_holes(ctx)

    # 坡脚到底板的开挖线
    ctx.line((ctx.STEPS[-1]["坡脚x"], ctx.Y_BOT), (ctx.X_RIGHT, ctx.Y_BOT), "边坡线")
    # 截水沟（坡顶）
    ctx.poly([(300, ctx.Y_TOP), (800, ctx.Y_TOP),
              (800, ctx.Y_TOP - 400), (300, ctx.Y_TOP - 400)], "其它")
    ctx.poly([(400, ctx.Y_TOP), (700, ctx.Y_TOP),
              (700, ctx.Y_TOP - 300), (400, ctx.Y_TOP - 300)], "其它")
    ctx.text("截水沟 300×400", (900, ctx.Y_TOP + 500))
    ctx.text("地面硬化 宽3.5m 厚150mm 砼C15", (ctx.X_LEFT + 500, ctx.Y_TOP + 1800))

    # 坡比注释
    for i, s in enumerate(ctx.STEPS, 1):
        w = s["坡脚x"] - ctx._x_at_top(s)
        h = s["顶"] - s["底"]
        if h > 0:
            ctx.text("1:%.2g" % (w / h), ((ctx._x_at_top(s) + s["坡脚x"]) / 2 + 500,
                                          (s["顶"] + s["底"]) / 2))

    _draw_anchor_table(ctx)

    # 尺寸
    y = ctx.Y_TOP
    for s in ctx.STEPS:
        ctx.dim((ctx._x_at_top(s), y), (ctx._x_at_top(s), s["底"]),
                (ctx._x_at_top(s) - 1500, (y + s["底"]) / 2), math.pi / 2)
        y = s["底"]
    ctx.dim((0.0, ctx.Y_TOP), (ctx.STEPS[-1]["坡脚x"], ctx.Y_TOP),
            (ctx.STEPS[-1]["坡脚x"] / 2, ctx.Y_TOP + 2600), 0)
    draw_soil_dims(ctx)

    ctx.text("坡顶标高 %.3fm" % P["坡顶标高"], (-6800, ctx.Y_TOP + 700))
    ctx.text("基底标高 %.3fm" % P["基底标高"],
             (ctx.X_TOE + 1000, ctx.Y_BOT + 700))

    draw_notes_and_title(ctx)
    fill_titleblock(ctx)
