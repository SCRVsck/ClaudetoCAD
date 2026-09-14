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

import glob
import math
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402
from cadkit import calcbook, standard  # noqa: E402

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
# 相邻两张图的水平间距 —— 实测演示图里 11 个图框排在 -1000, 51000, 103000…
SHEET_PITCH = 52000.0
SHEET_DX = 0.0              # 当前这张图的水平偏移（批量出图时逐张累加）

# 图签栏各格子的落字位置，**直接量自演示图**（图框在 (-1000,-11000) 时）。
# 图框块没有属性，格子是空的，填值只能按坐标放文字。
TITLE_CELLS = {
    "项目名称": ((17240.0, -19850.0), 600.0),
    "图名":     ((17030.0, -21650.0), 600.0),
    "专业":     ((20658.0, -22750.0), 400.0),
    "图号":     ((20325.0, -23550.0), 300.0),
    "设计阶段": ((17268.0, -24300.0), 400.0),
    "版本号":   ((20578.0, -24350.0), 400.0),
    "出图日期": ((17075.0, -25100.0), 300.0),
}

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
def use_params(p):
    """把一组参数摊成本模块的全局量 —— 绘图函数都直接读这些名字。

    参数可以来自 CASES（手写），也可以来自 cadkit.calcbook（解析计算书），
    两者结构一致，所以下游完全不用区分。
    """
    global P, SHEET_DX
    P = p
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


def load_case(name):
    use_params(CASES[name])


# 目前只有桩锚/悬臂这一种类型的绘图程序，其余的要按需补
SUPPORTED_TYPES = {"pile": "桩锚/悬臂桩"}


def draw_one(p, warn=()):
    """画一张完整的图。返回 True 表示成功。"""
    stype = p.get("类型", "pile")
    if stype not in SUPPORTED_TYPES:
        print("  跳过：支护类型 %r（%s）还没有绘图程序"
              % (p.get("支护类型", stype), stype))
        print("        目前已实现：%s" % "、".join(SUPPORTED_TYPES.values()))
        return False

    print("=== %s ===" % (p.get("图名") or p.get("名称")))
    for w in warn:
        print("   警告：%s" % w)
    use_params(p)

    setup_sheet()
    draw_soils()
    draw_structure()
    draw_load()
    draw_dims()
    draw_notes_and_title()
    fill_titleblock()
    return True


def _opt(args, key):
    if key in args:
        i = args.index(key)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def main():
    args = sys.argv[1:]
    rtf = _opt(args, "--rtf")
    folder = _opt(args, "--dir")
    named = [a for a in args if not a.startswith("-")
             and a not in (rtf, folder)]

    # ---- 准备图纸 ----
    name = named[0] if named else "CD段"
    if not (rtf or folder) and name not in CASES:
        print("未知工点 %r，可选：%s" % (name, "、".join(CASES)))
        return 2
    if rtf or folder:
        load_case("CD段")          # 先用一套占位参数，仅为了拿到图名去命名文件
        label = ("批量出图" if folder else os.path.splitext(
            os.path.basename(rtf))[0])
        prepare_from_template_named(label)
    else:
        load_case(name)
        if "--template" in args or "--new" in args:
            prepare_from_template(name)

    # ---- 出图 ----
    ok = True
    if folder:
        files = sorted(glob.glob(os.path.join(folder, "*.rtf")))
        if not files:
            print("目录里没有 .rtf：%s" % folder)
            return 2
        print("批量出图：%d 份计算书\n" % len(files))
        for i, f in enumerate(files):
            globals()["SHEET_DX"] = i * SHEET_PITCH
            try:
                p, warn = calcbook.parse(f)
            except Exception as e:
                print("[%d] %s 解析失败：%s" % (i + 1, os.path.basename(f), e))
                ok = False
                continue
            p["图号"] = p.get("图号") or "JS-%02d-1" % (i + 1)
            ok = draw_one(p, warn) and ok
            print()
    elif rtf:
        try:
            p, warn = calcbook.parse(rtf)
        except Exception as e:
            print("解析失败：%s" % e)
            return 1
        globals()["SHEET_DX"] = 0.0
        ok = draw_one(p, warn)
    else:
        globals()["SHEET_DX"] = 0.0
        ok = draw_one(CASES[name])

    # 缩放到所有图框
    n = max(1, len(glob.glob(os.path.join(folder, "*.rtf"))) if folder else 1)
    x0, y0, x1, y1 = FRAME_BOX
    call({"cmd": "zoom", "mode": "center",
          "center": [x0 + (x1 - x0) / 2 + (n - 1) * SHEET_PITCH / 2,
                     (y0 + y1) / 2, 0.0],
          "height": (y1 - y0) * 1.1 if n == 1 else (x1 - x0 + (n - 1) * SHEET_PITCH) * 0.6})

    print("\n完成。实体总数 %s；失败项：%s"
          % (cad.send({"cmd": "count"}).get("count"), FAILED if FAILED else "无"))
    return 0 if ok else 1


def Y(elev_m):
    """标高(m) -> 图面 y（mm，坡顶为 0，向下为负）。"""
    return (elev_m - P["坡顶标高"]) * 1000.0


def YX(x, y):
    """剖面坐标 -> 图纸坐标（含当前张的水平偏移）。"""
    return x + OX + SHEET_DX, y + OY


def FX(x):
    """图纸绝对坐标 -> 当前张（图框/图签/说明用的是绝对坐标）。"""
    return x + SHEET_DX


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
              "point": [FRAME_INSERT[0] + SHEET_DX, FRAME_INSERT[1], 0.0],
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
    x0 = FX(FRAME_BOX[0] + 2500)
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


def fill_titleblock():
    """把工程信息填进图签栏各格。

    图框块没有属性（格子里是空的），值只能在模型空间按坐标放文字 ——
    位置是**从演示图里量出来的**，照着原图的落字点走，版式才一致。
    """
    vals = {
        "项目名称": "%s基坑支护工程" % P.get("名称", ""),
        "图名": P.get("图名") or "%s支护结构剖面图" % P.get("名称", ""),
        "专业": "基坑",
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
        text(v, (FX(at[0]), at[1]), h=h, layer="图框", xform=False)
        filled.append(key)
    print("[7] 图签栏填格：%s" % "、".join(filled))


def prepare_from_template_named(label):
    """从演示图复制一份干净模板并打开。

    演示图里带着这套标准的**图框块、23 个图层、5 个文字样式、2 个标注样式** ——
    这些才是「标准」的载体，从零画一个图框永远只是「像」。
    复制过来、清空模型空间（块表/样式表不受影响），再在里面画新图。
    """
    import shutil
    src = os.path.join(BASE, "eg", "演示.dwg")
    outdir = os.path.join(BASE, "out")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "%s.dwg" % label)
    if not os.path.exists(src):
        print("找不到模板 %s —— 请把演示图放在 eg/ 下" % src)
        return None
    call({"cmd": "closedocs"}, quiet=True)          # 释放文件占用，否则复制会失败
    time.sleep(1.0)
    shutil.copy2(src, dst)
    r = call({"cmd": "open", "path": dst})
    e = call({"cmd": "erase_all"})
    print("[0] 模板 %s：打开 %s 图元 → 清空后 %s\n"
          % (os.path.basename(src), r.get("entities"), e.get("after")))
    return dst


if __name__ == "__main__":
    sys.exit(main())
