# -*- coding: utf-8 -*-
"""绘图链路测试：计算书解析 + 剖面几何。

这层原先完全没有测试，而**两次几何 bug 都是靠打印坐标才发现的**：
  · 土层多边形先是画成三角形（漏了坡顶转折点）
  · 后又多出一条斜边（放坡底处的轮廓是多值的，取错了那一个）
两个都补上了回归用例。计算书解析同理 —— 解析错一个数，图上就是错的。

不依赖 AutoCAD，也不依赖 eg/ 里的样本（RTF 在测试里现造），CI 能跑。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadkit import calcbook  # noqa: E402


# ---------------------------------------------------------- 造 RTF 样本
def rtf_escape(s):
    """中文按 GBK 逐字节写成 \\'xx —— 与天汉软件导出的 RTF 同一种编码。"""
    out = []
    for ch in s:
        try:
            b = ch.encode("gbk")
        except UnicodeEncodeError:
            b = b"?"
        out.append("".join("\\'%02x" % x for x in b))
    return "".join(out)


def make_rtf(lines):
    body = "\\par ".join(rtf_escape(l) for l in lines)
    return ("{\\rtf1\\ansi\\ansicpg936\\deff0"
            "{\\fonttbl{\\f0\\fnil\\fcharset134 \\'cb\\'ce\\'cc\\'e5;}}"
            "\\viewkind1\\uc1\\pard\\f0\\fs24 " + body + "}")


SAMPLE_LINES = [
    "AB段_桩撑/锚结构输入信息文本",
    "计算软件:天汉基坑设计软件;软件版本:V2015.1",
    "计算时间：2017.10.16.10.25.09;计算标志码：1259-92510-31568",
    "AB段_1 综合信息",
    "项目 指标 项目 指标",
    "引用钻孔号 K1 结构正负零标高 23.000m",
    "计算坡顶标高 22.000m 结构正负零高差 1.00m",
    "计算开挖深度 5.0m 基底标高 17.000m(-6.000m)",
    "基坑等级 二级基坑 临时结构调整系数 0.9",
    "支护结构类型 桩墙撑锚结构 土压力分布模式 朗肯土压力模式",
    "AB段_2.1 土层信息",
    "序号 土层编号 土层名称 层底埋深 C φ m τ",
    "单位 m kPa 度 kPa",
    "1 ① 杂填土 1.5 8 10 1800 30",
    "2 ② 淤泥质粘土 3 10 6 896 35",
    "3 ③ 粉质粘土 10 20 10 3000 50",
    "AB段_2.2 工况信息",
    "序号 工况类型 索引 相对标高(m) 坑底边坡 预应力(KN)",
    "工况1 开挖 --- -6 ---",
    "AB段_2.3 先期荷载",
    "序号 作用深度(m) 起点距(m) 起点值(kPa) 荷载类型 分布宽度(m) 终点值(kPa)",
    "1 0 5 30 局部荷载 7 30",
    "AB段_2.4 桩顶放坡信息",
    "放坡信息共:1项总高：1.5m总宽：2.5m",
    "序号 坡高(m) 坡宽(m) 宽高比 平台宽(m)",
    "1 1.5 1.5 1 1",
    "AB段_2.5 桩排信息",
    "项目 参数 项目 参数",
    "桩顶标高 -2.500m(20.5m) 桩顶埋深 1.5m",
    "桩长 12.0m 桩排水平间距 1.2m",
    "桩身截面几何类型 圆形 面截参数 直径=800mm",
    "AB段_2.6 冠梁信息",
    "项目 参数 项目 参数",
    "冠梁高 0.6m 混凝土等级 C30",
    "内侧外扩宽度 0.1m 外侧外扩宽度 0.1m",
]


class TestCalcbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.path = tempfile.mkstemp(suffix=".rtf")
        with os.fdopen(fd, "w", encoding="latin-1") as f:
            f.write(make_rtf(SAMPLE_LINES))
        cls.p, cls.warn = calcbook.parse(cls.path)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.path)
        except OSError:
            pass

    def test_no_warnings(self):
        self.assertEqual(self.warn, [], "样本完整，不该有警告")

    def test_section_prefix_is_name(self):
        self.assertEqual(self.p["名称"], "AB段")

    def test_support_type_classified(self):
        self.assertEqual(self.p["支护类型"], "桩墙撑锚结构")
        self.assertEqual(self.p["类型"], "pile")

    def test_elevations(self):
        self.assertEqual(self.p["正负零标高"], 23.0)
        self.assertEqual(self.p["坡顶标高"], 22.0)
        self.assertEqual(self.p["基底标高"], 17.0)

    def test_pile_top_uses_absolute_value(self):
        """桩顶标高写成 '-2.500m(20.5m)'：绝对值在括号里，别取成 -2.5。"""
        self.assertEqual(self.p["桩顶标高"], 20.5)

    def test_base_uses_absolute_value(self):
        """基底标高写成 '17.000m(-6.000m)'：绝对值在前面。"""
        self.assertEqual(self.p["基底标高"], 17.0)

    def test_pile_params(self):
        self.assertEqual(self.p["桩长"], 12.0)
        self.assertEqual(self.p["桩径"], 800.0)       # 从 '直径=800mm' 里取
        self.assertEqual(self.p["桩间距"], 1200.0)     # m -> mm

    def test_beam_params(self):
        self.assertEqual(self.p["冠梁高"], 600.0)
        self.assertEqual(self.p["冠梁外扩"], 100.0)
        self.assertEqual(self.p["砼标号"], "C30")

    def test_slope_params(self):
        self.assertEqual(self.p["放坡总高"], 1500.0)
        self.assertEqual(self.p["放坡坡宽"], 1500.0)
        self.assertEqual(self.p["放坡平台宽"], 1000.0)

    def test_soils(self):
        s = self.p["土层"]
        self.assertEqual(len(s), 3)
        self.assertEqual(s[0], ("①", "杂填土", 1.5, 8.0, 10.0))
        self.assertEqual(s[2][1], "粉质粘土")

    def test_surcharge(self):
        self.assertEqual(self.p["荷载"]["起点距"], 5000.0)
        self.assertEqual(self.p["荷载"]["宽"], 7000.0)
        self.assertEqual(self.p["荷载"]["值"], "30kPa")

    def test_conditions_parsed(self):
        """工况表的行首是「工况1」不是数字，早先整张表被过滤掉了。"""
        self.assertEqual(len(self.p["工况"]), 1)
        self.assertEqual(self.p["工况"][0]["类型"], "开挖")

    def test_date(self):
        self.assertEqual(self.p["日期"], "2017.10.16")

    def test_missing_file_raises(self):
        with self.assertRaises(calcbook.ParseError):
            calcbook.parse(os.path.join(tempfile.gettempdir(), "no_such.rtf"))


class TestClassify(unittest.TestCase):
    def test_types(self):
        cases = [("桩墙撑锚结构", "pile"), ("桩锚", "pile"), ("悬臂桩", "pile"),
                 ("排桩支护", "pile"),
                 ("放坡喷锚结构", "slope"), ("土钉墙", "slope"),
                 ("双排桩支护结构", "double")]
        for raw, want in cases:
            self.assertEqual(calcbook.classify(raw), want, "判定错: %s" % raw)

    def test_unknown(self):
        self.assertIsNone(calcbook.classify("没听说过的结构"))
        self.assertIsNone(calcbook.classify(""))

    def test_double_pile_beats_pile(self):
        """「双排桩」里也含「桩」，规则顺序错了就会误判成普通桩。"""
        self.assertEqual(calcbook.classify("双排桩支护结构"), "double")


class TestNumberParsing(unittest.TestCase):
    def test_num(self):
        self.assertEqual(calcbook.num("23.000m"), 23.0)
        self.assertEqual(calcbook.num("-2.500m(20.5m)"), -2.5)
        self.assertIsNone(calcbook.num("二级基坑"))
        self.assertIsNone(calcbook.num(None))

    def test_nums(self):
        self.assertEqual(calcbook.nums("-2.500m(20.5m)"), [-2.5, 20.5])
        self.assertEqual(calcbook.nums("17.000m(-6.000m)"), [17.0, -6.0])
        self.assertEqual(calcbook.nums("没有数字"), [])


# ------------------------------------------------------------ 剖面几何
SAMPLE_EXISTS = os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "eg", "演示.dwg"))


