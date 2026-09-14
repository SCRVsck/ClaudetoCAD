#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""示例：画一个长方形并标注尺寸，尺寸用绿色。

    python draw_rect_dim.py

尺寸走桥接的 add_dim 指令（COM 的 AddDimRotated），而不是 sendcommand
敲 DIMLINEAR —— 后者会停在命令行等输入，把 AutoCAD 卡成忙态。
"""

import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402

# 长方形尺寸与位置。
# 放在 (800, 0)：图形里已有别的示例内容（二维图在 0~500，三维模型在 520~600），
# 画在这里不会跟它们叠在一起。
X0, Y0 = 800.0, 0.0
W, H = 200.0, 120.0
OFF = 28.0          # 尺寸线离图形的距离

GREEN = 3           # AutoCAD 颜色索引：1红 2黄 3绿 4青 5蓝 6洋红 7白/黑
DIM_TEXT_H = 4.0    # 标注文字高度


def call(req):
    r = cad.send(req)
    if not r.get("ok"):
        print("  !! %s 失败: %s" % (req.get("cmd"), r.get("error")))
    return r


def main():
    x1, y1 = X0 + W, Y0 + H

    print("[1] 长方形 %.0f × %.0f" % (W, H))
    r = call({"cmd": "add_polyline", "closed": True,
              "points": [[X0, Y0], [x1, Y0], [x1, y1], [X0, y1]]})
    print("    句柄", r.get("handle"))

    print("[2] 水平尺寸（标宽 %.0f），尺寸线在下方" % W)
    rh = call({"cmd": "add_dim", "mode": "rotated",
               "p1": [X0, Y0], "p2": [x1, Y0],
               "loc": [(X0 + x1) / 2.0, Y0 - OFF], "angle": 0.0,
               "color": GREEN, "text_height": DIM_TEXT_H})
    print("    句柄 %s  实测尺寸 %s" % (rh.get("handle"), rh.get("measurement")))

    print("[3] 垂直尺寸（标高 %.0f），尺寸线在右侧" % H)
    rv = call({"cmd": "add_dim", "mode": "rotated",
               "p1": [x1, Y0], "p2": [x1, y1],
               "loc": [x1 + OFF, (Y0 + y1) / 2.0], "angle": math.pi / 2,
               "color": GREEN, "text_height": DIM_TEXT_H})
    print("    句柄 %s  实测尺寸 %s" % (rv.get("handle"), rv.get("measurement")))

    print("[4] 缩放到长方形")
    # 不用 extents：图形里可能还有别的图元，extents 会把镜头拉到很远，
    # 长方形变得很小。直接对准它自己。
    call({"cmd": "zoom", "mode": "center",
          "center": [(X0 + x1) / 2.0 + OFF / 2.0,
                     (Y0 + y1) / 2.0 - OFF / 2.0, 0.0],
          "height": max(W, H) * 1.9})
    print("完成。实体总数：", cad.send({"cmd": "count"}).get("count"))


if __name__ == "__main__":
    main()
