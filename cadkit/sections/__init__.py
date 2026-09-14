# -*- coding: utf-8 -*-
"""各支护类型的绘图程序。

分两类：
  **主体类型**（决定开挖轮廓、画一张独立图纸）
      pile      桩锚 / 悬臂桩
      slope     放坡土钉
      double    双排桩
  **附加内容**（叠加在主体剖面上，不单独出图）
      passive   被动区加固（坑底以下）
      bracing   内支撑 + 格构柱
      reinforce 桩身配筋大样
      notes     设计施工说明文字块

参数里用 `附加` 指定要叠加哪些，例如 `["passive", "bracing"]`。
原 VB 里这些是揉在同一个过程里的；拆开之后任一主体都能配任一组附加。
"""

from . import base

MAIN = {}
ADDONS = {}


def _register():
    from . import bracing, doublepile, notes, passive, pile, reinforce, slope
    MAIN.update({"pile": pile, "slope": slope, "double": doublepile})
    ADDONS.update({"passive": passive, "bracing": bracing,
                   "reinforce": reinforce, "notes": notes})


_register()

TYPE_NAMES = {
    "pile": "桩锚 / 悬臂桩",
    "slope": "放坡土钉",
    "double": "双排桩",
    "passive": "被动区加固",
    "bracing": "内支撑 / 格构柱",
    "reinforce": "桩身配筋大样",
    "notes": "设计施工说明",
}


def supported():
    return dict(MAIN), dict(ADDONS)


def make_ctx(params, sheet_dx=0.0, **kw):
    """按类型造上下文 —— 放坡要换成多级台阶轮廓。"""
    t = params.get("类型", "pile")
    if t == "slope":
        from .slope import SlopeCtx
        return SlopeCtx(params, sheet_dx=sheet_dx, **kw)
    return base.Ctx(params, sheet_dx=sheet_dx, **kw)


def draw_sheet(params, sheet_dx=0.0, failed=None):
    """画一张完整的图。返回 (是否成功, 上下文)。"""
    stype = params.get("类型", "pile")
    if stype not in MAIN:
        print("  跳过：支护类型 %r（%s）还没有绘图程序" % (params.get("支护类型"), stype))
        print("        主体类型已实现：%s"
              % "、".join("%s(%s)" % (k, v) for k, v in TYPE_NAMES.items()
                         if k in MAIN))
        return False, None

    failed = failed if failed is not None else []
    ctx = make_ctx(params, sheet_dx=sheet_dx, failed=failed)
    print("=== %s ===" % (params.get("图名") or params.get("名称")))

    MAIN[stype].draw(ctx)                    # 主体（含图框/图签/说明）

    for key in params.get("附加", []):
        mod = ADDONS.get(key)
        if mod is None:
            print("  未知附加项：%r" % key)
            continue
        mod.draw(ctx)

    return True, ctx
