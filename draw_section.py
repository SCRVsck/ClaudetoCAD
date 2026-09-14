#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按工程图标准生成「基坑支护结构剖面图」。

    python draw_section.py            # 用内置的 AB 段参数
    python draw_section.py --fresh    # 先清空当前图形再画

参数取自 eg/桩悬臂.rtf（天汉基坑设计软件输出的 AB 段「桩撑/锚结构」），
图层与土层填充约定取自 eg/Drawing Module.vb，见 cadkit/standard.py。

坐标约定与那套图纸一致：
    y = 0 是坡顶地面线，标高向下为负；单位 mm。
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402
from cadkit import standard  # noqa: E402

# --------------------------------------------------------------- 输入参数
# 全部来自 桩悬臂.rtf 的「AB段」各表
P = {
    "正负零标高": 23.000,      # AB段_1 结构正负零标高
    "坡顶标高": 22.000,        # 计算坡顶标高
    "基底标高": 17.000,        # = -6.000(相对±0.000)
    "桩顶标高": 20.500,        # 桩顶 -2.500m(20.5m)
    "桩长": 12.0,              # AB段_2.5 桩长
    "桩径": 800.0,             # 桩身截面 圆形 直径=800mm
    "桩间距": 1200.0,          # 桩排水平间距
    "冠梁高": 600.0,           # AB段_2.6 冠梁高 0.6m
    "冠梁外扩": 100.0,         # 内侧/外侧外扩宽度 0.1m
    "放坡总高": 1500.0,        # AB段_2.4 坡高 1.5m
    "放坡坡宽": 1500.0,        # 坡宽 1.5m，宽高比 1
    "放坡平台宽": 1000.0,      # 平台宽 1m
    # AB段_2.1 土层：编号、名称、层底埋深(m)、C(kPa)、φ(°)
    "土层": [
        ("①", "杂填土",     1.5,   8, 10),
        ("②", "淤泥质粘土",  3.0,  10,  6),
        ("③", "粉质粘土",   10.0,  20, 10),
        ("④", "粘土",      15.0,  30, 15),
        ("⑤", "石灰岩",    20.0, 150, 15),
    ],
    # AB段_2.3 先期荷载：作用深度 0、起点距 5m、宽 7m、30kPa
    "荷载": {"起点距": 5000.0, "宽": 7000.0, "值": "30kPa"},
    "图名": "AB段支护结构剖面图",
    "比例": "1:100",
}

# 图面范围（mm）
X_LEFT = -22000.0      # 土层剖面左边界
X_RIGHT = 12000.0      # 基坑右边界
FAR = -26000.0         # 绘图原点偏移，避开之前的测试内容
TXT = 600.0            # 土层标注字高
DIMTXT = 500.0         # 尺寸文字高度

FAILED = []


# ------------------------------------------------------------------ 桥接
def call(req, quiet=False, record=True):
    r = cad.send(req)
    if not r.get("ok"):
        if record:
            FAILED.append((req.get("cmd"), r.get("error")))
        if not quiet:
            print("   !! %s 失败: %s" % (req.get("cmd"), str(r.get("error"))[:150]))
    return r


def Y(elev_m):
    """把「标高(m)」换算成图面 y（mm，坡顶为 0，向下为负）。"""
    return (elev_m - P["坡顶标高"]) * 1000.0


# 关键标高换算成图面坐标
Y_TOP = 0.0                              # 坡顶地面线
Y_PILE_TOP = Y(P["桩顶标高"])            # 桩顶（冠梁顶面）
Y_BEAM_BOT = Y_TOP - P["放坡总高"]        # 冠梁底面 = 坡顶下 1.5m
Y_BOT = Y(P["基底标高"])                 # 基底
Y_PILE_BOT = Y_BEAM_BOT - P["桩长"] * 1000.0
# 最深一层土的底 —— 图名/说明要放在它下面，否则会压在土层上
Y_SOIL_BOT = -P["土层"][-1][2] * 1000.0

