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
    """土层多边形的回归测试（几何函数现在在 cadkit/sections/base.py）。

    这两个 bug 都真实发生过，且都只在图上看得见、不报错：
      1. ① 层多边形只有 3 个点 —— 漏了坡顶 (0,0)，
         于是放坡面被画成从最左端直拉下来的一条斜线；
      2. y = -放坡总高 处轮廓有**两个** x（坡脚 1500 / 平台外沿 2500），
         土层顶边取错那个就多出一条斜边。
    """

    @classmethod
    def setUpClass(cls):
        from cadkit import draw, sections
        from cadkit.sections import base
        cls.ctx = sections.make_ctx(draw.CASES["CD段"])
        cls.base = base

    # 便捷取用
    @property
    def c(self):
        return self.ctx

    def test_first_layer_is_trapezoid_with_slope_top(self):
        c, b = self.ctx, self.base
        pts = b.layer_polygon_pts(c, c.Y_TOP, -c.P["放坡总高"])
        self.assertIn((0.0, c.Y_TOP), pts,
                      "① 层必须包含坡顶点 (0,0)，否则放坡面会横贯全图")
        self.assertEqual(len(pts), 4, "① 层应是梯形，得到 %d 个点：%s" % (len(pts), pts))
        self.assertEqual(pts[0][0], c.X_LEFT)
        self.assertEqual(pts[-1][0], c.X_LEFT)

    def test_layer_below_slope_uses_outer_edge(self):
        """② 层顶边要延伸到平台外沿，不能停在坡脚。"""
        c, b = self.ctx, self.base
        k = -c.P["放坡总高"]
        pts = b.layer_polygon_pts(c, k, k - 1000)
        self.assertEqual(pts[1], (c.X_PLAT_END, k),
                         "② 层顶边该用平台外沿，得到 %s" % (pts[1],))

    def test_layer_bottom_at_slope_foot_uses_inner_edge(self):
        """① 层底边正好落在坡底，只能用坡脚 —— 平台是挖掉的。"""
        c, b = self.ctx, self.base
        k = -c.P["放坡总高"]
        pts = b.layer_polygon_pts(c, c.Y_TOP, k)
        self.assertEqual(pts[-2], (c.X_SLOPE_END, k),
                         "① 层底边该用坡脚，得到 %s" % (pts[-2],))

    def test_layer_crossing_pit_bottom_has_step(self):
        c, b = self.ctx, self.base
        pts = b.layer_polygon_pts(c, c.Y_BOT + 1000, c.Y_BOT - 5000)
        self.assertIn((c.X_PLAT_END, c.Y_BOT), pts)
        self.assertIn((c.X_RIGHT, c.Y_BOT), pts)

    def test_layer_below_pit_is_full_width_rect(self):
        c, b = self.ctx, self.base
        top, bot = c.Y_BOT - 1000, c.Y_BOT - 6000
        self.assertEqual(b.layer_polygon_pts(c, top, bot),
                         [(c.X_LEFT, top), (c.X_RIGHT, top),
                          (c.X_RIGHT, bot), (c.X_LEFT, bot)])

    def test_no_duplicate_consecutive_points(self):
        """重复点会让闭合多段线自交、填充失败。"""
        c, b = self.ctx, self.base
        top = c.Y_TOP
        for _no, _n, depth, _cc, _p in c.P["土层"]:
            bot = -depth * 1000.0
            pts = b.layer_polygon_pts(c, top, bot)
            for a, z in zip(pts, pts[1:]):
                self.assertNotEqual(a, z, "土层多边形有重复点：%s" % pts)
            self.assertGreaterEqual(len(pts), 4, "多边形至少 4 个点，得到 %s" % pts)
            top = bot

    def test_all_layers_close_on_left_edge(self):
        c, b = self.ctx, self.base
        top = c.Y_TOP
        for _no, _n, depth, _cc, _p in c.P["土层"]:
            bot = -depth * 1000.0
            pts = b.layer_polygon_pts(c, top, bot)
            self.assertEqual(pts[0][0], c.X_LEFT)
            self.assertEqual(pts[-1][0], c.X_LEFT)
            top = bot

    def test_layers_are_contiguous(self):
        """相邻两层必须首尾相接，不能有缝也不能重叠。"""
        top, prev_bot = self.ctx.Y_TOP, None
        for _no, _n, depth, _c, _p in self.ctx.P["土层"]:
            bot = -depth * 1000.0
            if prev_bot is not None:
                self.assertEqual(prev_bot, top, "土层之间出现了缝或重叠")
            prev_bot = bot
            top = bot

    def test_exc_profile_is_three_stage(self):
        c = self.ctx
        self.assertEqual(c.profile_x(c.Y_TOP), 0.0)                     # 坡顶
        self.assertAlmostEqual(c.profile_x(c.Y_TOP - 500), 500.0)       # 1:1 放坡
        self.assertEqual(c.profile_x(-c.P["放坡总高"]), c.X_PLAT_END)    # 平台外沿
        self.assertEqual(c.profile_x(c.Y_BOT), c.X_RIGHT)               # 坑底以下


