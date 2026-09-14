# -*- coding: utf-8 -*-
"""工程图标准（基坑支护施工图）。

这些表**不是拍脑袋定的**，是从 `eg/Drawing Module.vb`（天汉基坑设计软件的
配套绘图模块，10569 行）里逐条抄出来的 —— 图层名、线型、颜色、土层填充图案，
都和那套图纸一致。复刻图纸时以这里为准。

来源对照：
    图层表      <- Drawing Module.vb  PileSupport() 开头的 Layers.Add 段
    土层图案表   <- Drawing Module.vb  soilpattern()
    坐标系      <- 地面线 y=0，标高向下为负；每张图按 frameSpac 水平排开
"""

# ---------------------------------------------------------------- 图层表
# 图层名 -> (线型, AutoCAD 颜色索引)
LAYERS = {
    "土层线":        ("DASHED", 7),
    "边坡线":        ("Continuous", 3),
    "土钉":          ("Continuous", 1),
    "尺寸标注":      ("Continuous", 3),
    "注释":          ("Continuous", 7),
    "竖向隔渗帷幕":  ("Continuous", 9),
    "冠梁":          ("Continuous", 6),
    "地下室":        ("DASHED", 200),
    "腰梁":          ("Continuous", 30),
    "支护桩":        ("Continuous", 5),
    "桩间挂网":      ("Continuous", 4),
    "传力带":        ("Continuous", 203),
    "被动区加固":    ("Continuous", 9),
    "内支撑":        ("Continuous", 2),
    "格构柱":        ("Continuous", 4),
    "剖面图用轴线":  ("DASHDOT", 15),
    "平面图用轴线":  ("DASHDOT", 1),
    "设计说明":      ("Continuous", 4),
    "图名":          ("Continuous", 7),
    "图框":          ("Continuous", 7),
    "其它":          ("Continuous", 7),
}

# 需要从 acad.lin 加载的线型（Continuous 是内置的，不用加载）
LINETYPES = ["DASHED", "DASHDOT"]

# ------------------------------------------------------------ 土层图案表
# 土层名 -> (填充图案名, 颜色索引)。别名（黏/粘）按 VB 里的写法一并列出。
SOIL_PATTERNS = {
    "杂填土": ("CQ杂填土", 0),
    "素填土": ("CQ素填土", 1),
    "卵石": ("CQ卵石", 16),
    "碎石": ("CQ碎石", 15),
    "圆砾": ("CQ圆砾", 14),
    "砾砂": ("CQ砾砂", 13),
    "粗砂": ("CQ粗砂", 12),
    "中粗砂": ("CQ粗砂", 12),
    "中砂": ("CQ中砂", 11),
    "细砂": ("CQ细砂", 10),
    "粉砂": ("CQ粉砂", 9),
    "粉土": ("CQ粉土", 2),
    "粉质粘土": ("CQ粉质粘土", 3),
    "粉质黏土": ("CQ粉质粘土", 3),
    "粘土": ("CQ粘土", 4),
    "黏土": ("CQ粘土", 4),
    "粘性土": ("CQ粘土", 4),
    "黏性土": ("CQ粘土", 4),
    "红黏土": ("CQ红粘土", 5),
    "红粘土": ("CQ红粘土", 5),
    "淤泥": ("CQ淤泥", 6),
    "淤泥质土": ("CQ淤泥", 6),
    "淤泥质粉土": ("CQ淤泥质粉土", 7),
    "淤泥质粉质粘土": ("CQ淤泥质粉质粘土", 5),
    "淤泥质粉质黏土": ("CQ淤泥质粉质粘土", 5),
    "淤泥质粘土": ("CQ淤泥质粘土", 6),
    "淤泥质黏土": ("CQ淤泥质粘土", 6),
    "石灰岩": ("AR-B816", 150),
}

# CQ 系列是本项目**自带的自定义图案**（在某个 .pat 里），不是 AutoCAD 标配。
# 机器上没装那个 .pat 时填充会失败，届时按土性退到 AutoCAD 标准图案，
# 保证图还能看，并在返回值里标明用了兜底。
FALLBACK_PATTERNS = {
    "杂填土": ("ANSI31", 1),
    "素填土": ("ANSI31", 1),
    "卵石": ("AR-CONC", 16),
    "碎石": ("AR-CONC", 15),
    "圆砾": ("AR-CONC", 14),
    "砾砂": ("AR-SAND", 13),
    "粗砂": ("AR-SAND", 12),
    "中粗砂": ("AR-SAND", 12),
    "中砂": ("AR-SAND", 11),
    "细砂": ("AR-SAND", 10),
    "粉砂": ("AR-SAND", 9),
    "粉土": ("ANSI31", 2),
    "粉质粘土": ("ANSI31", 3),
    "粘土": ("ANSI31", 4),
    "红粘土": ("ANSI31", 5),
    "淤泥": ("ANSI37", 6),
    "石灰岩": ("AR-B816", 150),
}

# 填充比例。VB 里土层填充用的是 PatternScale=100 —— 图纸以 mm 为单位、
# 一张图铺开几万单位，比例小了根本看不见纹路。
SOIL_PATTERN_SCALE = 100.0
SOIL_PATTERN_SCALE_FALLBACK = 15.0
# 个别图案有自己的合适比例。AR-B816 是砖形图案（8×16），
# 用 100 会被放大到完全看不见 —— 实测就是这么空白一片的。
PATTERN_SCALE_OVERRIDE = {
    "AR-B816": 20.0,
    "AR-CONC": 8.0,
    "AR-SAND": 10.0,
    "ANSI31": 15.0,
    "ANSI37": 15.0,
}


def pattern_scale(pat, default):
    return PATTERN_SCALE_OVERRIDE.get(pat, default)

# 每张图纸的水平间距（VB: frameSpac = (x-1) * (图框宽*1000 + 42000)）
FRAME_STEP_BASE = 42000.0

DEFAULT_TITLE = "AB段支护结构剖面图"
DEFAULT_COMPANY = "中南勘察设计院（湖北）有限责任公司"


def soil_style(name):
    """按土层名查 (图案, 颜色, 比例, 是否兜底)。

    查不到、或标准图案是本项目自定义的 CQ 系列而本机没装对应 .pat 时，
    退回 AutoCAD 标准图案 —— 保证图能看，并用第四项标明用了兜底。
    """
    n = (name or "").strip()
    # 去掉编号前缀，如 "② 淤泥质粘土" -> "淤泥质粘土"
    for sep in (" ", "\t"):
        if sep in n:
            n = n.split(sep, 1)[1]
            break
    if n not in SOIL_PATTERNS:
        return "ANSI31", 7, SOIL_PATTERN_SCALE_FALLBACK, True

    pat, col = SOIL_PATTERNS[n]
    if not pat.startswith("CQ"):
        return pat, col, pattern_scale(pat, SOIL_PATTERN_SCALE), False

    # CQ* 是本项目自带图案，本机多半没有
    fb = FALLBACK_PATTERNS.get(n)
    if fb:
        return fb[0], fb[1], pattern_scale(fb[0], SOIL_PATTERN_SCALE_FALLBACK), True
    return ("ANSI31", col if col else 7,
            pattern_scale("ANSI31", SOIL_PATTERN_SCALE_FALLBACK), True)


def describe():
    return {
        "layers": len(LAYERS),
        "soils": len(SOIL_PATTERNS),
        "title": DEFAULT_TITLE,
    }
