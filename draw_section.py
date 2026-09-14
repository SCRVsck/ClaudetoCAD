#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按工程图标准生成「基坑支护结构剖面图」——完整图纸（含图框/图签/设计说明）。

    python draw_section.py                 # 默认 CD段（悬臂段）
    python draw_section.py AB段             # 演示同源的 AB 段（桩撑/锚）
    python draw_section.py CD段 --new       # 先新建图纸再画

图层、线型、土层填充图案等约定取自 cadkit/standard.py，
而那是从用户提供的 eg/Drawing Module.vb 里逐条抄出来的。

坐标约定（与那套图纸一致）：
    y = 0 是坡顶地面线，标高向下为负；单位 mm。
    剖面本身以坡顶为原点，再整体平移到图纸幅面内。
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402
from cadkit import standard  # noqa: E402

# ============================================================ 参数（工点）
# 每个工点就是一组参数；「不同于演示」只要换一组即可。
CASES = {
    # ---------- 新工点：真悬臂桩（无锚无撑）----------
    "CD段": {
        "名称": "CD段（悬臂段）",
        "图名": "CD段支护结构剖面图",
        "图号": "JS-07-2",
        "设计号": "2024-118",
        "日期": "2024.06.20",
        "比例": "1:100",
        "基坑等级": "二级基坑",
        "支护类型": "悬臂桩",
        "正负零标高": 19.500,
        "坡顶标高": 18.500,
        "基底标高": 12.000,      # 开挖 6.5m
        "桩顶标高": 17.000,      # 桩顶埋深 1.5m
        "桩长": 15.0,
        "桩径": 1000.0,
        "桩间距": 1300.0,
        "冠梁高": 700.0,
        "冠梁外扩": 100.0,
        "放坡总高": 1500.0,
        "放坡坡宽": 1500.0,      # 1:1
        "放坡平台宽": 1000.0,
        "砼标号": "C30",
        # 编号、名称、层底埋深(m)、C(kPa)、φ(°)
        "土层": [
            ("①", "素填土",        2.0,   5,  8),
            ("②", "粉质粘土",      4.5,  18, 12),
            ("③", "淤泥质粉质粘土",  8.0,  12,  7),
            ("④", "中砂",         12.0,   0, 30),
            ("⑤", "强风化泥岩",    18.0,  60, 25),
        ],
        "荷载": {"起点距": 2000.0, "宽": 6000.0, "值": "20kPa"},
    },
    # ---------- 演示同源：桩撑/锚结构（用于对照）----------
    "AB段": {
        "名称": "AB段（桩撑/锚）",
        "图名": "AB段支护结构剖面图",
        "图号": "JS-04-1",
        "设计号": "2017-616",
        "日期": "2017.10.16",
        "比例": "1:100",
        "基坑等级": "二级基坑",
        "支护类型": "桩墙撑锚结构",
        "正负零标高": 23.000,
        "坡顶标高": 22.000,
        "基底标高": 17.000,
        "桩顶标高": 20.500,
        "桩长": 12.0,
        "桩径": 800.0,
        "桩间距": 1200.0,
        "冠梁高": 600.0,
        "冠梁外扩": 100.0,
        "放坡总高": 1500.0,
        "放坡坡宽": 1500.0,
        "放坡平台宽": 1000.0,
        "砼标号": "C30",
        "土层": [
            ("①", "杂填土",      1.5,   8, 10),
            ("②", "淤泥质粘土",   3.0,  10,  6),
            ("③", "粉质粘土",    10.0,  20, 10),
            ("④", "粘土",       15.0,  30, 15),
            ("⑤", "石灰岩",     20.0, 150, 15),
        ],
        "荷载": {"起点距": 5000.0, "宽": 7000.0, "值": "30kPa"},
    },
}

# ======================================================== 图幅（A2 1:100）
SHEET_W, SHEET_H = 59400.0, 42000.0
MARGIN = 2500.0
# 剖面在图纸中的落位（放左上，右下留给图签）
OX, OY = 20000.0, 36000.0
# 图签栏
TB_W, TB_H = 18000.0, 7000.0
TB_X, TB_Y = SHEET_W - MARGIN - TB_W, MARGIN
# 土层指标表
TBL_X, TBL_Y = 31500.0, 34500.0

# 剖面自身范围（相对坡顶原点）
X_LEFT = -15000.0
X_RIGHT = 8000.0
TXT = 380.0
DIMTXT = 320.0
FAILED = []


