# -*- coding: utf-8 -*-
"""计算书解析：天汉基坑设计软件输出的 RTF → 结构化参数。

原 `Drawing Module.vb` 读这些参数用的是**段落序号 + `InStr` 截取**
（`Paragraphs(nPara)`、`Mid(s, site1+2, site2-site1-2)`），极其脆弱 ——
计算书多一行、少一行就全错位。好在这份 RTF 本身是**规整的分段表格**，
按标题切段再逐行解析要稳得多。

输出的字典直接对应 `draw_section.py` 的 `CASES` 结构，可以喂给生成器。
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.rtftext import rtf_text  # noqa: E402


class ParseError(Exception):
    pass


# ------------------------------------------------------------ 基础工具
def num(s, default=None):
    """从 '23.000m' / '-2.500m(20.5m)' / '1.2' 里取第一个数。"""
    if s is None:
        return default
    m = re.search(r"-?\d+(?:\.\d+)?", str(s))
    return float(m.group(0)) if m else default


def nums(s):
    """取出一行里所有的数（用于 '-2.500m(20.5m)' 这种双值）。"""
    if s is None:
        return []
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", str(s))]


def sections(text):
    """按「XX段_N[.M] 标题」切段 -> [(标题, [行...]), ...]（保序）"""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^(\S*?段_\d+(?:\.\d+)?)\s+(.+)$", line)
        if m:
            cur = ("%s %s" % (m.group(1), m.group(2).strip()), [])
            out.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return out


def find_section(secs, keyword):
    for title, lines in secs:
        if keyword in title:
            return title, lines
    return None, []


def kv_pairs(lines):
    """「项目 值 项目 值」两列键值 -> dict（也兼容单列）。"""
    d = {}
    for line in lines:
        if re.match(r"^(项目|序号|单位)\b", line):
            continue
        toks = line.split()
        if len(toks) >= 4 and len(toks) % 2 == 0:
            half = len(toks) // 2
            d[toks[0]] = " ".join(toks[1:half])
            d[toks[half]] = " ".join(toks[half + 1:])
        elif len(toks) == 2:
            d[toks[0]] = toks[1]
    return d


def _rows(lines):
    """丢掉表头/单位行，留下数据行。

    数据行不一定以数字开头 —— 工况表的行首是「工况1」，最早只认数字，
    整张工况表都被滤掉了。
    """
    out = []
    for line in lines:
        if re.match(r"^(序号|单位|项目|放坡信息共)", line):
            continue
        if re.match(r"^(\d+\s|工况\s*\d)", line):
            out.append(line.split())
    return out


# ------------------------------------------------------------ 各分表
def parse_soils(lines):
    """土层信息 -> [(编号, 名称, 层底埋深, C, φ), ...]"""
    out = []
    for t in _rows(lines):
        if len(t) < 6:
            continue
        try:
            out.append((t[1], t[2], float(t[3]), float(t[4]), float(t[5])))
        except (ValueError, IndexError):
            continue
    return out


def parse_surcharge(lines):
    """先期荷载 -> {起点距, 宽, 值}（取第一行局部荷载）"""
    for t in _rows(lines):
        # 序号 作用深度 起点距 起点值 荷载类型 分布宽度 终点值
        if len(t) >= 7:
            try:
                return {"起点距": float(t[2]) * 1000.0,
                        "宽": float(t[5]) * 1000.0,
                        "值": "%gkPa" % float(t[3])}
            except ValueError:
                continue
    return None


def parse_slope(lines):
    """桩顶放坡信息 -> {总高, 总宽, 坡宽, 平台宽}（mm）"""
    out = {}
    for line in lines:
        m = re.search(r"总高[：:]\s*([\d.]+)m.*?总宽[：:]\s*([\d.]+)m", line)
        if m:
            out["总高"] = float(m.group(1)) * 1000.0
            out["总宽"] = float(m.group(2)) * 1000.0
    rows = _rows(lines)
    if rows:
        t = rows[0]
        # 序号 坡高 坡宽 宽高比 平台宽
        if len(t) >= 5:
            out.setdefault("总高", num(t[1], 1.5) * 1000.0)
            out["坡宽"] = num(t[2], 1.5) * 1000.0
            out["平台宽"] = num(t[4], 1.0) * 1000.0
    return out or None


def parse_conditions(lines):
    """工况信息 -> [{工况, 类型, 相对标高}, ...]"""
    out = []
    for t in _rows(lines):
        # 工况1 开挖 --- -6 ---
        if len(t) >= 4:
            out.append({"工况": t[0], "类型": t[1],
                        "相对标高": num(t[3])})
    return out


def _section_prefix(secs):
    """从段落名里取工点号，如 'AB段_1 综合信息' -> 'AB段'。"""
    for title, _ in secs:
        m = re.match(r"^(\S*?段)_\d", title)
        if m:
            return m.group(1)
    return None


# -------------------------------------------------------- 支护类型判定
# 原 VB 是把文档里读到的字符串直接比："桩墙撑锚结构" -> PileSupport。
# 这里放宽成包含匹配，并把结果归一成类型键。
TYPE_RULES = [
    ("double", ("双排桩",)),
    ("slope", ("放坡", "土钉", "喷锚")),
    ("pile", ("桩墙撑锚", "桩撑", "桩锚", "悬臂桩", "排桩")),
]


def classify(text):
    s = (text or "").strip()
    for key, keys in TYPE_RULES:
        if any(k in s for k in keys):
            return key
    return None


# ------------------------------------------------------------ 主入口
def parse(path):
    """解析一份计算书，返回 (参数字典, 警告列表)。"""
    if not os.path.exists(path):
        raise ParseError("找不到计算书：%s" % path)
    text = rtf_text(path)
    secs = sections(text)
    if not secs:
        raise ParseError("没切出任何段落，文件格式可能不对：%s" % path)
    warn = []

    kv = {}
    for title, lines in secs:
        if "综合信息" in title:
            kv.update(kv_pairs(lines))
    _, soil_lines = find_section(secs, "土层信息")
    _, pile_lines = find_section(secs, "桩排信息")
    _, beam_lines = find_section(secs, "冠梁信息")
    _, load_lines = find_section(secs, "先期荷载")
    _, slope_lines = find_section(secs, "放坡信息")
    _, cond_lines = find_section(secs, "工况信息")

    pile = kv_pairs(pile_lines)
    beam = kv_pairs(beam_lines)
    soils = parse_soils(soil_lines)
    if not soils:
        warn.append("没解析出土层信息")

    # --- 支护类型 ---
    raw_type = kv.get("支护结构类型", "")
    stype = classify(raw_type)
    if stype is None:
        warn.append("认不出支护结构类型 %r（按桩锚处理）" % raw_type)
        stype = "pile"

    # --- 标高 ---
    # 计算书里同一项常给「绝对值(相对值)」两个数，且顺序不固定：
    #   基底标高 17.000m(-6.000m)   -> 先绝对值后相对值
    #   桩顶标高 -2.500m(20.5m)     -> 先相对值后绝对值
    # 判据：取与「正负零标高」量级接近的那个当绝对值。
    zero = num(kv.get("结构正负零标高"), 0.0)
    top = num(kv.get("计算坡顶标高"), zero)

    def absolute(raw, fallback):
        vs = nums(raw)
        if not vs:
            return fallback
        if len(vs) == 1:
            # 单个值时看它是否大于坡顶标高的一半量级，否则当相对值换算
            return vs[0] if vs[0] > top - 100 else top + vs[0]
        return min(vs, key=lambda v: abs(v - zero))

    base = absolute(kv.get("基底标高"), top - num(kv.get("计算开挖深度"), 5.0))
    pile_top = absolute(pile.get("桩顶标高"), top - num(pile.get("桩顶埋深"), 1.5))

    def dia(raw):
        # '直径=800mm' / '800'
        v = nums(raw)
        return v[-1] if v else 800.0

    def mm(raw, default):
        v = num(raw, None)
        return default if v is None else v * 1000.0

    slope = parse_slope(slope_lines) or {}
    prefix = _section_prefix(secs) or _pick_name(path)
    params = {
        "名称": prefix,
        "图名": "%s支护结构剖面图" % prefix,
        "日期": _pick_date(text),
        "比例": "1:100",
        "基坑等级": kv.get("基坑等级", "二级基坑"),
        "支护类型": raw_type or "桩墙撑锚结构",
        "类型": stype,                       # pile / slope / double
        "正负零标高": zero,
        "坡顶标高": top,
        "基底标高": base,
        "桩顶标高": pile_top,
        "桩长": num(pile.get("桩长"), 12.0),
        "桩径": dia(pile.get("面截参数")),
        "桩间距": mm(pile.get("桩排水平间距"), 1200.0),
        "冠梁高": mm(beam.get("冠梁高"), 600.0),
        "冠梁外扩": mm(beam.get("内侧外扩宽度"), 100.0),
        "放坡总高": slope.get("总高", 1500.0),
        "放坡坡宽": slope.get("坡宽", 1500.0),
        "放坡平台宽": slope.get("平台宽", 1000.0),
        "砼标号": beam.get("混凝土等级", "C30"),
        "土层": soils,
        "荷载": parse_surcharge(load_lines),
        "工况": parse_conditions(cond_lines),
        "_源文件": os.path.basename(path),
        "_岩土参数": {k: kv.get(k) for k in
                      ("引用钻孔号", "临时结构调整系数", "土压力分布模式",
                       "水土压力计算方法", "被动土压力折减系数") if k in kv},
    }
    return params, warn


def _pick_name(path):
    """从文件名猜工点名，如 'PM3.rtf' -> 'PM3'。"""
    return os.path.splitext(os.path.basename(path))[0]


def _pick_date(text):
    m = re.search(r"计算时间[：:]\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return "%s.%02d.%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ""


if __name__ == "__main__":
    import json
    sys.stdout.reconfigure(encoding="utf-8")
    p, w = parse(sys.argv[1])
    print(json.dumps(p, ensure_ascii=False, indent=2))
    if w:
        print("\n警告：", "；".join(w))
