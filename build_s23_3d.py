#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
三星 Galaxy S23 Ultra —— 真三维实体模型（ACIS 实体）
==================================================
全部通过 cad.py 桥接的 3D 指令建模：闭合轮廓 → 面域 → 拉伸 → 布尔运算。

坐标约定（AutoCAD 默认 Z 轴朝上，三维视图里手机才是立着的）：
    x : 0..78.1 —— 世界里 +X；屏幕朝 +Y，所以「正面视角的右方」= -X
    y : 0..8.9  —— y=0 背面，y=8.9 正面/屏幕
    z : 0..163.4
整体平移到 (BX, 0, 0)，与已有的二维立体图错开。

注意左右：二维图里 x 是从正面看从左往右量；三维里屏幕朝 +Y，人站在 +Y 往 -Y 看时
右手边是 -X，所以零件横坐标要按  fx(x) = W - x  换算，否则整机左右镜像。

拉伸永远沿 +Z，所以立起来的零件要靠旋转摆正：
    绕 X 轴 -90°：(x,y,z) -> (x, z, -y)   把「XZ 平面轮廓」立成竖直件
    绕 Y 轴 +90°：(x,y,z) -> (z, y, -x)   把轮廓转到 YZ 平面（侧键）
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402

W, H, D = 78.1, 163.4, 8.9
R = 8.5
BX, BY, BZ = 520.0, 0.0, 0.0

FAILED = []


# --------------------------------------------------------------------------
# 桥接封装
# --------------------------------------------------------------------------
def call(req):
    r = cad.send(req)
    if not r.get("ok"):
        FAILED.append((req.get("cmd"), r.get("error")))
        print("  !! %s 失败: %s" % (req.get("cmd"), str(r.get("error"))[:130]))
    return r