# ------------------------------------------------------------ 当前工点
def load_case(name):
    """把一组参数摊成本模块的全局量 —— 绘图函数都直接读这些名字。"""
    global P
    P = CASES[name]
    g = globals()
    g["Y_TOP"] = 0.0
    g["Y_PILE_TOP"] = Y(P["桩顶标高"])
    g["Y_BEAM_BOT"] = Y_PILE_TOP - P["冠梁高"]
    g["Y_SLOPE_BOT"] = -P["放坡总高"]
    g["Y_BOT"] = Y(P["基底标高"])
    g["Y_PILE_BOT"] = Y_BEAM_BOT - P["桩长"] * 1000.0
    g["Y_SOIL_BOT"] = -P["土层"][-1][2] * 1000.0
    g["X_SLOPE_END"] = P["放坡坡宽"]
    g["X_PLAT_END"] = X_SLOPE_END + P["放坡平台宽"]
    g["X_PILE_FACE"] = X_PLAT_END
    g["X_PILE_BACK"] = X_PILE_FACE - P["桩径"]
    g["X_BEAM_HALF"] = (P["桩径"] + 2 * P["冠梁外扩"]) / 2.0


def Y(elev_m):
    """标高(m) -> 图面 y（mm，坡顶为 0，向下为负）。"""
    return (elev_m - P["坡顶标高"]) * 1000.0


def YX(x, y):
    """剖面坐标 -> 图纸坐标。"""
    return x + OX, y + OY


# ------------------------------------------------------------------ 桥接
def call(req, quiet=False, record=True):
    r = cad.send(req)
    if not r.get("ok"):
        if record:
            FAILED.append((req.get("cmd"), r.get("error")))
        if not quiet:
            print("   !! %s 失败: %s" % (req.get("cmd"), str(r.get("error"))[:150]))
    return r


def poly(pts, layer, closed=True, xform=True):
    if xform:
        pts = [YX(x, y) for x, y in pts]
    r = call({"cmd": "add_polyline", "closed": closed,
              "points": [[x, y, 0.0] for x, y in pts]})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


def line(p1, p2, layer, xform=True):
    if xform:
        p1, p2 = YX(*p1), YX(*p2)
    r = call({"cmd": "add_line", "start": [p1[0], p1[1], 0.0],
              "end": [p2[0], p2[1], 0.0]})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


def text(s, at, h=TXT, layer="注释", xform=True):
    if xform:
        at = YX(*at)
    r = call({"cmd": "add_text", "text": s, "insert": [at[0], at[1], 0.0],
              "height": h})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


def dim(p1, p2, loc, angle, color=3, h=DIMTXT, mode="rotated",
        layer="尺寸标注"):
    """尺寸标注：剖面坐标进，内部换算成图纸坐标。"""
    a, b, c = YX(*p1), YX(*p2), YX(*loc)
    req = {"cmd": "add_dim", "mode": mode, "p1": [a[0], a[1], 0.0],
           "p2": [b[0], b[1], 0.0], "loc": [c[0], c[1], 0.0],
           "color": color, "layer": layer, "text_height": h}
    if mode == "rotated":
        req["angle"] = angle
    return call(req, quiet=True)


# ------------------------------------------------------------ 图层与线型
def setup_layers():
    print("[1] 图层 / 线型 / 文字样式（按 standard.py 的表）")
    # 中文必须先建 TrueType 样式，否则整张图的中文会静默变成 ?
    call({"cmd": "textstyle", "name": "工程图", "font": "SimHei"}, quiet=True)
    for lt in standard.LINETYPES:
        call({"cmd": "linetype", "name": lt, "file": "acad.lin"}, quiet=True)
    for name, (lt, color) in standard.LAYERS.items():
        call({"cmd": "layer", "name": name, "color": color, "linetype": lt},
             quiet=True)
    print("    %d 个图层，线型 %s" % (len(standard.LAYERS),
                                    "/".join(standard.LINETYPES)))


# ---------------------------------------------------------------- 土层
def exc_x_at(y):
    """开挖轮廓在某深度处的 x。注意放坡底是多值的，这里取外沿。"""
    if y <= Y_BOT:
        return X_RIGHT
    if y >= Y_TOP:
        return 0.0
    if y > Y_SLOPE_BOT:
        return -y
    return X_PLAT_END