# 开挖轮廓关键 x
X_SLOPE_END = P["放坡坡宽"]                          # 放坡到底的 x
X_PLAT_END = X_SLOPE_END + P["放坡平台宽"]           # 平台外侧 = 开挖竖壁
X_PILE_FACE = X_PLAT_END                             # 桩前面（临坑侧）贴着竖壁
X_PILE_BACK = X_PILE_FACE - P["桩径"]                # 桩背面
X_BEAM_HALF = (P["桩径"] + 2 * P["冠梁外扩"]) / 2.0  # 冠梁半宽 = 1000/2


def exc_x_at(y):
    """开挖轮廓在某个 y 处的 x（基底以上用轮廓，以下用基坑右边界）。

    注意 y = -放坡总高 处轮廓是**多值**的：坡底在 1500，平台外沿在 2500。
    这里统一返回外沿（2500），因为往下走土层是延伸到坑壁的；
    需要坡底那个值时由调用方显式用 X_SLOPE_END。
    """
    if y <= Y_BOT:
        return X_RIGHT
    if y >= Y_TOP:
        return 0.0
    if y > -P["放坡总高"]:
        return -y          # 1:1 放坡段
    return X_PLAT_END


# ------------------------------------------------------------ 图层与线型
def setup_layers():
    print("[1] 建图层 / 载线型 / 文字样式（按标准表）")
    # 中文必须先建 TrueType 样式：默认 Standard 是 SHX 字体，中文一律显示成 ?
    call({"cmd": "textstyle", "name": "工程图", "font": "SimHei"}, quiet=True)
    for lt in standard.LINETYPES:
        call({"cmd": "linetype", "name": lt, "file": "acad.lin"}, quiet=True)
    for name, (lt, color) in standard.LAYERS.items():
        call({"cmd": "layer", "name": name, "color": color, "linetype": lt},
             quiet=True)
    print("    图层 %d 个，线型 %s" % (len(standard.LAYERS),
                                      "/".join(standard.LINETYPES)))


def poly(pts, layer):
    r = call({"cmd": "add_polyline", "points": [[x, y, 0.0] for x, y in pts],
              "closed": True})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


def line(p1, p2, layer):
    r = call({"cmd": "add_line", "start": [p1[0], p1[1], 0.0],
              "end": [p2[0], p2[1], 0.0]})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


def text(s, at, h=TXT, layer="注释"):
    r = call({"cmd": "add_text", "text": s, "insert": [at[0], at[1], 0.0],
              "height": h})
    if r.get("ok") and layer:
        call({"cmd": "setprop", "handle": r["handle"], "layer": layer}, quiet=True)
    return r.get("handle")


# ---------------------------------------------------------------- 土层
def layer_polygon_pts(y_top, y_bot):
    """某土层在图面上的多边形。

    思路是「从左上角出发，沿开挖轮廓往下走，再回到左下角」。轮廓有三级：
    放坡段（1:1）→ 平台 → 坑壁竖段；坑底以下土层铺满宽度。

    早先的写法只用「落在区间内的转折点」拼点，结果顶边被直接从最左端
    斜拉到坡底 —— ① 层变成了三角形，坡面画成一条横贯全图的斜线。
    """
    if y_top <= Y_BOT:
        # 整层都在坑底以下：满宽矩形
        return [(X_LEFT, y_top), (X_RIGHT, y_top),
                (X_RIGHT, y_bot), (X_LEFT, y_bot)]

    pts = [(X_LEFT, y_top), (exc_x_at(y_top), y_top)]

    # 放坡底部的转折（只有真正跨过它时才需要）
    k = -P["放坡总高"]
    if y_bot < k < y_top:
        pts.append((X_SLOPE_END, k))
        pts.append((X_PLAT_END, k))

    if y_bot >= Y_BOT:
        # 底边正好落在放坡底时，土层只铺到坡脚，不覆盖平台（平台是挖掉的）
        if abs(y_bot + P["放坡总高"]) < 1e-6:
            pts.append((X_SLOPE_END, y_bot))
        else:
            pts.append((exc_x_at(y_bot), y_bot))
    else:
        # 穿过坑底：先沿坑壁下到基底，再横向铺到右边界，再往下
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
    print("[2] 土层：分带轮廓 + 图案填充")
    top = Y_TOP
    for i, (no, name, depth_m, c, phi) in enumerate(P["土层"], 1):
        bot = -depth_m * 1000.0
        pts = layer_polygon_pts(top, bot)
        h = poly(pts, "土层线")
        if not h:
            top = bot
            continue

        pat, color, scale, fallback = standard.soil_style(name)
        # 第一次失败不算错：多半是本机没装 CQ*.pat，属于预期内
        r = call({"cmd": "hatch", "boundary": h, "pattern": pat,
                  "scale": scale, "color": color, "layer": "土层线"},
                 quiet=True, record=False)
        if not r.get("ok"):
            r = call({"cmd": "hatch", "boundary": h, "pattern": "ANSI31",
                      "scale": standard.SOIL_PATTERN_SCALE_FALLBACK,
                      "color": color, "layer": "土层线"}, quiet=True)
            pat, fallback = "ANSI31", True

        # 左侧标注：土名 + C/φ
        text("%s %s" % (no, name), (X_LEFT + 900, (top + bot) / 2.0 + 500))
        text("C=%g kPa,φ=%g°" % (c, phi), (X_LEFT + 900, (top + bot) / 2.0 - 400))
        print("    %s %-8s %6.1fm  %s%s" %
              (no, name, depth_m, pat, "（兜底）" if fallback else ""))
        top = bot


