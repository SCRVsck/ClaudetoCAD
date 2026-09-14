# -*- coding: utf-8 -*-
"""``cadbridge doctor`` —— 一次跑完所有自检，直接告诉你缺什么。

产品化最值钱的一个命令：用户遇到问题不该去读故障排查表，
而应该跑一条命令拿到「哪一环断了 + 怎么修」。
"""

import os
import sys

from . import acad, config, paths, protocol

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_MARK = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, title, detail=""):
        self.items.append((level, title, detail))

    @property
    def worst(self):
        if any(l == FAIL for l, _, _ in self.items):
            return FAIL
        if any(l == WARN for l, _, _ in self.items):
            return WARN
        return OK

    def render(self, color=True):
        lines = []
        for level, title, detail in self.items:
            lines.append("%s %s" % (_MARK[level], title))
            if detail:
                for d in str(detail).splitlines():
                    lines.append("       %s" % d)
        return "\n".join(lines)


def _check_python(rep):
    rep.add(OK, "Python %s" % sys.version.split()[0],
            "打包运行：%s" % ("是" if paths.is_frozen() else "否（源码模式）"))


def _check_pywin32(rep):
    if acad.HAVE_PYWIN32:
        try:
            import win32api
            rep.add(OK, "pywin32 可用", "build %s" % win32api.GetVersionEx()[0])
        except Exception:
            rep.add(OK, "pywin32 可用")
    else:
        rep.add(FAIL, "缺少 pywin32", "修复：pip install pywin32")


def _check_dirs(rep):
    d = paths.data_dir()
    try:
        probe = os.path.join(d, ".writetest")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        rep.add(OK, "数据目录可写", d)
    except Exception as e:
        rep.add(FAIL, "数据目录不可写", "%s\n%s" % (d, e))


def _check_autocad_installed(rep):
    reg = acad.registered_progids()
    if not reg:
        rep.add(FAIL, "未检测到本机安装的 AutoCAD",
                "注册表里没有 AutoCAD.Application.* 项。\n"
                "修复：安装 AutoCAD，或确认安装未损坏。")
        return None
    names = ", ".join("%s(%s)" % (p, v) for p, v in reg)
    rep.add(OK, "AutoCAD 已注册（%d 个版本）" % len(reg), names)
    return reg[0]


def _check_exe(rep, progid):
    if not progid:
        return
    exe = acad.exe_for_progid(progid[0])
    if exe:
        rep.add(OK, "acad.exe 可定位", "%s\n（%s）" % (exe, progid[0]))
    else:
        rep.add(WARN, "没能从注册表定位 acad.exe",
                "会自动改用 COM Dispatch 启动，通常也能用；\n"
                "若启动失败，请手动打开一次 AutoCAD 再重试。")


def _check_running(rep):
    app, pid, ver = acad.running_instance()
    if app is not None:
        rep.add(OK, "AutoCAD 正在运行", "%s（%s）" % (pid, ver))
        return True
    rep.add(WARN, "AutoCAD 当前没在运行", "桥接启动时会自动拉起它。")
    return False


def _check_bridge(rep):
    st = protocol.live_state()
    if st:
        rep.add(OK, "桥接正在运行",
                "端口 %s · PID %s · AutoCAD %s" % (st.get("port"), st.get("pid"),
                                                   st.get("acad_version")))
        return True
    stale = protocol.read_state()
    if stale:
        rep.add(WARN, "桥接未运行，但残留了 state.json",
                "端口 %s 已无响应（上次是 PID %s，可能异常退出）。\n"
                "下次调用会自动重新拉起。" % (stale.get("port"), stale.get("pid")))
    else:
        rep.add(WARN, "桥接未运行", "首次调用时会自动拉起。")
    return False


def _check_roundtrip(rep, deep):
    """真画一条线再删掉 —— 端到端验证 COM 写权限。"""
    if not deep:
        return
    from . import protocol as P
    try:
        r = P.request({"cmd": "add_line", "start": [0, 0, 0], "end": [1, 1, 0]},
                      timeout=120)
        if not r.get("ok"):
            rep.add(FAIL, "写入测试失败", str(r.get("error")))
            return
        h = r.get("handle")
        P.request({"cmd": "erase", "handles": [h]}, timeout=60)
        rep.add(OK, "端到端写入测试通过", "已画线并删除（句柄 %s）" % h)
    except Exception as e:
        rep.add(FAIL, "端到端写入测试失败", str(e))


def _check_cjk(rep, deep):
    """中文字体是否可用。"""
    if not deep:
        return
    from . import protocol as P
    try:
        r = P.request({"cmd": "textstyle", "name": "CadBridgeCheck",
                       "font": "SimHei"}, timeout=60)
        if r.get("ok"):
            rep.add(OK, "中文字体样式可用", "字体文件：%s" % r.get("font"))
        else:
            rep.add(WARN, "中文字体样式创建失败",
                    "%s\n中文可能显示成 ?。修复：安装黑体（SimHei）。" % r.get("error"))
    except Exception as e:
        rep.add(WARN, "中文字体检查跳过", str(e))


def run(deep=False, verbose=False):
    rep = Report()
    _check_python(rep)
    _check_pywin32(rep)
    _check_dirs(rep)
    progid = _check_autocad_installed(rep)
    _check_exe(rep, progid)

    # 深度检查放在「运行状态」之前：它会把桥接和 AutoCAD 拉起来，
    # 之后再汇报状态才不会是自相矛盾的旧快照。
    if deep:
        _check_roundtrip(rep, True)
        _check_cjk(rep, True)

    _check_running(rep)
    _check_bridge(rep)

    if not deep:
        rep.add(WARN, "深度检查未运行", "加 --deep 会真画一条线来端到端验证。")
    return rep