def layer_polygon_pts(y_top, y_bot):
    if y_top <= Y_BOT:
        return [(X_LEFT, y_top), (X_RIGHT, y_top),
                (X_RIGHT, y_bot), (X_LEFT, y_bot)]
    pts = [(X_LEFT, y_top), (exc_x_at(y_top), y_top)]
    k = Y_SLOPE_BOT
    if y_bot < k < y_top:
        pts.append((X_SLOPE_END, k))
        pts.append((X_PLAT_END, k))
    if y_bot >= Y_BOT:
        pts.append((X_SLOPE_END if abs(y_bot - k) < 1e-6 else exc_x_at(y_bot), y_bot))
    else:
        pts.append((X_PLAT_END, Y_BOT))
        pts.append((X_RIGHT, Y_BOT))
        pts.append((X_RIGHT, y_bot))
    pts.append((X_LEFT, y_bot))
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def draw_soils():
    print("[2] 土层：分带轮廓 + 图案填充 + 标注")
    top = Y_TOP
    for no, name, depth_m, c, phi in P["土层"]:
        bot = -depth_m * 1000.0
        h = poly(layer_polygon_pts(top, bot), "土层线")
        pat, color, scale, fallback = standard.soil_style(name)
        r = call({"cmd": "hatch", "boundary": h, "pattern": pat, "scale": scale,
                  "color": color, "layer": "土层线"}, quiet=True, record=False)
        if not r.get("ok"):
            r = call({"cmd": "hatch", "boundary": h, "pattern": "ANSI31",
                      "scale": standard.SOIL_PATTERN_SCALE_FALLBACK,
                      "color": color, "layer": "土层线"}, quiet=True)
            pat, fallback = "ANSI31", True
        mid = (top + bot) / 2.0
        text("%s %s" % (no, name), (X_LEFT + 700, mid + 600))
        text("C=%g kPa  φ=%g°" % (c, phi), (X_LEFT + 700, mid - 500))
        print("    %-8s %5.1fm  %s%s" %
              (name, depth_m, pat, "（兜底）" if fallback else ""))
        top = bot


# ------------------------------------------------------------ 支护结构
def draw_structure():
    print("[3] 开挖轮廓 / 冠梁 / 支护桩 / 面层 / 排水")
    dh = 150.0      # 地面硬化厚
    sh = 80.0       # 喷射混凝土面层厚

    # 地面线（坡顶以左）
    line((X_LEFT, Y_TOP), (0.0, Y_TOP), "土层线")
    # 放坡 + 平台 + 坑壁 + 坑底
    line((0.0, Y_TOP), (X_SLOPE_END, Y_SLOPE_BOT), "边坡线")
    line((X_SLOPE_END, Y_SLOPE_BOT), (X_PLAT_END, Y_SLOPE_BOT), "边坡线")
    line((X_PLAT_END, Y_SLOPE_BOT), (X_PLAT_END, Y_BOT), "边坡线")
    line((X_PLAT_END, Y_BOT), (X_RIGHT, Y_BOT), "边坡线")

    # 地面硬化（坡顶以左 3.5m）
    poly([(X_LEFT, Y_TOP), (0.0, Y_TOP), (0.0, Y_TOP - dh), (X_LEFT, Y_TOP - dh)],
         "其它")
    text("地面硬化 宽3.5m 厚%dmm 砼C15" % dh, (X_LEFT + 500, Y_TOP + 700))

    # 坡顶护栏（简化的栏杆符号）
    for i in range(6):
        x = X_LEFT + 500 + i * 1400
        line((x, Y_TOP), (x, Y_TOP + 900), "其它")
    line((X_LEFT + 500, Y_TOP + 900), (X_LEFT + 500 + 5 * 1400, Y_TOP + 900), "其它")

    # 冠梁
    bx0 = X_PILE_FACE - X_BEAM_HALF
    hb = poly([(bx0, Y_PILE_TOP), (bx0 + 2 * X_BEAM_HALF, Y_PILE_TOP),
               (bx0 + 2 * X_BEAM_HALF, Y_BEAM_BOT), (bx0, Y_BEAM_BOT)], "冠梁")
    if hb:
        call({"cmd": "hatch", "boundary": hb, "pattern": "AR-CONC",
              "scale": standard.pattern_scale("AR-CONC", 8.0),
              "color": 256, "layer": "冠梁"}, quiet=True)

    # 支护桩
    hp = poly([(X_PILE_BACK, Y_BEAM_BOT), (X_PILE_FACE, Y_BEAM_BOT),
               (X_PILE_FACE, Y_PILE_BOT), (X_PILE_BACK, Y_PILE_BOT)], "支护桩")
    if hp:
        call({"cmd": "hatch", "boundary": hp, "pattern": "AR-CONC",
              "scale": standard.pattern_scale("AR-CONC", 8.0),
              "color": 256, "layer": "支护桩"}, quiet=True)

    # 桩间挂网喷射混凝土面层（贴在桩前面）
    poly([(X_PILE_FACE, Y_SLOPE_BOT), (X_PILE_FACE + sh, Y_SLOPE_BOT),
          (X_PILE_FACE + sh, Y_BOT), (X_PILE_FACE, Y_BOT)], "桩间挂网")

    # 坑内排水沟 + 集水井
    poly([(X_PLAT_END + 1200, Y_BOT), (X_PLAT_END + 2000, Y_BOT),
          (X_PLAT_END + 2000, Y_BOT - 400), (X_PLAT_END + 1200, Y_BOT - 400),
          (X_PLAT_END + 1200, Y_BOT)], "其它")
    # 坡顶截水沟
    poly([(X_LEFT + 200, Y_TOP - dh), (X_LEFT + 700, Y_TOP - dh),
          (X_LEFT + 700, Y_TOP - dh - 400), (X_LEFT + 200, Y_TOP - dh - 400),
          (X_LEFT + 200, Y_TOP - dh)], "其它")

    print("    冠梁 %.0f×%.0f  桩 Φ%.0f@%.0f L=%.1fm  %s" %
          (2 * X_BEAM_HALF, P["冠梁高"], P["桩径"], P["桩间距"], P["桩长"],
          P["砼标号"]))