class TestAllTypes(unittest.TestCase):
    """三种主体类型都要能建出上下文并算出合法几何 —— 不需要 AutoCAD。

    新增一类绘图程序时最容易犯的错就是几何自相矛盾（多边形自交、
    标高顺序反了），这里先把它们挡在绘图之前。
    """

    @classmethod
    def setUpClass(cls):
        from cadkit import draw, sections
        cls.draw, cls.sections = draw, sections

    def _ctx(self, name):
        return self.sections.make_ctx(self.draw.CASES[name])

    def test_all_cases_construct(self):
        for name in self.draw.CASES:
            c = self._ctx(name)
            self.assertLess(c.Y_BOT, c.Y_TOP, "%s 的基底该在坡顶之下" % name)
            self.assertGreater(c.Y_SOIL_BOT, c.Y_PILE_BOT - 1e6)

    def test_all_cases_produce_valid_layer_polygons(self):
        from cadkit.sections import base as b
        for name in self.draw.CASES:
            c = self._ctx(name)
            top = c.Y_TOP
            for _no, _n, depth, _cc, _p in c.P["土层"]:
                bot = -depth * 1000.0
                pts = b.layer_polygon_pts(c, top, bot)
                self.assertGreaterEqual(len(pts), 4,
                                        "%s 的土层多边形点太少：%s" % (name, pts))
                for p, q in zip(pts, pts[1:]):
                    self.assertNotEqual(p, q, "%s 多边形有重复点" % name)
                top = bot

    def test_slope_profile_is_multi_step(self):
        """放坡土钉的轮廓必须跟着台阶走，不能退化成单坡+竖壁。"""
        c = self._ctx("EF段")
        breaks = c.profile_breaks()
        self.assertGreater(len(breaks), 2,
                           "多级放坡应有多个转折点，得到 %s" % breaks)
        xs = [c.profile_x(c.Y_TOP - d) for d in (100, 1000, 2500, 4000)]
        self.assertEqual(xs, sorted(xs), "越往下轮廓的 x 应越大")

    def test_slope_layers_follow_steps(self):
        from cadkit.sections import base as b
        c = self._ctx("EF段")
        top = c.Y_TOP
        for _no, _n, depth, _cc, _p in c.P["土层"]:
            bot = -depth * 1000.0
            pts = b.layer_polygon_pts(c, top, bot)
            self.assertGreaterEqual(len(pts), 4)
            top = bot

    def test_double_pile_spacing_positive(self):
        c = self._ctx("GH段")
        self.assertGreater(c.P["桩排间距"], 0)
        self.assertGreater(c.P["桩长"], -c.Y_BOT / 1000.0,
                           "双排桩的桩长应大于开挖深度（要嵌固）")


class TestTemplateLookup(unittest.TestCase):
    """找不到模板时要给出**可照做**的提示。

    这里守的是一个真实 bug：find_template 里留了一行多余的
    `from . import cad`（cadkit 里根本没有这个模块），于是「找不到模板」
    这条分支直接抛 ImportError，用户看到的是
    `cannot import name 'cad' from 'cadkit'` —— 完全不知所云。
    """

    def test_missing_template_raises_template_error(self):
        from unittest import mock

        from cadkit import draw
        with mock.patch.object(draw.paths, "install_dir",
                               return_value=r"C:\no_such_dir_xyz"), \
             mock.patch.object(draw.config, "load",
                               return_value={"template_dwg": ""}):
            with self.assertRaises(draw.TemplateError) as cm:
                draw.find_template()
        msg = str(cm.exception)
        self.assertIn("template_dwg", msg, "提示里要写清怎么配置")
        self.assertIn("--template-dwg", msg, "提示里要给命令行用法")

    def test_explicit_template_wins(self):
        import tempfile
        from cadkit import draw
        fd, p = tempfile.mkstemp(suffix=".dwg")
        os.close(fd)
        try:
            self.assertEqual(draw.find_template(p), os.path.abspath(p))
        finally:
            os.remove(p)

    def test_builtin_cases_are_drawable(self):
        """每个内置工点的类型都要有对应的绘图程序，不能是空壳。"""
        from cadkit import draw, sections
        main_t, _addon = sections.supported()
        for name, case in draw.CASES.items():
            self.assertIn(case["类型"], main_t,
                          "%s 的类型 %s 没有绘图程序" % (name, case["类型"]))
            for k in ("名称", "图名", "土层", "坡顶标高", "基底标高", "正负零标高"):
                self.assertIn(k, case, "%s 少了必需参数 %s" % (name, k))


if __name__ == "__main__":
    unittest.main(verbosity=2)