# ------------------------------------------------------------ 支护结构
def draw_structure():
    print("[3] 开挖轮廓 / 冠梁 / 支护桩")

    # 地面线
    line((X_LEFT, Y_TOP), (0.0, Y_TOP), "土层线")
    line((0.0, Y_TOP), (X_SLOPE_END, -P["放坡总高"]), "边坡线")
    line((X_SLOPE_END, -P["放坡总高"]), (X_PLAT_END, -P["放坡总高"]), "边坡线")
    line((X_PLAT_END, -P["放坡总高"]), (X_PLAT_END, Y_BOT), "边坡线")
    line((X_PLAT_END, Y_BOT), (X_RIGHT, Y_BOT), "边坡线")

    # 冠梁 1000×600（冠梁图层，标准色 6）
    hb = poly([(X_PILE_FACE - X_BEAM_HALF, Y_PILE_TOP),
               (X_PILE_FACE - X_BEAM_HALF + 2 * X_BEAM_HALF, Y_PILE_TOP),
               (X_PILE_FACE - X_BEAM_HALF + 2 * X_BEAM_HALF, Y_PILE_TOP - P["冠梁高"]),
               (X_PILE_FACE - X_BEAM_HALF, Y_PILE_TOP - P["冠梁高"])], "冠梁")
    if hb:
        call({"cmd": "hatch", "boundary": hb, "pattern": "AR-CONC",
              "scale": 5.0, "color": 256, "layer": "冠梁"}, quiet=True)

    # 支护桩 Φ800：剖面里是一根竖条，桩顶从冠梁底起算
    hp = poly([(X_PILE_BACK, Y_BEAM_BOT),
               (X_PILE_FACE, Y_BEAM_BOT),
               (X_PILE_FACE, Y_PILE_BOT),
               (X_PILE_BACK, Y_PILE_BOT)], "支护桩")
    if hp:
        call({"cmd": "hatch", "boundary": hp, "pattern": "AR-CONC",
              "scale": 8.0, "color": 256, "layer": "支护桩"}, quiet=True)

    print("    冠梁 1000×600  支护桩 Φ%d L=%.1fm  桩顶 %.1fm" %
          (P["桩径"], P["桩长"], P["桩顶标高"]))


def draw_load():
    print("[4] 先期荷载（地面超载）")
    ld = P["荷载"]
    x0, x1 = ld["起点距"], ld["起点距"] + ld["宽"]
    line((x0, Y_TOP), (x1, Y_TOP), "其它")
    # 一排向下的箭头表示均布荷载
    n = 7
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        line((x, Y_TOP), (x, Y_TOP - 900), "其它")
        line((x, Y_TOP - 900), (x - 220, Y_TOP - 550), "其它")
        line((x, Y_TOP - 900), (x + 220, Y_TOP - 550), "其它")
    text("q=%s" % ld["值"], ((x0 + x1) / 2.0 - 700, Y_TOP + 700))


