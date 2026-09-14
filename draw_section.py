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
import time

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

# ===================================================== 图纸（用标准图框块）
# 不再自己画图框 —— 直接插标准图框块 CSSDI-A3，与演示图**同一插入点、同一比例**。
# 它内部嵌着 设计所图框A3（420×297 的纸面尺寸，按 100 倍放大）：
#     CSSDI-A3 @ (-1000,-11000) scale 1
#       └ 设计所图框A3 @ (-18750,-14850) scale 100
# 于是图纸 1 的图框落在  x -19750..22250, y -25850..3850（42000×29700）
# 这与演示图里文字的实际位置完全吻合（院名 x≈15547、土层标注 x≈-14200）。
FRAME_INSERT = [-1000.0, -11000.0]
FRAME_BOX = (-19750.0, -25850.0, 22250.0, 3850.0)     # x0,y0,x1,y1
SIGN_COL_X = 14944.0        # 图签栏左边界（图框内右侧那一栏）

# 文字：标准图里 566 个文字**全部**用 PM-TEXT，字高以 400 为主。
# 但它的原字体是 Tssdeng.shx（探索者 TSSD 字体，路径指向 AutoCAD 2012），
# 本机没有这个文件 —— 缺字体时 AutoCAD **什么都不画**（不是显示成 ?，是彻底空白），
# 极难排查。所以先试原字体，装了就照用，没装才换成同类的国标 SHX 组合。
TEXT_STYLE = "PM-TEXT"
STD_FONT, STD_BIGFONT = "tssdeng.shx", "gbcbig.shx"
ALT_FONT, ALT_BIGFONT = "gbenor.shx", "gbcbig.shx"
TXT = 400.0
DIMTXT = 350.0
TITLE_H = 600.0

# 剖面在图纸中的落位（让剖面落在图签栏左侧的绘图区里）
OX, OY = -2250.0, 600.0

# 剖面自身范围（相对坡顶原点）
X_LEFT = -15000.0
X_RIGHT = 8000.0
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
    return call({"cmd": "add_polyline", "closed": closed, "layer": layer,
                 "points": [[x, y, 0.0] for x, y in pts]}).get("handle")


def line(p1, p2, layer, xform=True):
    if xform:
        p1, p2 = YX(*p1), YX(*p2)
    return call({"cmd": "add_line", "layer": layer,
                 "start": [p1[0], p1[1], 0.0],
                 "end": [p2[0], p2[1], 0.0]}).get("handle")


def text(s, at, h=TXT, layer="注释", xform=True):
    if xform:
        at = YX(*at)
    return call({"cmd": "add_text", "text": s, "layer": layer,
                 "insert": [at[0], at[1], 0.0], "height": h}).get("handle")


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


# ------------------------------------------------------- 图纸准备
def ensure_layers():
    """补齐标准表里有、但模板里缺的图层。

    模板是演示图，图层未必齐全 —— 比如「桩间挂网」在演示图里就被清理掉了。
    给实体设一个不存在的图层会报「未找到主键」，而且**报错点在建图元那一步**，
    很容易误以为是几何数据有问题。
    已有的图层一律不动（保留模板里的颜色/线型设置），只建缺的。
    """
    t = cad.send({"cmd": "tables"})
    have = {L["name"] for L in t.get("layers", [])}
    made = []
    for name, (lt, color) in standard.LAYERS.items():
        if name not in have:
            call({"cmd": "layer", "name": name, "color": color,
                  "linetype": lt}, quiet=True)
            made.append(name)
    if made:
        print("    补建缺失图层：%s" % "、".join(made))
    else:
        print("    模板图层齐全（%d 个标准图层都在）" % len(standard.LAYERS))