def draw_load():
    print("[4] 地面超载")
    ld = P["荷载"]
    x0, x1 = ld["起点距"], ld["起点距"] + ld["宽"]
    line((x0, Y_TOP), (x1, Y_TOP), "其它")
    n = 8
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        line((x, Y_TOP), (x, Y_TOP - 800), "其它")
        line((x, Y_TOP - 800), (x - 200, Y_TOP - 500), "其它")
        line((x, Y_TOP - 800), (x + 200, Y_TOP - 500), "其它")
    text("q=%s" % ld["值"], ((x0 + x1) / 2.0 - 600, Y_TOP + 700))


def draw_dims():
    print("[5] 尺寸标注（图层「尺寸标注」，色 3）")
    dx = X_RIGHT + 1600
    # 开挖深度
    dim((X_PLAT_END, Y_TOP), (X_PLAT_END, Y_BOT), (dx, (Y_TOP + Y_BOT) / 2),
        math.pi / 2)
    # 桩顶埋深
    dim((X_PILE_FACE, Y_TOP), (X_PILE_FACE, Y_PILE_TOP),
        (dx + 2600, (Y_TOP + Y_PILE_TOP) / 2), math.pi / 2)
    # 桩长
    dim((X_PILE_FACE, Y_BEAM_BOT), (X_PILE_FACE, Y_PILE_BOT),
        (dx + 4200, (Y_BEAM_BOT + Y_PILE_BOT) / 2), math.pi / 2)
    # 放坡宽度
    dim((0.0, Y_TOP), (X_PLAT_END, Y_TOP),
        ((0 + X_PLAT_END) / 2, Y_TOP + 2600), 0)
    # 各土层厚度（左侧）
    top = Y_TOP
    for _no, _n, depth_m, _c, _p in P["土层"]:
        bot = -depth_m * 1000.0
        dim((X_LEFT, top), (X_LEFT, bot), (X_LEFT - 1800, (top + bot) / 2),
            math.pi / 2)


def draw_soil_table():
    """土层物理力学指标表 —— 这类图纸的标配，也把右侧空白利用起来。"""
    print("[7] 土层物理力学指标表")
    cols = [("编号", 1200), ("土层名称", 3400), ("层厚(m)", 1600),
            ("层底埋深(m)", 2200), ("C(kPa)", 1600), ("φ(°)", 1300)]
    rows = []
    prev = 0.0
    for no, name, depth_m, c, phi in P["土层"]:
        rows.append((no, name, "%.1f" % (depth_m - prev),
                     "%.1f" % depth_m, "%g" % c, "%g" % phi))
        prev = depth_m

    rh = 900.0
    tw = sum(c[1] for c in cols)
    th = rh * (len(rows) + 1)
    x0, y1 = TBL_X, TBL_Y
    y0 = y1 - th

    text("土层物理力学指标", (x0, y1 + 700), h=420, layer="注释", xform=False)
    poly([(x0, y0), (x0 + tw, y0), (x0 + tw, y1), (x0, y1)], "其它", xform=False)
    # 表头分隔线
    line((x0, y1 - rh), (x0 + tw, y1 - rh), "其它", xform=False)
    xs = [x0]
    for _t, w in cols:
        xs.append(xs[-1] + w)
    for x in xs[1:-1]:
        line((x, y0), (x, y1), "其它", xform=False)

    for j, (t, _w) in enumerate(cols):
        text(t, (xs[j] + 180, y1 - rh + 250), h=330, layer="其它", xform=False)
    for i, r in enumerate(rows):
        yy = y1 - rh * (i + 2) + 250
        for j, v in enumerate(r):
            text(v, (xs[j] + 180, yy), h=330, layer="其它", xform=False)
    print("    %d 层 × %d 列" % (len(rows), len(cols)))


