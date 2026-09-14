# -*- coding: utf-8 -*-
"""自动绘图的可调用入口（打包后由 `cadbridge draw` 使用）。

原先这套逻辑在根目录的 `draw_section.py` 里 —— 那是个**独立脚本**，
打包进 exe 的只有 `cadkit`，所以装了软件的人根本调不到绘图功能。
挪进包里之后，CLI 和脚本都能用同一份实现。
"""

import glob
import os
import shutil
import sys
import time

from . import calcbook, config, paths, sections
from .sections import base

SHEET_PITCH = base.SHEET_PITCH
FAILED = []


# ============================================================ 内置参数
# 读计算书时用不到这些；不读计算书时从这儿取。三组对应三种主体类型。
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
        # 放坡不用桩，但底座要这几个键，给 0 即可
        "桩顶标高": 11.000, "桩长": 0.0, "桩径": 0.0, "桩间距": 0.0,
        "冠梁高": 0.0, "冠梁外扩": 0.0, "砼标号": "C25",
        "放坡总高": 1500.0, "放坡坡宽": 1500.0, "放坡平台宽": 1000.0,
        # 多级台阶：坡高 / 坡宽 / 平台宽（mm）
        "放坡台阶": [(2000.0, 1500.0, 1000.0),
                     (1500.0, 1200.0, 1000.0),
                     (1500.0, 1200.0, 0.0)],
        "土钉长": 6000.0,
        "土钉表": [["1", "1.5m", "1.5m", "6.0m", "15°"],
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


# ------------------------------------------------------------ 模板
class TemplateError(RuntimeError):
    """找不到可用的标准模板。"""


def find_template(explicit=None):
    """找一个带标准图框块的模板 DWG。

    标准不是「描述」而是**那张演示图本身** —— 图框块 `CSSDI-A3`、
    23 个图层、文字样式都在它里面，从零画一个图框永远只是「像」。
    查找顺序：命令行指定 → 配置项 → 安装目录下的 eg/演示.dwg。
    """
    cands = []
    if explicit:
        cands.append(explicit)
    cfg = config.load()
    if cfg.get("template_dwg"):
        cands.append(cfg["template_dwg"])
    here = paths.install_dir()
    cands += [os.path.join(here, "eg", "演示.dwg"),
              os.path.join(here, "演示.dwg"),
              os.path.join(here, "templates", "演示.dwg")]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)

    raise TemplateError(
        "找不到标准模板 DWG。绘图需要一份带标准图框块（CSSDI-A3）的图纸作为模板，\n"
        "  它承载着图框、图层和文字样式 —— 这是「标准」的载体。\n"
        "  任选一种方式提供：\n"
        "    1) 把模板放到 %s\\eg\\演示.dwg\n"
        "    2) 命令行指定：--template-dwg <路径>\n"
        "    3) 写进配置：cadbridge config template_dwg <路径>"
        % paths.install_dir())


def prepare_from_template(label, template=None, outdir=None):
    """复制模板 → 打开 → 清空模型空间（块表/样式表保留）。"""
    src = find_template(template)
    outdir = outdir or os.path.join(paths.install_dir(), "out")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "%s.dwg" % label)

    from . import protocol
    protocol.request({"cmd": "closedocs"}, timeout=120)   # 释放占用，否则复制会失败
    time.sleep(1.0)
    shutil.copy2(src, dst)
    r = protocol.request({"cmd": "open", "path": dst}, timeout=300)
    e = protocol.request({"cmd": "erase_all"}, timeout=300)
    print("[0] 模板 %s：打开 %s 图元 → 清空后 %s\n"
          % (os.path.basename(src), r.get("entities"), e.get("after")))
    return dst


# ------------------------------------------------------------ 驱动
def run(cases, rtf=None, folder=None, template=None, outdir=None,
        list_only=False):
    """出图主流程。返回退出码。"""
    from . import protocol
    FAILED.clear()

    if list_only:
        print("内置工点：")
        for k, v in cases.items():
            print("  %-6s %-4s %s" % (k, v["类型"], v["图名"]))
        main_t, addon_t = sections.supported()
        print("\n主体类型：%s" % "、".join(
            "%s(%s)" % (k, sections.TYPE_NAMES[k]) for k in main_t))
        print("附加内容：%s" % "、".join(
            "%s(%s)" % (k, sections.TYPE_NAMES[k]) for k in addon_t))
        return 0

    # ---- 准备图纸 ----
    try:
        if rtf or folder:
            label = ("批量出图" if folder
                     else os.path.splitext(os.path.basename(rtf))[0])
            prepare_from_template(label, template, outdir)
        else:
            prepare_from_template(cases["图名"], template, outdir)
    except TemplateError as e:
        print("错误：%s" % e)
        return 2

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
        ok, _ = sections.draw_sheet(cases, sheet_dx=0.0, failed=FAILED)

    base.zoom_to_sheets(protocol.request, n)
    print("\n完成。实体总数 %s；失败项：%s"
          % (protocol.request({"cmd": "count"}).get("count"),
             FAILED if FAILED else "无"))
    return 0 if ok else 1
