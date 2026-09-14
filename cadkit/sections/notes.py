# -*- coding: utf-8 -*-
"""设计施工说明文字块（对应 VB 的 `pileDesignExp`）。

原 VB 从参数表第 35 行往下逐条取说明文字，一级标题（一、二、三…）
标红，标题下面画一条青色粗线。这里改成接受一个字符串列表，
渲染规则一致 —— 说明文字本来就该由参数表提供，不该写死在绘图代码里。
"""

from . import base

TXT = base.TXT
CJK_NUM = "一二三四五六七八九十"


def draw(ctx, notes=None, at=None, title="支护桩设计施工说明"):
    """在图纸上排一段说明文字。

    notes 为 None 时用参数里的「设计说明」；每条以「一、」这类开头的
    作一级标题（红字），其余为正文（白字）。
    """
    notes = notes if notes is not None else ctx.P.get("设计说明") or []
    if not notes:
        print("[N] 无说明文字，跳过")
        return
    if at is None:
        at = (ctx.X_RIGHT + 12000.0, ctx.Y_TOP - 1000.0)

    print("[N] 设计施工说明（%d 条）" % len(notes))
    x, y = at

    ctx.mtext(title, (x, y), h=600, layer="设计说明", width=16000.0)
    # 标题下的粗线（原 VB 是 Offset(150) + ConstantWidth 40）
    ctx.line((x, y - 250), (x + 15000, y - 250), "设计说明")

    yy = y - 1400
    for s in notes:
        s = str(s)
        is_head = bool(s) and s[0] in CJK_NUM and "、" in s[:3]
        color = 1 if is_head else 256          # 一级标题红字
        r = ctx.call({"cmd": "add_mtext", "text": s, "layer": "设计说明",
                      "insert": [ctx.FX(x), yy + ctx.OY, 0.0],
                      "height": 450.0, "width": 16000.0,
                      "color": color if is_head else None},
                     quiet=True, record=False)
        if not r.get("ok"):
            # 桥接的 add_mtext 暂不支持 color，退成普通文字再单独设色
            h = ctx.text(s, (x, yy), h=450, layer="设计说明", xform=False)
            if is_head and h:
                ctx.call({"cmd": "setprop", "handle": h, "color": 1}, quiet=True)
        yy -= 700
    return yy