def draw_notes_and_frame():
    print("[6] 图框 / 图签 / 设计说明")
    # 图框
    poly([(MARGIN, MARGIN), (SHEET_W - MARGIN, MARGIN),
          (SHEET_W - MARGIN, SHEET_H - MARGIN), (MARGIN, SHEET_H - MARGIN)],
         "图框", xform=False)

    # ---- 图签栏 ----
    x0, y0 = TB_X, TB_Y
    x1, y1 = TB_X + TB_W, TB_Y + TB_H
    poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "图框", xform=False)
    for i in range(1, 5):
        yy = y0 + TB_H * i / 5.0
        line((x0, yy), (x1, yy), "图框", xform=False)
        line((x0 + TB_W * 0.62, yy), (x1, yy), "图框", xform=False)
    line((x0 + TB_W * 0.62, y0), (x0 + TB_W * 0.62, y0 + TB_H * 4 / 5.0),
         "图框", xform=False)

    rows = [
        ("设计单位", "（此处填设计单位）"),
        ("工程名称", "%s基坑支护工程" % P["名称"]),
        ("图名", P["图名"]),
        ("设计号 / 图号", "%s / %s" % (P["设计号"], P["图号"])),
        ("日期", P["日期"]),
    ]
    for i, (k, v) in enumerate(rows):
        yy = y0 + TB_H * (4 - i) / 5.0 + TB_H / 10.0 - 180
        text(k, (x0 + 400, yy), h=300, layer="图框", xform=False)
        text(v, (x0 + TB_W * 0.63 + 400, yy), h=300, layer="图框", xform=False)

    sig = ["设计", "制图", "校核", "审核", "审定"]
    for i, s in enumerate(sig):
        xx = x0 + 400 + i * 1150
        text(s, (xx, y0 + TB_H / 10.0 - 180), h=300, layer="图框", xform=False)
        line((xx - 200, y0 + TB_H / 10.0 - 600), (xx + 900, y0 + TB_H / 10.0 - 600),
             "图框", xform=False)

    # ---- 图名（剖面正下方）----
    text(P["图名"], (MARGIN + 2000, Y_SOIL_BOT + OY - 2600), h=900, layer="图名",
         xform=False)
    text("比例 %s" % P["比例"], (MARGIN + 2000, Y_SOIL_BOT + OY - 3900),
         h=560, layer="图名", xform=False)

    # ---- 设计说明（图名下方，与图签同一水平带）----
    nx, ny = MARGIN + 2000, Y_SOIL_BOT + OY - 5600
    notes = [
        "设计说明：",
        "1 图中标高以米（m）为单位，其他尺寸均以毫米（mm）为单位；",
        "2 本工程采用相对标高，±0.000=%.3fm；" % P["正负零标高"],
        "3 基坑等级为%s，支护结构类型为%s，砼标号%s；"
        % (P["基坑等级"], P["支护类型"], P["砼标号"]),
        "4 支护桩桩间土支护采用挂钢筋网并喷射砼C20，厚度80mm；",
        "5 基坑周边应设围挡，坡顶3.5m范围内不得堆载；",
        "6 施工前应完成降水，基坑内设排水沟与集水井，及时抽排；",
        "7 开挖应分层分段进行，严禁超挖，开挖至基底后及时浇筑垫层；",
        "8 未尽事宜按相应规范执行。",
    ]
    for i, s in enumerate(notes):
        text(s, (nx, ny - i * 700), h=340, layer="设计说明", xform=False)


def main():
    name = next((a for a in sys.argv[1:] if not a.startswith("-")), "CD段")
    if name not in CASES:
        print("未知工点 %r，可选：%s" % (name, "、".join(CASES)))
        return 2
    load_case(name)

    if "--new" in sys.argv:
        print("[0] 新建图纸")
        call({"cmd": "new"})

    print("=== 生成 %s ===" % P["图名"])
    setup_layers()
    draw_soils()
    draw_structure()
    draw_load()
    draw_dims()
    draw_notes_and_frame()
    draw_soil_table()

    # 缩放到图框
    call({"cmd": "zoom", "mode": "center",
          "center": [SHEET_W / 2, SHEET_H / 2, 0.0], "height": SHEET_H * 1.12})

    print("\n完成。实体总数 %s；失败项：%s"
          % (cad.send({"cmd": "count"}).get("count"), FAILED if FAILED else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