def rrect(x0, y0, x1, y1, r, seg=18):
    pts = []
    for cx, cy, a0, a1 in ((x1 - r, y0 + r, -90, 0), (x1 - r, y1 - r, 0, 90),
                           (x0 + r, y1 - r, 90, 180), (x0 + r, y0 + r, 180, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    pts.append(pts[0])
    return pts


def prism(pts, h):
    """XY 平面闭合轮廓 → 沿 +Z 拉伸 h → 实体 handle（源曲线自动清掉）"""
    p = call({"cmd": "add_polyline", "points": pts, "closed": True})
    reg = call({"cmd": "add_region", "handles": [p["handle"]]})
    call({"cmd": "erase", "handles": [p["handle"]]})
    rh = reg["handles"][0]
    s = call({"cmd": "extrude", "region": rh, "height": h})
    call({"cmd": "erase", "handles": [rh]})
    return s["handle"]


def plate(x0, x1, z0, z1, r, thick, y_face):
    """立在 XZ 平面的圆角薄板：x∈[x0,x1]、z∈[z0,z1]、y∈[y_face-thick, y_face]"""
    s = prism(rrect(x0, z0, x1, z1, r, 18), thick)
    call({"cmd": "rotate3d", "handle": s, "p1": [0, 0, 0], "p2": [1, 0, 0],
          "angle": -math.pi / 2})
    call({"cmd": "move", "handle": s, "from": [0, 0, 0],
          "to": [BX, BY + y_face - thick, BZ + z0 + z1]})
    return s


def disc(cx, cz, y0, y1, r):
    """轴向沿 Y 的圆柱（镜圈、闪光灯、开孔都用它）"""
    s = call({"cmd": "add_cylinder", "center": [0.0, 0.0, 0.0],
              "radius": r, "height": y1 - y0})["handle"]
    call({"cmd": "rotate3d", "handle": s, "p1": [0, 0, 0], "p2": [1, 0, 0],
          "angle": -math.pi / 2})
    call({"cmd": "move", "handle": s, "from": [0, 0, 0],
          "to": [BX + cx, BY + y0, BZ + cz]})
    return s


def slot(x0, width, y_lo, y_hi, r, depth, cut):
    """底边开孔。轮廓直接在 XY 平面（x=孔宽，y=孔的厚度方向尺寸），沿 Z 掏出 depth，
    再沿 Z 下移，使刀具从 z<0 穿到机身内部 cut 深。"""
    s = prism(rrect(x0, y_lo, x0 + width, y_hi, r, 8), depth)   # z∈[0,depth]
    call({"cmd": "move", "handle": s, "from": [0, 0, 0],
          "to": [BX, BY, BZ + cut - depth]})                    # z∈[cut-depth, cut]
    return s


def setcolor(h, c):
    call({"cmd": "setprop", "handle": h, "color": c})


# --------------------------------------------------------------------------
# 建模
# --------------------------------------------------------------------------
def build():
    print("[1] 机身：圆角矩形轮廓拉伸 8.9mm")
    body = plate(0, W, 0, H, R, D, D)

    print("[2] 屏幕：先铣 0.5mm 凹槽，再嵌一块面板")
    scr = (1.6, W - 1.6, 1.3, H - 1.3, 6.0)
    cut = plate(*scr, 1.2, 9.6)
    call({"cmd": "boolean", "op": "subtract", "target": body, "tools": [cut]})
    pane = plate(*scr, 0.5, 8.75)
    setcolor(pane, 250)

    print("[3] 居中打孔前摄")
    setcolor(disc(W / 2, H - 5.5, 8.70, 8.82, 2.2), 253)

    print("[4] 后置四摄：镜圈 + 镜片 + 高光")
    # 二维背视图里镜头列在画面左侧 u'=12.5；背视图 u' = W - (正面视角 x)，
    # 折回正面视角 x = 65.6，再按 fx() 换成世界坐标 = 12.5
    cx = 12.5
    for k in range(4):
        cz = H - 13.5 - k * 21.5
        ring = disc(cx, cz, -1.9, 0.0, 9.5)
        call({"cmd": "boolean", "op": "subtract", "target": ring,
              "tools": [disc(cx, cz, -1.9, 0.0, 8.0)]})
        setcolor(ring, 8)
        setcolor(disc(cx, cz, -0.55, 0.0, 8.1), 250)
        setcolor(disc(cx, cz, -0.42, -0.30, 2.8), 253)

    print("[5] 闪光灯 / 激光对焦")
    flx, flz = 31.5, H - 15.9
    setcolor(plate(flx - 4.2, flx + 4.2, flz - 3.4, flz + 3.4, 1.2, 0.7, 0.0), 8)
    for dx in (-1.9, 1.9):
        setcolor(disc(flx + dx, flz, -1.0, -0.72, 1.7), 2)
    setcolor(disc(flx, flz - 12.0, -0.7, 0.0, 2.4), 250)

    print("[6] 右侧音量键 / 电源键（正面视角的右侧 = 世界 x=0 那面）")
    for z0, z1 in ((112.0, 134.0), (99.0, 110.0)):
        ln = z1 - z0
        s = prism(rrect(0, 0, ln, 7.9, 1.2, 8), 0.9)
        call({"cmd": "rotate3d", "handle": s, "p1": [0, 0, 0], "p2": [0, 1, 0],
              "angle": math.pi / 2})
        call({"cmd": "move", "handle": s, "from": [0, 0, 0],
              "to": [BX - 0.9, BY + 0.5, BZ + z0 + ln]})
        setcolor(s, 8)

    print("[7] 底边开孔：Type-C / 扬声器 / S Pen")
    cuts = [slot(34.8, 8.5, 3.15, 5.75, 1.2, 5.0, 2.5),
            slot(20.6, 10.0, 3.65, 5.25, 0.8, 3.0, 1.5),
            slot(62.6, 5.0, 3.80, 5.10, 0.6, 2.6, 1.3)]
    call({"cmd": "boolean", "op": "subtract", "target": body, "tools": cuts})

    # 注意：布尔运算会把目标实体的颜色重置回 ByLayer(256)，
    # 所以机身的颜色必须等所有布尔做完之后再设。
    setcolor(body, 254)

    return body


def setup_view():
    print("[8] 三维视图 + 着色")
    # 视点在 -X/+Y/+Z：能看到屏幕（+Y）、按键那一侧（世界 x=0 面）和顶面。
    # 想看背面四摄就把 dir 换成 [-1, -1, 1]。
    call({"cmd": "view3d", "dir": [-1.0, 1.0, 1.0]})
    call({"cmd": "zoom", "mode": "center",
          "center": [BX + W / 2, BY + D / 2, BZ + H / 2], "height": 270.0})
    # VSCURRENT 的选项要用「本地关键字缩写」，不能写中文全称、也不能加下划线
    # （下划线只做命令名翻译，选项缩写不翻译）。写错会停在命令行等输入，
    # 把 AutoCAD 卡成忙态（COM 全部被 RPC_E_CALL_REJECTED 顶回）。
    #   C=概念（冷暧定向光，好看但会给背光面染蓝）  S=着色（按实体本色平滑着色）
    call({"cmd": "visualstyle", "name": "S"})


def main():
    build()
    print("实体总数：", cad.send({"cmd": "count"}).get("count"))
    setup_view()
    print("失败项：", FAILED if FAILED else "无")


if __name__ == "__main__":
    main()
