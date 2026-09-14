#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
三星 Galaxy S23 Ultra 立体图（斜轴测投影）
=========================================
通过 cad.py 桥接把图形画进 AutoCAD 模型空间。

投影方式：斜等测/斜二测（cavalier/oblique）——正面保持真实形状，
深度方向沿 45° 斜上方偏移。为便于观察，厚度方向放大 K 倍作图。

坐标：x 向右（宽），y 向上（高），z 由观察者向后（厚）。
屏幕坐标： u = x - O*z ,  v = y - O*z ,  O = K*sqrt(1/2)
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402

# --------------------------------------------------------------------------
# 一、尺寸参数（单位 mm，取自 S23 Ultra 官方规格）
# --------------------------------------------------------------------------
W, H, D = 78.1, 163.4, 8.9      # 宽 / 高 / 厚
R = 8.5                          # 机身圆角
K = 1.8                          # 深度方向放大系数（作图用）
O = K * math.sqrt(0.5)           # 每单位 z 的 45° 偏移量

OX_F, OX_B = 0.0, 160.0          # 正视图 / 背视图 的横向摆放位置

# 屏幕（6.8" 19.3:9 → 3088/1440）
SC_X0, SC_Y0 = 1.6, 1.3
SC_X1, SC_Y1 = W - 1.6, H - 1.3
SC_R = 6.0

# 后置摄像头：左侧一列 4 颗
LENS_R = 9.5                     # 镜圈外半径 ⌀19
LENS_PITCH = 21.5                # 镜心间距
LENS_CX = 12.5                   # 镜心横坐标（背视图局部坐标）
LENS_Y0 = H - 13.5               # 最上一颗镜心高度
BUMP = 1.9                       # 镜圈凸出高度

# --------------------------------------------------------------------------
# 二、实体收集
# --------------------------------------------------------------------------
ENTS = []


def line(a, b):
    ENTS.append({"cmd": "add_line", "start": [a[0], a[1], 0.0],
                 "end": [b[0], b[1], 0.0]})


def pl(pts, close=False):
    p = [[q[0], q[1]] for q in pts]
    if close and p[0] != p[-1]:
        p.append(p[0])
    ENTS.append({"cmd": "add_polyline", "points": p})


def ci(c, r):
    ENTS.append({"cmd": "add_circle", "center": [c[0], c[1], 0.0], "radius": r})


def tx(s, p, h):
    ENTS.append({"cmd": "add_text", "text": s, "insert": [p[0], p[1], 0.0],
                 "height": h})


def tick(p, s=1.3):
    line((p[0] - s, p[1] - s), (p[0] + s, p[1] + s))


