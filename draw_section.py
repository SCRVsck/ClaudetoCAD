#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按工程图标准生成「基坑支护结构剖面图」。

    python draw_section.py CD段 --template           # 内置参数
    python draw_section.py --rtf eg/桩悬臂.rtf        # 一份计算书 → 一张图
    python draw_section.py --dir 计算书目录/           # 一批计算书 → 一册图

标准来自 `eg/演示.dwg`：复制它当模板、清空模型空间（块表与样式表保留），
再在新图里画。图框块 `CSSDI-A3`、23 个图层、文字样式 `PM-TEXT` 都是原图的。

绘图程序按类型分发，见 `cadkit/sections/`：
    主体  pile(桩锚/悬臂) · slope(放坡土钉) · double(双排桩)
    附加  passive(被动区加固) · bracing(内支撑/格构柱) · reinforce(配筋大样) · notes(说明)
"""

import glob
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cad  # noqa: E402
from cadkit import calcbook, sections  # noqa: E402
from cadkit.sections import base  # noqa: E402

SHEET_PITCH = base.SHEET_PITCH
FAILED = []


# ============================================================ 内置参数
# 读计算书时用不到这些；不读计算书时从这儿取。三组分别对应三种主体类型。
CASES = {
    # ---------- 桩锚 / 悬臂桩 ----------
    "CD段": {
        "名称": "CD段", "图名": "CD段支护结构剖面图",
        "图号": "JS-07-2", "日期": "2024.06.20", "比例": "1:100",
        "专业": "基坑", "设计阶段": "施工图", "版本号": "V1.0",
        "基坑等级": "二级基坑", "支护类型": "悬臂桩", "类型": "pile",
        "正负零标高": 19.500, "坡顶标高": 18.500, "基底标高": 12.000,
        "桩顶标高": 17.000, "桩长": 15.0, "桩径": 1000.0, "桩间距": 1300.0,
        "冠梁高": 700.0, "冠梁外扩": 100.0,
        "放坡总高": 1500.0, "放坡坡宽": 1500.0, "放坡平台宽": 1000.0,
        "砼标号": "C30",
        "土层": [("①", "素填土", 2.0, 5, 8),
                 ("②", "粉质粘土", 4.5, 18, 12),
                 ("③", "淤泥质粉质粘土", 8.0, 12, 7),
                 ("④", "中砂", 12.0, 0, 30),
                 ("⑤", "强风化泥岩", 18.0, 60, 25)],
        "荷载": {"起点距": 2000.0, "宽": 6000.0, "值": "20kPa"},
        "附加": ["passive", "notes"],
    },
    # ---------- 桩锚（演示同源）----------
    "AB段": {
        "名称": "AB段", "图名": "AB段支护结构剖面图",
        "图号": "JS-04-1", "日期": "2017.10.16", "比例": "1:100",
        "专业": "基坑", "设计阶段": "施工图", "版本号": "V1.0",
        "基坑等级": "二级基坑", "支护类型": "桩墙撑锚结构", "类型": "pile",
        "正负零标高": 23.000, "坡顶标高": 22.000, "基底标高": 17.000,
        "桩顶标高": 20.500, "桩长": 12.0, "桩径": 800.0, "桩间距": 1200.0,
        "冠梁高": 600.0, "冠梁外扩": 100.0,
        "放坡总高": 1500.0, "放坡坡宽": 1500.0, "放坡平台宽": 1000.0,
        "砼标号": "C30",
        "土层": [("①", "杂填土", 1.5, 8, 10),
                 ("②", "淤泥质粘土", 3.0, 10, 6),
                 ("③", "粉质粘土", 10.0, 20, 10),
                 ("④", "粘土", 15.0, 30, 15),
                 ("⑤", "石灰岩", 20.0, 150, 15)],
        "荷载": {"起点距": 5000.0, "宽": 7000.0, "值": "30kPa"},
        "附加": ["bracing", "notes"],
    },
    # ---------- 放坡土钉 ----------
    "EF段": {
        "名称": "EF段", "图名": "EF段支护结构剖面图",
        "图号": "JS-09-1", "日期": "2024.06.20", "比例": "1:100",
        "专业": "基坑", "设计阶段": "施工图", "版本号": "V1.0",
        "基坑等级": "三级基坑", "支护类型": "放坡喷锚结构", "类型": "slope",
        "正负零标高": 12.000, "坡顶标高": 11.000, "基底标高": 6.000,
        # 放坡土钉不用桩，但底座要这几个键，给 0 即可
        "桩顶标高": 11.000, "桩长": 0.0, "桩径": 0.0, "桩间距": 0.0,
        "冠梁高": 0.0, "冠梁外扩": 0.0,
        "砼标号": "C25",
        "放坡总高": 1500.0, "放坡坡宽": 1500.0, "放坡平台宽": 1000.0,
        # 多级台阶：坡高 / 坡宽 / 平台宽（mm）
        "放坡台阶": [(2000.0, 1500.0, 1000.0),
                     (1500.0, 1200.0, 1000.0),
                     (1500.0, 1200.0, 0.0)],
        "土钉长": 6000.0, "土钉表": [["1", "1.5m", "1.5m", "6.0m", "15°"],
                                     ["2", "1.5m", "1.5m", "6.0m", "15°"],
                                     ["3", "1.5m", "1.5m", "5.0m", "15°"]],
        "土层": [("①", "素填土", 1.5, 5, 8),
                 ("②", "粉质粘土", 4.0, 16, 11),
                 ("③", "粘土", 8.0, 26, 14),
                 ("④", "强风化泥岩", 12.0, 50, 22)],
        "荷载": {"起点距": 1500.0, "宽": 5000.0, "值": "15kPa"},
        "附加": ["notes"],
    },
    # ---------- 双排桩 ----------
    "GH段": {
        "名称": "GH段", "图名": "GH段支护结构剖面图",
        "图号": "JS-11-1", "日期": "2024.06.20", "比例": "1:100",
        "专业": "基坑", "设计阶段": "施工图", "版本号": "V1.0",
        "基坑等级": "一级基坑", "支护类型": "双排桩支护结构", "类型": "double",
        "正负零标高": 21.000, "坡顶标高": 20.000, "基底标高": 13.500,
        "桩顶标高": 18.500, "桩长": 18.0, "桩径": 1000.0, "桩间距": 1400.0,
        "桩排间距": 2400.0, "连梁高": 600.0,
        "冠梁高": 700.0, "冠梁外扩": 100.0,
        "放坡总高": 1500.0, "放坡坡宽": 1500.0, "放坡平台宽": 1000.0,
        "砼标号": "C30",
        "土层": [("①", "杂填土", 2.0, 6, 9),
                 ("②", "淤泥质粉质粘土", 5.0, 11, 6),
                 ("③", "粉质粘土", 11.0, 22, 12),
                 ("④", "中砂", 16.0, 0, 32),
                 ("⑤", "强风化泥岩", 22.0, 55, 24)],
        "荷载": {"起点距": 2000.0, "宽": 6000.0, "值": "25kPa"},
        "附加": ["reinforce", "notes"],
    },
}


# ------------------------------------------------------------ 图纸准备
def prepare_from_template(label):
    """从演示图复制一份干净模板并打开。

    演示图里带着这套标准的**图框块、23 个图层、5 个文字样式、2 个标注样式** ——
    这些才是「标准」的载体，从零画一个图框永远只是「像」。
    """
    src = os.path.join(BASE, "eg", "演示.dwg")
    outdir = os.path.join(BASE, "out")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "%s.dwg" % label)
    if not os.path.exists(src):
        print("找不到模板 %s —— 请把演示图放在 eg/ 下" % src)
        return None
    cad.send({"cmd": "closedocs"})          # 释放占用，否则复制会失败
    time.sleep(1.0)
    shutil.copy2(src, dst)
    r = cad.send({"cmd": "open", "path": dst})
    e = cad.send({"cmd": "erase_all"})
    print("[0] 模板 %s：打开 %s 图元 → 清空后 %s\n"
          % (os.path.basename(src), r.get("entities"), e.get("after")))
    return dst


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
    named = [a for a in args if not a.startswith("-") and a not in (rtf, folder)]
    name = named[0] if named else "CD段"

    if not (rtf or folder) and name not in CASES:
        print("未知工点 %r，可选：%s" % (name, "、".join(CASES)))
        return 2

    # ---- 准备图纸 ----
    if rtf or folder:
        label = "批量出图" if folder else os.path.splitext(os.path.basename(rtf))[0]
        prepare_from_template(label)
    elif "--template" in args or "--new" in args:
        prepare_from_template(CASES[name]["图名"])

    # ---- 出图 ----
    ok, n = True, 1
    if folder:
        files = sorted(glob.glob(os.path.join(folder, "*.rtf")))
        if not files:
            print("目录里没有 .rtf：%s" % folder)
            return 2
        n = len(files)
        print("批量出图：%d 份计算书\n" % n)
        for i, f in enumerate(files):
            try:
                p, warn = calcbook.parse(f)
            except Exception as e:
                print("[%d] %s 解析失败：%s" % (i + 1, os.path.basename(f), e))
                ok = False
                continue
            for w in warn:
                print("   警告：%s" % w)
            p["图号"] = p.get("图号") or "JS-%02d-1" % (i + 1)
            p.setdefault("附加", ["notes"])
            r, _ = sections.draw_sheet(p, sheet_dx=i * SHEET_PITCH, failed=FAILED)
            ok = r and ok
            print()
    elif rtf:
        try:
            p, warn = calcbook.parse(rtf)
        except Exception as e:
            print("解析失败：%s" % e)
            return 1
        for w in warn:
            print("   警告：%s" % w)
        p.setdefault("附加", ["notes"])
        ok, _ = sections.draw_sheet(p, sheet_dx=0.0, failed=FAILED)
    else:
        ok, _ = sections.draw_sheet(CASES[name], sheet_dx=0.0, failed=FAILED)

    base.zoom_to_sheets(cad.send, n)
    print("\n完成。实体总数 %s；失败项：%s"
          % (cad.send({"cmd": "count"}).get("count"), FAILED if FAILED else "无"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