# ---------------------------------------------------------------- 标注
def draw_dims():
    print("[5] 尺寸标注（标准图层「尺寸标注」，色 3）")
    # 开挖深度：坡顶 -> 基底
    call({"cmd": "add_dim", "mode": "rotated",
          "p1": [X_PLAT_END, Y_TOP], "p2": [X_PLAT_END, Y_BOT],
          "loc": [X_RIGHT + 1500, (Y_TOP + Y_BOT) / 2], "angle": math.pi / 2,
          "color": 3, "text_height": DIMTXT})
    # 桩长：冠梁底 -> 桩底
    call({"cmd": "add_dim", "mode": "rotated",
          "p1": [X_PILE_FACE, Y_BEAM_BOT], "p2": [X_PILE_FACE, Y_PILE_BOT],
          "loc": [X_RIGHT + 4500, (Y_BEAM_BOT + Y_PILE_BOT) / 2],
          "angle": math.pi / 2, "color": 3, "text_height": DIMTXT})
    # 桩顶埋深：坡顶 -> 桩顶
    call({"cmd": "add_dim", "mode": "rotated",
          "p1": [X_PILE_FACE, Y_TOP], "p2": [X_PILE_FACE, Y_PILE_TOP],
          "loc": [X_RIGHT + 3000, (Y_TOP + Y_PILE_TOP) / 2],
          "angle": math.pi / 2, "color": 3, "text_height": DIMTXT})
    # 放坡宽度
    call({"cmd": "add_dim", "mode": "rotated",
          "p1": [0.0, Y_TOP], "p2": [X_PLAT_END, Y_TOP],
          "loc": [(0 + X_PLAT_END) / 2, Y_TOP + 2200], "angle": 0,
          "color": 3, "text_height": DIMTXT})


def draw_axis_and_title():
    print("[6] 剖面轴线 / 图名 / 构件引注")
    line((0.0, Y_TOP + 2500), (0.0, Y_PILE_BOT - 1500), "剖面图用轴线")

    # 图名放到**最深一层土**下面（不是桩底 —— 土层比桩长深，压在土上会糊）
    text(P["图名"], (X_LEFT + 500, Y_SOIL_BOT - 3500), h=1100, layer="图名")
    text("比例 %s" % P["比例"], (X_LEFT + 500, Y_SOIL_BOT - 5000),
         h=700, layer="图名")

    # 构件引注放在基坑内侧的空白处，不要压在土层的填充上
    ax = X_PLAT_END + 1200
    text("冠梁 1000×600", (ax, Y_BEAM_BOT - 1200))
    text("支护桩 Φ%d@%d，L=%.1fm" % (P["桩径"], P["桩间距"], P["桩长"]),
         (ax, Y_PILE_BOT + 2500))
    text("基底标高 %.3fm" % P["基底标高"], (ax, Y_BOT + 900))


def main():
    fresh = "--fresh" in sys.argv
    if fresh:
        print("[0] 清空当前图形")
        call({"cmd": "erase", "handles": [e["Handle"] for e in
              cad.send({"cmd": "entities", "limit": 20000}).get("entities", [])
              if e.get("Handle")]}, quiet=True)

    print("=== 按标准生成：%s ===" % P["图名"])
    setup_layers()
    draw_soils()
    draw_structure()
    draw_load()
    draw_dims()
    draw_axis_and_title()

    call({"cmd": "zoom", "mode": "center",
          "center": [(X_LEFT + X_RIGHT) / 2, (Y_TOP + Y_SOIL_BOT) / 2, 0.0],
          "height": (Y_TOP - Y_SOIL_BOT) * 1.35})

    n = cad.send({"cmd": "count"}).get("count")
    print("\n完成。实体总数 %s；失败项：%s" % (n, FAILED if FAILED else "无"))


if __name__ == "__main__":
    main()
