# -*- coding: utf-8 -*-
"""共用绘图底座。

各类支护剖面（桩锚/放坡/双排桩/配筋/被动区/内支撑）大量内容是重复的：
土层分带 + 填充 + 标注、尺寸、注释、图框、图签栏。原先都堆在
`draw_section.py` 里，再加五类会膨胀到两千行，所以抽出来。

坐标约定与标准图一致：**y=0 是坡顶地面线，标高向下为负，单位 mm**。
`Ctx` 负责把「剖面坐标」换算成「图纸坐标」（含每张图的水平偏移）。
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
import cad  # noqa: E402
from cadkit import standard  # noqa: E402

# ---------------------------------------------------------------- 图幅
FRAME_INSERT = [-1000.0, -11000.0]
FRAME_BOX = (-19750.0, -25850.0, 22250.0, 3850.0)
SHEET_PITCH = 52000.0          # 相邻两张图的水平间距（实测演示图）

# 标准文字样式。原字体 Tssdeng.shx 本机多半没有 —— 缺字体时 AutoCAD
# 什么都不画（不是变 ?，是彻底空白），所以要有替代方案。
TEXT_STYLE = "PM-TEXT"
STD_FONT, STD_BIGFONT = "tssdeng.shx", "gbcbig.shx"
ALT_FONT, ALT_BIGFONT = "gbenor.shx", "gbcbig.shx"

TXT = 400.0
DIMTXT = 350.0
TITLE_H = 600.0

# 图签栏各格落字位置，逐格量自演示图（块里没有属性，格子是空的）
TITLE_CELLS = {
    "项目名称": ((17240.0, -19850.0), 600.0),
    "图名":     ((17030.0, -21650.0), 600.0),
    "专业":     ((20658.0, -22750.0), 400.0),
    "图号":     ((20325.0, -23550.0), 300.0),
    "设计阶段": ((17268.0, -24300.0), 400.0),
    "版本号":   ((20578.0, -24350.0), 400.0),
    "出图日期": ((17075.0, -25100.0), 300.0),
}


class Ctx:
    """一次出图的上下文：参数 + 图纸偏移 + 绘图原语。"""

    def __init__(self, params, sheet_dx=0.0, ox=-2250.0, oy=600.0,
                 x_left=-15000.0, x_right=8000.0, failed=None):
        self.P = params
        self.SHEET_DX = sheet_dx
        self.OX, self.OY = ox, oy
        self.X_LEFT, self.X_RIGHT = x_left, x_right
        self.FAILED = failed if failed is not None else []
        self._compute()

    # ---- 关键标高/坐标 ----
    def _compute(self):
        P = self.P
        self.Y_TOP = 0.0
        self.Y_PILE_TOP = self.Y(P["桩顶标高"])
        self.Y_BEAM_BOT = self.Y_PILE_TOP - P["冠梁高"]
        self.Y_SLOPE_BOT = -P["放坡总高"]
        self.Y_BOT = self.Y(P["基底标高"])
        self.Y_PILE_BOT = self.Y_BEAM_BOT - P["桩长"] * 1000.0
        self.Y_SOIL_BOT = -P["土层"][-1][2] * 1000.0
        self.X_SLOPE_END = P["放坡坡宽"]
        self.X_PLAT_END = self.X_SLOPE_END + P["放坡平台宽"]
        self.X_PILE_FACE = self.X_PLAT_END
        self.X_PILE_BACK = self.X_PILE_FACE - P["桩径"]
        self.X_BEAM_HALF = (P["桩径"] + 2 * P["冠梁外扩"]) / 2.0

    def Y(self, elev_m):
        """标高(m) -> 图面 y（mm，坡顶为 0，向下为负）。"""
        return (elev_m - self.P["坡顶标高"]) * 1000.0

    def YX(self, x, y):
        return x + self.OX + self.SHEET_DX, y + self.OY

    def FX(self, x):
        """图纸绝对坐标 -> 当前张。"""
        return x + self.SHEET_DX

    def profile_x(self, y):
        """开挖轮廓在某个深度处的 x。**各类支护可以覆盖它**。

        默认是「桩锚/悬臂」那种单级轮廓：1:1 放坡 → 平台 → 竖壁。
        放坡土钉是多级台阶，双排桩又是另一种，各自覆盖即可。

        注意 y = -放坡总高 处轮廓是**多值**的（坡脚 / 平台外沿），
        这里统一返回外沿；需要坡脚那个值时调用方显式用 X_SLOPE_END。
        """
        P = self.P
        if y <= self.Y_BOT:
            return self.X_RIGHT
        if y >= self.Y_TOP:
            return 0.0
        if y > -P["放坡总高"]:
            return -y
        return self.X_PLAT_END

    def profile_breaks(self):
        """轮廓发生转折的那些 y 值（土层多边形要在这些深度取点）。"""
        return [-self.P["放坡总高"]]

    def profile_break_inner(self, y):
        """某转折点处轮廓的**内侧** x。

        放坡底是典型的多值点：坡脚在内、平台外沿在外。土层多边形的底边
        正好落在这里时只能用坡脚（平台是挖掉的），取错就多出一条斜边。
        返回 None 表示该处只有一个值。
        """
        if abs(y + self.P["放坡总高"]) < 1e-6:
            return self.X_SLOPE_END
        return None

    def pit_wall_x(self):
        """坑壁在**基底稍上方**的 x。

        不能直接用 `profile_x(Y_BOT)` —— 那个在 `y <= Y_BOT` 时返回的是
        坑底右边界（X_RIGHT），而土层多边形需要的是「沿坑壁下到基底」
        那个转折点。少了它，穿底的土层会从坑壁顶直接斜拉到右边界。
        """
        return self.X_PLAT_END

    # ---- 绘图原语 ----
    def call(self, req, quiet=False, record=True):
        r = cad.send(req)
        if not r.get("ok"):
            if record:
                self.FAILED.append((req.get("cmd"), r.get("error")))
            if not quiet:
                print("   !! %s 失败: %s"
                      % (req.get("cmd"), str(r.get("error"))[:140]))
        return r

    def poly(self, pts, layer, closed=True, xform=True):
        if xform:
            pts = [self.YX(x, y) for x, y in pts]
        return self.call({"cmd": "add_polyline", "closed": closed, "layer": layer,
                          "points": [[x, y, 0.0] for x, y in pts]}).get("handle")

    def line(self, p1, p2, layer, xform=True):
        if xform:
            p1, p2 = self.YX(*p1), self.YX(*p2)
        return self.call({"cmd": "add_line", "layer": layer,
                          "start": [p1[0], p1[1], 0.0],
                          "end": [p2[0], p2[1], 0.0]}).get("handle")

    def text(self, s, at, h=TXT, layer="注释", xform=True):
        if xform:
            at = self.YX(*at)
        return self.call({"cmd": "add_text", "text": s, "layer": layer,
                          "insert": [at[0], at[1], 0.0],
                          "height": h}).get("handle")

    def mtext(self, s, at, h=TXT, layer="注释", width=8000.0, xform=True):
        if xform:
            at = self.YX(*at)
        return self.call({"cmd": "add_mtext", "text": s, "layer": layer,
                          "insert": [at[0], at[1], 0.0], "height": h,
                          "width": width}).get("handle")

    def dim(self, p1, p2, loc, angle, color=3, h=DIMTXT, mode="rotated",
            layer="尺寸标注"):
        a, b, c = self.YX(*p1), self.YX(*p2), self.YX(*loc)
        req = {"cmd": "add_dim", "mode": mode, "p1": [a[0], a[1], 0.0],
               "p2": [b[0], b[1], 0.0], "loc": [c[0], c[1], 0.0],
               "color": color, "layer": layer, "text_height": h}
        if mode == "rotated":
            req["angle"] = angle
        return self.call(req, quiet=True)

    def hatch(self, boundary, pattern, scale, color, layer):
        r = self.call({"cmd": "hatch", "boundary": boundary, "pattern": pattern,
                       "scale": scale, "color": color, "layer": layer},
                      quiet=True, record=False)
        return r.get("ok", False)

    def hatch_soil(self, boundary, soil_name_or_pat, color=None):
        """按土层名（或直接给图案名）填充，图案不可用时退到标准图案。"""
        from cadkit import standard as _s
        if soil_name_or_pat in _s.SOIL_PATTERNS or \
           soil_name_or_pat in _s.FALLBACK_PATTERNS:
            pat, col, scale, _fb = _s.soil_style(soil_name_or_pat)
        else:
            pat, col, scale = soil_name_or_pat, (color or 7), 15.0
        if self.hatch(boundary, pat, scale, col, "土层线"):
            return pat, False
        self.hatch(boundary, "ANSI31", _s.SOIL_PATTERN_SCALE_FALLBACK,
                   col, "土层线")
        return "ANSI31", True

    def block(self, name, at, layer=None, scale=1.0, rot=0.0, xform=True):
        if xform:
            at = self.YX(*at)
        req = {"cmd": "insert", "name": name, "layer": layer,
               "point": [at[0], at[1], 0.0],
               "xscale": scale, "yscale": scale, "zscale": scale, "rotation": rot}
        return self.call(req, quiet=True).get("handle")

    def circle(self, c, r, layer, xform=True):
        if xform:
            c = self.YX(*c)
        return self.call({"cmd": "add_circle", "layer": layer,
                          "center": [c[0], c[1], 0.0],
                          "radius": float(r)}).get("handle")


# ============================================================ 共用绘制
def ensure_layers(ctx):
    """补齐标准表里有、模板里缺的图层。

    模板是演示图，图层未必齐全（实测缺 桩间挂网、竖向隔渗帷幕、平面图用轴线）。
    给实体设不存在的图层会报「未找到主键」，而且报在建图元那一步，
    看起来像几何数据有问题。已有的不动，保留模板配好的颜色/线型。
    """
    t = cad.send({"cmd": "tables"})
    have = {L["name"] for L in t.get("layers", [])}
    made = []
    for name, (lt, color) in standard.LAYERS.items():
        if name not in have:
            ctx.call({"cmd": "layer", "name": name, "color": color,
                      "linetype": lt}, quiet=True)
            made.append(name)
    # 非标准表、但绘图会用到的补充图层
    for name, color in (("主动区加固", 8), ("桩排间加固", 30), ("截面配筋", 1)):
        if name not in have:
            ctx.call({"cmd": "layer", "name": name, "color": color,
                      "linetype": "Continuous"}, quiet=True)
            made.append(name)
    if made:
        print("    补建缺失图层：%s" % "、".join(made))


def setup_sheet(ctx):
    """插标准图框、补图层、切标准文字样式。"""
    print("[1] 标准图框 / 图层 / 文字样式")
    ensure_layers(ctx)
    r = ctx.call({"cmd": "insert", "name": "CSSDI-A3", "layer": "图框",
                  "point": [FRAME_INSERT[0] + ctx.SHEET_DX, FRAME_INSERT[1], 0.0],
                  "xscale": 1.0, "yscale": 1.0, "zscale": 1.0})
    print("    图框句柄 %s" % r.get("handle"))

    base = {"cmd": "textstyle", "name": TEXT_STYLE, "width": 0.7, "height": 0.0}
    r = ctx.call({**base, "font": STD_FONT, "bigfont": STD_BIGFONT},
                 quiet=True, record=False)
    if r.get("ok"):
        used = "%s + %s（标准原字体）" % (STD_FONT, STD_BIGFONT)
    else:
        r2 = ctx.call({**base, "font": ALT_FONT, "bigfont": ALT_BIGFONT}, quiet=True)
        used = ("%s + %s（替代；本机缺 %s）" % (ALT_FONT, ALT_BIGFONT, STD_FONT)
                if r2.get("ok") else "SimHei")
        if not r2.get("ok"):
            ctx.call({**base, "font": "SimHei"}, quiet=True)
    ctx.call({"cmd": "activestyle", "name": TEXT_STYLE}, quiet=True)
    print("    文字样式 %s：%s，字高 %g" % (TEXT_STYLE, used, TXT))


def exc_x_at(ctx, y):
    """开挖轮廓在某深度处的 x（转发到 ctx.profile_x，各类支护可覆盖）。"""
    return ctx.profile_x(y)


def layer_polygon_pts(ctx, y_top, y_bot):
    """某土层在图面上的多边形。

    从左上角出发、沿开挖轮廓往下走、再回到左下角。轮廓由 `ctx.profile_x`
    给出（默认是单级放坡→平台→竖壁；放坡土钉会换成多级台阶）。

    早先的写法只用「落在区间内的转折点」拼点，结果顶边被直接从最左端
    斜拉到坡底 —— ① 层变成了三角形，坡面画成一条横贯全图的斜线。
    还有 y = -放坡总高 处轮廓多值，取错那个就多出一条斜边。
    """
    X_LEFT, X_RIGHT = ctx.X_LEFT, ctx.X_RIGHT
    if y_top <= ctx.Y_BOT:
        return [(X_LEFT, y_top), (X_RIGHT, y_top),
                (X_RIGHT, y_bot), (X_LEFT, y_bot)]

    # 把轮廓在 [y_bot, y_top] 区间内的所有转折点都取出来
    marks = [k for k in ctx.profile_breaks() if y_bot < k < y_top]
    pts = [(X_LEFT, y_top), (ctx.profile_x(y_top), y_top)]
    for k in sorted(marks, reverse=True):
        pts.append((ctx.profile_x(k), k))
        inner = ctx.profile_break_inner(k)
        if inner is not None:
            pts.append((inner, k))
    if y_bot >= ctx.Y_BOT:
        endx = ctx.profile_x(y_bot)
        inner = ctx.profile_break_inner(y_bot)
        pts.append((inner if inner is not None else endx, y_bot))
    else:
        pts.append((ctx.pit_wall_x(), ctx.Y_BOT))
        pts.append((X_RIGHT, ctx.Y_BOT))
        pts.append((X_RIGHT, y_bot))
    pts.append((X_LEFT, y_bot))

    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def draw_soils(ctx):
    """土层：分带轮廓 + 图案填充 + 参数标注。"""
    print("[2] 土层：分带轮廓 + 图案填充 + 标注")
    top = ctx.Y_TOP
    for no, name, depth_m, c, phi in ctx.P["土层"]:
        bot = -depth_m * 1000.0
        h = ctx.poly(layer_polygon_pts(ctx, top, bot), "土层线")
        pat, fb = ctx.hatch_soil(h, name)
        mid = (top + bot) / 2.0
        ctx.text("%s %s" % (no, name), (ctx.X_LEFT + 700, mid + 600))
        ctx.text("C=%g kPa  φ=%g°" % (c, phi), (ctx.X_LEFT + 700, mid - 500))
        print("    %-8s %5.1fm  %s%s"
              % (name, depth_m, pat, "（兜底）" if fb else ""))
        top = bot


def draw_soil_dims(ctx):
    """左侧各土层厚度尺寸。"""
    top = ctx.Y_TOP
    for _no, _n, depth_m, _c, _p in ctx.P["土层"]:
        bot = -depth_m * 1000.0
        ctx.dim((ctx.X_LEFT, top), (ctx.X_LEFT, bot),
                (ctx.X_LEFT - 1800, (top + bot) / 2), math.pi / 2)
        top = bot


def draw_excavation_outline(ctx):
    """地面线 / 放坡 / 平台 / 坑壁 / 坑底。"""
    P = ctx.P
    ctx.line((ctx.X_LEFT, ctx.Y_TOP), (0.0, ctx.Y_TOP), "土层线")
    ctx.line((0.0, ctx.Y_TOP), (ctx.X_SLOPE_END, ctx.Y_SLOPE_BOT), "边坡线")
    ctx.line((ctx.X_SLOPE_END, ctx.Y_SLOPE_BOT),
             (ctx.X_PLAT_END, ctx.Y_SLOPE_BOT), "边坡线")
    ctx.line((ctx.X_PLAT_END, ctx.Y_SLOPE_BOT), (ctx.X_PLAT_END, ctx.Y_BOT),
             "边坡线")
    ctx.line((ctx.X_PLAT_END, ctx.Y_BOT), (ctx.X_RIGHT, ctx.Y_BOT), "边坡线")


def draw_surcharge(ctx):
    """地面超载：一排向下的箭头。"""
    ld = ctx.P.get("荷载")
    if not ld:
        return
    x0, x1 = ld["起点距"], ld["起点距"] + ld["宽"]
    y = ctx.Y_TOP
    ctx.line((x0, y), (x1, y), "其它")
    n = 8
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        ctx.line((x, y), (x, y - 800), "其它")
        ctx.line((x, y - 800), (x - 200, y - 500), "其它")
        ctx.line((x, y - 800), (x + 200, y - 500), "其它")
    ctx.text("q=%s" % ld["值"], ((x0 + x1) / 2.0 - 600, y + 700))


def draw_drainage(ctx):
    """坑内排水沟 + 坡顶截水沟 + 地面硬化。"""
    x0 = ctx.X_PLAT_END
    ctx.poly([(x0 + 1200, ctx.Y_BOT), (x0 + 2000, ctx.Y_BOT),
              (x0 + 2000, ctx.Y_BOT - 400), (x0 + 1200, ctx.Y_BOT - 400)],
             "其它")
    dh = 150.0
    ctx.poly([(ctx.X_LEFT, ctx.Y_TOP), (0.0, ctx.Y_TOP),
              (0.0, ctx.Y_TOP - dh), (ctx.X_LEFT, ctx.Y_TOP - dh)], "其它")
    ctx.text("地面硬化 宽3.5m 厚%dmm 砼C15" % dh,
             (ctx.X_LEFT + 500, ctx.Y_TOP + 700))
    ctx.poly([(ctx.X_LEFT + 200, ctx.Y_TOP - dh),
              (ctx.X_LEFT + 700, ctx.Y_TOP - dh),
              (ctx.X_LEFT + 700, ctx.Y_TOP - dh - 400),
              (ctx.X_LEFT + 200, ctx.Y_TOP - dh - 400)], "其它")


def draw_guardrail(ctx):
    """坡顶护栏（简化栏杆符号）。"""
    for i in range(6):
        x = ctx.X_LEFT + 500 + i * 1400
        ctx.line((x, ctx.Y_TOP), (x, ctx.Y_TOP + 900), "其它")
    ctx.line((ctx.X_LEFT + 500, ctx.Y_TOP + 900),
             (ctx.X_LEFT + 500 + 5 * 1400, ctx.Y_TOP + 900), "其它")


def draw_notes_and_title(ctx):
    """图名 + 设计说明。

    图框和图签栏不在这里画 —— 那是标准块 CSSDI-A3 的职责。
    """
    print("[6] 图名 / 设计说明")
    x0 = ctx.FX(FRAME_BOX[0] + 2500)
    y_base = ctx.Y_SOIL_BOT + ctx.OY
    ctx.text(ctx.P["图名"], (x0, y_base - 1400), h=TITLE_H,
             layer="图名", xform=False)
    ctx.text("  比例 %s" % ctx.P["比例"], (x0, y_base - 2500), h=TXT,
             layer="图名", xform=False)

    notes = ctx.P.get("设计说明") or [
        "设计说明：",
        "1 图中标高以米（m）为单位，其他尺寸均以毫米（mm）为单位；",
        "2 本工程采用相对标高，±0.000=%.3fm；" % ctx.P["正负零标高"],
        "3 基坑等级为%s，支护结构类型为%s，砼标号%s；"
        % (ctx.P["基坑等级"], ctx.P["支护类型"], ctx.P["砼标号"]),
        "4 基坑周边应设围挡，坡顶3.5m范围内不得堆载；",
        "5 施工前应完成降水，基坑内设排水沟与集水井，及时抽排；",
        "6 开挖应分层分段进行，严禁超挖，开挖至基底后及时浇筑垫层；",
        "7 未尽事宜按相应规范执行。",
    ]
    ny = y_base - 3600
    half = (len(notes) + 1) // 2
    for i, s in enumerate(notes):
        col, row = (0, i) if i < half else (1, i - half)
        ctx.text(s, (x0 + col * 17500, ny - row * 620), h=TXT,
                 layer="设计说明", xform=False)


def fill_titleblock(ctx):
    """把工程信息填进图签栏各格（块里没有属性，只能按坐标放文字）。"""
    P = ctx.P
    vals = {
        "项目名称": "%s基坑支护工程" % P.get("名称", ""),
        "图名": P.get("图名") or "%s支护结构剖面图" % P.get("名称", ""),
        "专业": P.get("专业", "基坑"),
        "图号": P.get("图号") or "",
        "设计阶段": P.get("设计阶段", "施工图"),
        "版本号": P.get("版本号", "V1.0"),
        "出图日期": P.get("日期") or "",
    }
    filled = []
    for key, (at, h) in TITLE_CELLS.items():
        v = vals.get(key)
        if not v:
            continue
        ctx.text(v, (ctx.FX(at[0]), at[1]), h=h, layer="图框", xform=False)
        filled.append(key)
    print("[7] 图签栏填格：%s" % "、".join(filled))


def zoom_to_sheets(call, n_sheets=1, sheet_dx=0.0):
    """缩放到图框。call 是发送指令的可调用对象（ctx.call 或 cad.send）。"""
    x0, y0, x1, y1 = FRAME_BOX
    if n_sheets <= 1:
        call({"cmd": "zoom", "mode": "center",
              "center": [x0 + (x1 - x0) / 2 + sheet_dx, (y0 + y1) / 2, 0.0],
              "height": (y1 - y0) * 1.1})
    else:
        total = (x1 - x0) + (n_sheets - 1) * SHEET_PITCH
        call({"cmd": "zoom", "mode": "center",
              "center": [x0 + total / 2, (y0 + y1) / 2, 0.0],
              "height": total * 0.62})