class TestSectionGeometry(unittest.TestCase):
    """土层多边形的回归测试。

    这两个 bug 都真实发生过，且都只在图上看得见、不报错：
      1. ① 层多边形只有 3 个点 —— 漏了坡顶 (0,0)，
         于是放坡面被画成从最左端直拉下来的一条斜线；
      2. y = -放坡总高 处轮廓有**两个** x（坡脚 1500 / 平台外沿 2500），
         土层顶边取错那个就多出一条斜边。
    """

    @classmethod
    def setUpClass(cls):
        import draw_section as D
        D.load_case("CD段")
        cls.D = D

    def test_first_layer_is_trapezoid_with_slope_top(self):
        D = self.D
        pts = D.layer_polygon_pts(D.Y_TOP, -D.P["放坡总高"])
        self.assertIn((0.0, D.Y_TOP), pts,
                      "① 层必须包含坡顶点 (0,0)，否则放坡面会横贯全图")
        self.assertEqual(len(pts), 4, "① 层应是梯形，得到 %d 个点：%s" % (len(pts), pts))
        self.assertEqual(pts[0][0], D.X_LEFT)
        self.assertEqual(pts[-1][0], D.X_LEFT)

    def test_layer_below_slope_uses_outer_edge(self):
        """② 层顶边要延伸到平台外沿(2500)，不能停在坡脚(1500)。"""
        D = self.D
        k = -D.P["放坡总高"]
        pts = D.layer_polygon_pts(k, k - 1000)
        self.assertEqual(pts[1], (D.X_PLAT_END, k),
                         "② 层顶边该用平台外沿，得到 %s" % (pts[1],))

    def test_layer_bottom_at_slope_foot_uses_inner_edge(self):
        """① 层底边正好落在坡底，只能用坡脚(1500) —— 平台是挖掉的。"""
        D = self.D
        k = -D.P["放坡总高"]
        pts = D.layer_polygon_pts(D.Y_TOP, k)
        self.assertEqual(pts[-2], (D.X_SLOPE_END, k),
                         "① 层底边该用坡脚，得到 %s" % (pts[-2],))

    def test_layer_crossing_pit_bottom_has_step(self):
        """穿过基底的层：要先沿坑壁下到基底，再横向铺到右边界。"""
        D = self.D
        pts = D.layer_polygon_pts(D.Y_BOT + 1000, D.Y_BOT - 5000)
        self.assertIn((D.X_PLAT_END, D.Y_BOT), pts)
        self.assertIn((D.X_RIGHT, D.Y_BOT), pts)

    def test_layer_below_pit_is_full_width_rect(self):
        D = self.D
        top, bot = D.Y_BOT - 1000, D.Y_BOT - 6000
        pts = D.layer_polygon_pts(top, bot)
        self.assertEqual(pts, [(D.X_LEFT, top), (D.X_RIGHT, top),
                               (D.X_RIGHT, bot), (D.X_LEFT, bot)])

    def test_no_duplicate_consecutive_points(self):
        """重复点会让闭合多段线自交、填充失败。"""
        D = self.D
        top = D.Y_TOP
        for _no, _n, depth, _c, _p in D.P["土层"]:
            bot = -depth * 1000.0
            pts = D.layer_polygon_pts(top, bot)
            for a, b in zip(pts, pts[1:]):
                self.assertNotEqual(a, b, "土层多边形有重复点：%s" % pts)
            self.assertGreaterEqual(len(pts), 4,
                                    "多边形至少 4 个点，得到 %s" % pts)
            top = bot

    def test_all_layers_close_on_left_edge(self):
        D = self.D
        top = D.Y_TOP
        for _no, _n, depth, _c, _p in D.P["土层"]:
            bot = -depth * 1000.0
            pts = D.layer_polygon_pts(top, bot)
            self.assertEqual(pts[0][0], D.X_LEFT)
            self.assertEqual(pts[-1][0], D.X_LEFT)
            top = bot

    def test_layers_are_contiguous(self):
        """相邻两层必须首尾相接，不能有缝也不能重叠。"""
        D = self.D
        top = D.Y_TOP
        prev_bot = None
        for _no, _n, depth, _c, _p in D.P["土层"]:
            bot = -depth * 1000.0
            if prev_bot is not None:
                self.assertEqual(prev_bot, top, "土层之间出现了缝或重叠")
            prev_bot = bot
            top = bot

    def test_exc_profile_is_three_stage(self):
        D = self.D
        self.assertEqual(D.exc_x_at(D.Y_TOP), 0.0)                    # 坡顶
        self.assertAlmostEqual(D.exc_x_at(D.Y_TOP - 500), 500.0)      # 1:1 放坡
        self.assertEqual(D.exc_x_at(-D.P["放坡总高"]), D.X_PLAT_END)   # 平台（取外沿）
        self.assertEqual(D.exc_x_at(D.Y_BOT), D.X_RIGHT)              # 坑底以下


if __name__ == "__main__":
    unittest.main(verbosity=2)