# --------------------------------------------------------------------------
# 三、几何工具
# --------------------------------------------------------------------------
def rrect(x0, y0, x1, y1, r, seg=10):
    """圆角矩形点列（闭合，从右边下部起逆时针）"""
    pts = []
    for cx, cy, a0, a1 in ((x1 - r, y0 + r, -90, 0), (x1 - r, y1 - r, 0, 90),
                           (x0 + r, y1 - r, 90, 180), (x0 + r, y0 + r, 180, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle3(c, u, v, r, n=24):
    """任意平面上的圆 → 3D 点列"""
    out = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        ct, st = math.cos(t), math.sin(t)
        out.append((c[0] + r * ct * u[0] + r * st * v[0],
                    c[1] + r * ct * u[1] + r * st * v[1],
                    c[2] + r * ct * u[2] + r * st * v[2]))
    return out


def mkproj(ox, oy):
    """斜轴测投影：z 越大（越靠里）→ 屏幕坐标越偏右上，故可见正面 + 右侧面 + 顶面。"""
    def P(x, y, z):
        return (ox + x + O * z, oy + y + O * z)
    return P


# --------------------------------------------------------------------------
# 四、机身轮廓（正面 + 可见的右侧面 / 顶面）
# --------------------------------------------------------------------------
def body(P, seg=10):
    pts = rrect(0, 0, W, H, R, seg)
    pl([P(x, y, 0) for x, y in pts], close=True)          # 正面轮廓
    i0, i1 = seg, 2 * seg + 2                             # 右边缘 → 上边缘
    pl([P(pts[i][0], pts[i][1], D) for i in range(i0, i1 + 1)])   # 背面可见弧
    for i in (i0, i1):                                    # 两条转向棱线
        line(P(pts[i][0], pts[i][1], 0), P(pts[i][0], pts[i][1], D))


# --------------------------------------------------------------------------
# 五、正视图（屏幕面）
# --------------------------------------------------------------------------
def front_view():
    P = mkproj(OX_F, 0.0)
    body(P)

    # 屏幕
    pl([P(x, y, 0) for x, y in rrect(SC_X0, SC_Y0, SC_X1, SC_Y1, SC_R, 10)],
       close=True)

    # 居中打孔前摄
    u, v = P(W / 2, H - 5.5, 0)
    ci((u, v), 2.4)
    ci((u, v), 1.55)

    # 右侧按键（音量键在上、电源键在下）
    for ya, yb in ((112.0, 134.0), (99.0, 110.0)):
        p = 0.9
        face = rrect(ya, 0.0, yb, D, 0.5, 4)              # (y,z) 平面内圆角矩形
        pl([P(W + p, a, b) for a, b in face], close=True)
        for a, b in ((ya, 0.0), (yb, 0.0), (yb, D), (ya, D)):
            line(P(W + p, a, b), P(W, a, b))

    # 顶面麦克风孔（y = H 平面上的小圆 → 斜轴测下为椭圆）
    c3 = circle3((14.0, H, D / 2), (1, 0, 0), (0, 0, 1), 1.2, 20)
    pl([P(*q) for q in c3])

    # 左下角 S Pen 插槽缝
    pl([P(x, y, 0) for x, y in rrect(11.0, 0.4, 16.5, 2.6, 1.1, 4)], close=True)


# --------------------------------------------------------------------------
# 六、背视图（摄像头面）。注意：从背面看，镜头列在画面左侧
# --------------------------------------------------------------------------
def back_view():
    P = mkproj(OX_B, 0.0)
    body(P)

    for k in range(4):
        cy = LENS_Y0 - k * LENS_PITCH
        cx = LENS_CX
        u, v = P(cx, cy, 0)
        d = -O * BUMP                                  # 镜圈朝观察者凸出 → 反向偏移

        ci((u, v), LENS_R)                             # 镜圈根部
        ci((u + d, v + d), LENS_R)                     # 镜圈顶面外沿
        for ang in (135.0, -45.0):                     # 圆柱轮廓线
            a = math.radians(ang)
            p0 = (u + LENS_R * math.cos(a), v + LENS_R * math.sin(a))
            line(p0, (p0[0] + d, p0[1] + d))

        ci((u + d, v + d), 7.8)                        # 镜圈顶面内沿
        ci((u + d * 0.7, v + d * 0.7), 6.6)            # 镜片玻璃
        ci((u + d * 0.7, v + d * 0.7), 3.7)            # 镜筒
        ci((u + d * 0.7, v + d * 0.7), 1.6)            # 镜心高光

    # 闪光灯（双色温 LED）
    flash = rrect(31.5 - 4.2, 147.5 - 3.4, 31.5 + 4.2, 147.5 + 3.4, 1.2, 4)
    pl([P(x, y, 0) for x, y in flash], close=True)
    for dx in (-1.9, 1.9):
        cu, cv = P(31.5 + dx, 147.5, 0)
        ci((cu, cv), 1.7)

    # 激光对焦窗
    lu, lv = P(31.5, 135.5, 0)
    ci((lu, lv), 2.4)
    ci((lu, lv), 1.4)

    # 背面 SAMSUNG 标识
    tx("SAMSUNG", (OX_B + 25.5, 22.0), 6.0)


# --------------------------------------------------------------------------
# 七、标注
# --------------------------------------------------------------------------
def annotate():
    # 标题
    tx("Samsung Galaxy S23 Ultra", (12.0, 200.0), 11.0)
    tx("立体图 · 斜轴测投影（厚度方向放大 1.8 倍作图）", (12.0, 188.0), 6.0)

    # 居中打孔前摄
    tx("居中打孔前摄 12MP", (2.0, 178.0), 5.5)
    line((22.0, 176.0), (36.0, 166.0))
    line((36.0, 166.0), (39.5, 160.5))

    # 厚度（引线指向顶面）
    tx("厚 8.9", (92.0, 178.0), 6.0)
    line((91.0, 176.0), (72.0, 172.0))

    # 总高 163.4
    for yy in (0.0, H):
        line((20.0, yy), (-16.0, yy))
    line((-11.0, 0.0), (-11.0, H))
    tick((-11.0, 0.0))
    tick((-11.0, H))
    tx("163.4", (-9.0, 78.0), 6.0)

    # 总宽 78.1
    for xx in (0.0, W):
        line((xx, 6.0), (xx, -32.0))
    line((0.0, -27.0), (W, -27.0))
    tick((0.0, -27.0))
    tick((W, -27.0))
    tx("78.1", (33.0, -24.0), 6.0)

    # 屏幕说明（引线指向屏幕中部）
    tx("6.8″ AMOLED 2X", (92.0, 128.0), 5.5)
    tx("1440×3088 · 120Hz", (92.0, 119.0), 5.5)
    line((91.0, 126.0), (74.0, 120.0))
    line((74.0, 120.0), (58.0, 112.0))

    # 按键说明
    tx("音量键 / 电源键", (92.0, 70.0), 5.5)
    line((91.0, 72.0), (84.0, 88.0))
    line((84.0, 88.0), (80.5, 101.0))

    # 后置四摄
    tx("后置四摄（背面左侧一列）", (258.0, 152.0), 6.0)
    tx("200MP 主摄 + 12MP 超广角", (258.0, 143.0), 5.5)
    tx("10MP 3× 长焦 + 10MP 10× 长焦", (258.0, 134.0), 5.5)
    line((257.0, 150.0), (215.0, 149.9))
    line((215.0, 149.9), (OX_B + LENS_CX + LENS_R, 149.9))

    # 闪光灯 / 激光对焦
    tx("闪光灯 · 激光对焦", (258.0, 100.0), 5.5)
    line((257.0, 102.0), (225.0, 120.0))
    line((225.0, 120.0), (OX_B + 31.5 + 4.2, 145.0))

    # 底部说明
    tx("S Pen 插槽（机身左下角）", (0.0, -46.0), 5.5)
    line((16.0, -44.0), (13.5, -3.0))
    tx("5000mAh 电池 · 234g · 装甲铝中框 · IP68", (0.0, -58.0), 5.5)
    tx("康宁大猩猩 Victus 2 玻璃 · 骁龙 8 Gen 2 for Galaxy", (0.0, -69.0), 5.5)


# --------------------------------------------------------------------------
def main():
    import time
    # 清空模型空间 + 建立中文字体样式
    cad.send({"cmd": "sendcommand", "text": "_ERASE _ALL  "})
    time.sleep(2)
    r = cad.send({"cmd": "textstyle", "name": "S23", "font": "SimHei"})
    print("文字样式：", r)

    front_view()
    back_view()
    annotate()

    print("待绘制实体数：%d" % len(ENTS))
    ok = bad = 0
    for i, e in enumerate(ENTS):
        r = cad.send(e)
        if r.get("ok"):
            ok += 1
        else:
            bad += 1
            print("  [%d/%d] 失败 %s -> %s" % (i + 1, len(ENTS),
                                             e["cmd"], r.get("error")))
    print("完成：成功 %d，失败 %d" % (ok, bad))

    cad.send({"cmd": "zoom", "mode": "extents"})
    print(cad.send({"cmd": "count"}))


if __name__ == "__main__":
    main()