def setup_sheet():
    """插标准图框、补图层、切标准文字样式。

    刻意**不重建已有图层**：模板里是演示图那 23 个标准图层（含 签名、
    PUB_TITLE、PUB_DIM 这些 VB 里没有的），重建反而会把人家配好的
    颜色/线型改掉。
    """
    print("[1] 标准图框 / 图层 / 文字样式")
    ensure_layers()

    r = call({"cmd": "insert", "name": "CSSDI-A3", "layer": "图框",
              "point": [FRAME_INSERT[0], FRAME_INSERT[1], 0.0],
              "xscale": 1.0, "yscale": 1.0, "zscale": 1.0})
    print("    图框句柄 %s" % r.get("handle"))

    # 先按标准原样设字体；本机没有 Tssdeng.shx 时才换替代品
    base = {"cmd": "textstyle", "name": TEXT_STYLE, "width": 0.7, "height": 0.0}
    r = call({**base, "font": STD_FONT, "bigfont": STD_BIGFONT},
             quiet=True, record=False)
    if r.get("ok"):
        used = "%s + %s（标准原字体）" % (STD_FONT, STD_BIGFONT)
    else:
        r2 = call({**base, "font": ALT_FONT, "bigfont": ALT_BIGFONT}, quiet=True)
        used = ("%s + %s（替代；本机缺 %s）" % (ALT_FONT, ALT_BIGFONT, STD_FONT)
                if r2.get("ok") else "SimHei")
        if not r2.get("ok"):
            call({**base, "font": "SimHei"}, quiet=True)
    call({"cmd": "activestyle", "name": TEXT_STYLE}, quiet=True)
    print("    文字样式 %s：%s，字高 %g" % (TEXT_STYLE, used, TXT))


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


def draw_notes_and_title():
    """图名 + 设计说明。

    图框和图签栏**不在这里画** —— 那是标准块 CSSDI-A3 的职责，
    自己画一套就又不是标准了。
    """
    print("[6] 图名 / 设计说明")
    x0 = FRAME_BOX[0] + 2500
    y_base = Y_SOIL_BOT + OY

    text(P["图名"], (x0, y_base - 1400), h=TITLE_H, layer="图名", xform=False)
    text("  比例 %s" % P["比例"], (x0, y_base - 2500), h=TXT, layer="图名",
         xform=False)

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
    # 两栏排布 —— 图框下方只有约 6m 高的余地，单栏放不下 9 行
    ny = y_base - 3600
    half = (len(notes) + 1) // 2
    for i, s in enumerate(notes):
        col, row = (0, i) if i < half else (1, i - half)
        text(s, (x0 + col * 17500, ny - row * 620), h=TXT,
             layer="设计说明", xform=False)


def prepare_from_template(case_name):
    """从演示图复制一份干净模板并打开。

    演示图里带着这套标准的**图框块、23 个图层、5 个文字样式、2 个标注样式** ——
    这些才是「标准」的载体，从零画一个图框永远只是「像」。
    复制过来、清空模型空间（块表/样式表不受影响），再在里面画新图。
    """
    import shutil
    src = os.path.join(BASE, "eg", "演示.dwg")
    outdir = os.path.join(BASE, "out")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "%s.dwg" % CASES[case_name]["图名"])
    if not os.path.exists(src):
        print("找不到模板 %s —— 请把演示图放在 eg/ 下" % src)
        return None
    call({"cmd": "closedocs"}, quiet=True)          # 释放文件占用，否则复制会失败
    time.sleep(1.0)
    shutil.copy2(src, dst)
    r = call({"cmd": "open", "path": dst})
    e = call({"cmd": "erase_all"})
    print("[0] 模板 %s：打开 %s 图元 → 清空后 %s"
          % (os.path.basename(src), r.get("entities"), e.get("after")))
    return dst


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    name = args[0] if args else "CD段"
    if name not in CASES:
        print("未知工点 %r，可选：%s" % (name, "、".join(CASES)))
        return 2
    load_case(name)

    print("=== 生成 %s ===" % P["图名"])
    if "--template" in sys.argv or "--new" in sys.argv:
        prepare_from_template(name)

    setup_sheet()
    draw_soils()
    draw_structure()
    draw_load()
    draw_dims()
    draw_notes_and_title()

    # 缩放到图框
    x0, y0, x1, y1 = FRAME_BOX
    call({"cmd": "zoom", "mode": "center",
          "center": [(x0 + x1) / 2, (y0 + y1) / 2, 0.0],
          "height": (y1 - y0) * 1.12})

    print("\n完成。实体总数 %s；失败项：%s"
          % (cad.send({"cmd": "count"}).get("count"), FAILED if FAILED else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
