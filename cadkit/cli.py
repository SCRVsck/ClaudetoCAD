# -*- coding: utf-8 -*-
"""命令行入口 —— 用户实际接触的那一层。

设计目标：**不需要读文档就能用**。

    cadbridge doctor            我现在到底缺什么？
    cadbridge info              连上了吗？什么版本？
    cadbridge line 0,0 100,100  画条线
    cadbridge "{\\"cmd\\":\\"count\\"}"   原样透传任意 JSON 指令

底层指令仍然是 JSON（向后兼容、也给脚本用），但常用操作有短命令。
"""

import argparse
import json
import os
import sys

from . import __version__, config, daemon, doctor, paths, protocol
from . import acad as _acad


# --------------------------------------------------------------- argv 修复
def _fix_argv():
    """Windows 下 argv 默认按 ANSI 代码页解码，中文会被破坏。

    用宽字符版 CommandLineToArgvW 重新取回正确的 Unicode argv。

    注意起点不同：源码模式命令行是 ``python.exe 脚本.py 参数…``（三段起），
    冻结成 exe 后是 ``cadbridge.exe 参数…``（两段起，**没有脚本名**）。
    写死从 1 开始取会让打包版把第一个参数当成脚本名丢掉，
    结果所有子命令都退化成打印帮助。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCommandLineW.restype = ctypes.c_wchar_p
        n = ctypes.c_int()
        fn = ctypes.windll.shell32.CommandLineToArgvW
        fn.restype = ctypes.POINTER(ctypes.c_wchar_p)
        fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        raw = fn(k32.GetCommandLineW(), ctypes.byref(n))
        start = 0 if getattr(sys, "frozen", False) else 1
        sys.argv = [raw[i] for i in range(start, n.value)]
    except Exception:
        pass


def _setup_io():
    """把标准输出/错误固定成 UTF-8。

    中文在管道或重定向输出时会按系统 ANSI 代码页（简体中文是 cp936）编码，
    下游按 UTF-8 读就是乱码。控制台本就跑在 UTF-8 上，改这个不会影响它。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ------------------------------------------------------------------ 输出
def _out(obj, as_json=False):
    """打印响应。默认给人看；--json 给脚本看。"""
    if as_json:
        print(json.dumps(obj, ensure_ascii=False))
        return
    if isinstance(obj, dict) and obj.get("ok") is False:
        _err(obj.get("error", "未知错误"))
        return
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _err(msg):
    sys.stderr.write("错误：%s\n" % msg)


def _pt(s):
    """解析 "x,y" 或 "x,y,z" 或 "x y"。"""
    for sep in (",", " "):
        if sep in s:
            parts = [p for p in s.split(sep) if p.strip()]
            break
    else:
        parts = [s]
    vals = [float(p) for p in parts]
    while len(vals) < 3:
        vals.append(0.0)
    return vals[:3]


# ------------------------------------------------------------------ 命令
def cmd_serve(args):
    from . import server
    return server.BridgeServer().serve_forever()


def cmd_gui(args):
    try:
        from . import gui
    except ImportError as e:
        _err("图形界面不可用：%s\n（打包版请用 cadbridge-gui.exe；"
             "源码运行需要 Python 带 tkinter）" % e)
        return 1
    return gui.run()


def cmd_draw(args):
    """按工程图标准出图。

    以前这一步只能跑根目录的 `draw_section.py` —— 那是个独立脚本，
    打包进 exe 的只有 cadkit，所以装了软件的人**根本调不到绘图功能**。
    现在实现搬进了 cadkit.draw，CLI 和脚本共用同一份。
    """
    from . import draw
    if args.list:
        return draw.run(draw.CASES, list_only=True)
    case = None
    if not (args.rtf or args.dir):
        name = args.case or "CD段"
        if name not in draw.CASES:
            _err("未知工点 %r，可选：%s\n（用 `cadbridge draw --list` 看全部类型）"
                 % (name, "、".join(draw.CASES)))
            return 2
        case = draw.CASES[name]
    return draw.run(case, rtf=args.rtf, folder=args.dir,
                    template=args.template_dwg, outdir=args.out)


def cmd_doctor(args):
    rep = doctor.run(deep=args.deep)
    print("CadBridge 自检 · v%s" % __version__)
    print("=" * 60)
    print(rep.render())
    print("=" * 60)
    if rep.worst == doctor.FAIL:
        print("结果：有致命问题，见上面的 [FAIL] 项。")
        return 1
    if rep.worst == doctor.WARN:
        print("结果：可用，但有需要注意的地方（[WARN]）。")
        return 0
    print("结果：一切正常。")
    return 0


def cmd_start(args):
    st = daemon.ensure_running()
    print("桥接已就绪：端口 %s · PID %s · AutoCAD %s"
          % (st.get("port"), st.get("pid"), st.get("acad_version")))
    return 0


def cmd_stop(args):
    print("桥接已停止。" if daemon.stop() else "桥接本来就没在运行。")
    return 0


def cmd_status(args):
    st = protocol.live_state()
    if not st:
        stale = protocol.read_state()
        if stale:
            print("桥接未运行（残留 state.json：端口 %s，PID %s）"
                  % (stale.get("port"), stale.get("pid")))
        else:
            print("桥接未运行。")
        return 1
    if args.json:
        _out(st, as_json=True)
    else:
        print("桥接运行中")
        for k in ("port", "pid", "mode", "progid", "acad_version", "data_dir"):
            if k in st:
                print("  %-14s %s" % (k, st[k]))
    return 0


def cmd_config(args):
    if args.key is None:
        cfg = config.load()
        if args.json:
            _out(cfg, as_json=True)
        else:
            print("配置文件：%s" % paths.config_path())
            for k in sorted(cfg):
                print("  %-18s %s" % (k, json.dumps(cfg[k], ensure_ascii=False)))
        return 0
    if args.value is None:
        print(json.dumps(config.load().get(args.key), ensure_ascii=False))
        return 0
    raw = args.value
    try:
        val = json.loads(raw)
    except ValueError:
        val = raw
    try:
        config.set(args.key, val)
    except KeyError as e:
        _err(str(e))
        return 2
    print("%s = %s" % (args.key, json.dumps(val, ensure_ascii=False)))
    return 0


def cmd_raw(args):
    """原样透传 JSON 指令（向后兼容 cad.py 的用法）。"""
    arg = args.payload
    if arg.startswith("{"):
        try:
            obj = json.loads(arg)
        except ValueError as e:
            _err("JSON 解析失败：%s" % e)
            return 2
    else:
        obj = {"cmd": arg}
    try:
        _out(protocol.request(obj), as_json=args.json)
    except protocol.BridgeError as e:
        _err(str(e))
        return 1
    return 0


# --- 常用操作的短命令（免去手写 JSON）-----------------------------------
def _simple(obj, args):
    try:
        r = protocol.request(obj)
    except protocol.BridgeError as e:
        _err(str(e))
        return 1
    _out(r, as_json=args.json)
    return 0 if r.get("ok") else 1


def cmd_line(args):
    return _simple({"cmd": "add_line", "start": _pt(args.start),
                    "end": _pt(args.end)}, args)


def cmd_circle(args):
    return _simple({"cmd": "add_circle", "center": _pt(args.center),
                    "radius": args.radius}, args)


def cmd_text(args):
    return _simple({"cmd": "add_text", "text": args.text,
                    "insert": _pt(args.at), "height": args.height}, args)


def cmd_count(args):
    return _simple({"cmd": "count"}, args)


def cmd_info(args):
    return _simple({"cmd": "info"}, args)


def cmd_zoom(args):
    obj = {"cmd": "zoom", "mode": args.mode}
    if args.mode == "center":
        obj["center"] = _pt(args.center)
        obj["height"] = args.height
    return _simple(obj, args)


def cmd_textstyle(args):
    return _simple({"cmd": "textstyle", "name": args.name, "font": args.font}, args)


def cmd_save(args):
    return _simple({"cmd": "save", "path": os.path.abspath(args.path)}, args)


def cmd_entities(args):
    return _simple({"cmd": "entities", "limit": args.limit}, args)


def cmd_changes(args):
    return _simple({"cmd": "changes"}, args)


# ------------------------------------------------------------------ 解析
def build_parser():
    p = argparse.ArgumentParser(
        prog="cadbridge",
        description="AutoCAD 双向实时桥接 —— 通过 COM 直接驱动本机 AutoCAD。",
        epilog="不知道从哪开始？跑 `cadbridge doctor`。",
    )
    p.add_argument("--version", action="version", version="CadBridge %s" % __version__)
    p.add_argument("--json", action="store_true", help="以 JSON 输出（供脚本解析）")
    sub = p.add_subparsers(dest="cmd", metavar="<命令>")

    sp = sub.add_parser("doctor", help="自检：我现在缺什么？")
    sp.add_argument("--deep", action="store_true", help="真画一条线做端到端验证")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("gui", help="打开图形控制台")
    sp.set_defaults(func=cmd_gui)

    sp = sub.add_parser("draw", help="按工程图标准出图（基坑支护剖面）")
    sp.add_argument("case", nargs="?",
                    help="内置工点，如 CD段(悬臂桩) / EF段(放坡土钉) / GH段(双排桩)")
    sp.add_argument("--rtf", help="计算书 RTF：解析参数并出图")
    sp.add_argument("--dir", help="批量：一个目录里的所有 .rtf 出一册图")
    sp.add_argument("--template-dwg", dest="template_dwg",
                    help="标准模板 DWG（承载图框块/图层/文字样式）")
    sp.add_argument("--out", help="出图的落盘目录")
    sp.add_argument("--list", action="store_true", help="列出可用的类型与工点")
    sp.set_defaults(func=cmd_draw)

    sp = sub.add_parser("info", help="桥接与 AutoCAD 状态")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("start", help="启动桥接（会自动拉起 AutoCAD）")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="停止桥接（AutoCAD 保留）")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="桥接是否在运行")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("config", help="查看/修改配置")
    sp.add_argument("key", nargs="?", help="配置项名")
    sp.add_argument("value", nargs="?", help="新值（JSON 或字符串）")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("line", help="画直线")
    sp.add_argument("start", help="起点 x,y[,z]")
    sp.add_argument("end", help="终点 x,y[,z]")
    sp.set_defaults(func=cmd_line)

    sp = sub.add_parser("circle", help="画圆")
    sp.add_argument("center", help="圆心 x,y[,z]")
    sp.add_argument("radius", type=float)
    sp.set_defaults(func=cmd_circle)

    sp = sub.add_parser("text", help="写文字（支持中文）")
    sp.add_argument("text")
    sp.add_argument("--at", default="0,0", help="插入点 x,y[,z]")
    sp.add_argument("--height", type=float, default=2.5)
    sp.set_defaults(func=cmd_text)

    sp = sub.add_parser("count", help="模型空间实体数")
    sp.set_defaults(func=cmd_count)

    sp = sub.add_parser("entities", help="枚举实体")
    sp.add_argument("--limit", type=int, default=200)
    sp.set_defaults(func=cmd_entities)

    sp = sub.add_parser("changes", help="变更签名（两次比对可知图形是否被改）")
    sp.set_defaults(func=cmd_changes)

    sp = sub.add_parser("zoom", help="缩放视图")
    sp.add_argument("mode", nargs="?", default="extents",
                    choices=["extents", "all", "center"])
    sp.add_argument("--center", default="0,0,0")
    sp.add_argument("--height", type=float, default=200.0)
    sp.set_defaults(func=cmd_zoom)

    sp = sub.add_parser("textstyle", help="建/改文字样式（中文用 SimHei）")
    sp.add_argument("--name", default="CadBridge")
    sp.add_argument("--font", default="SimHei")
    sp.set_defaults(func=cmd_textstyle)

    sp = sub.add_parser("save", help="另存为 DWG")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_save)

    sp = sub.add_parser("raw", help="原样发送 JSON 指令（高级）")
    sp.add_argument("payload")
    sp.set_defaults(func=cmd_raw)

    # 隐藏的服务端入口（daemon.ensure_running 用 --serve 拉起自己）；
    # 在 main() 里于解析前拦截，这里不注册，免得 argparse 对 "-" 开头的名字犯迷糊
    p.set_defaults(_subcommands=set(sub.choices))

    return p


def main(argv=None):
    _setup_io()
    if argv is None:
        _fix_argv()
        argv = sys.argv[1:]

    # `cadbridge --serve` 由 daemon 内部拉起，不走常规解析
    if argv and argv[0] == "--serve":
        return cmd_serve(argparse.Namespace())

    parser = build_parser()

    # 裸 JSON / 裸词：兼容 `cadbridge '{"cmd":"count"}'` 和 `cadbridge count`
    subcommands = parser.get_default("_subcommands") or set()
    if argv and not argv[0].startswith("-") and argv[0] not in subcommands:
        ns = argparse.Namespace(payload=argv[0], json="--json" in argv)
        try:
            return cmd_raw(ns)
        except Exception as e:
            _err(str(e))
            return 1

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except protocol.BridgeError as e:
        _err(str(e))
        return 1
    except _acad.AcadError as e:
        _err(str(e))
        return 1
    except Exception as e:
        if os.environ.get("CADBRIDGE_DEBUG"):
            raise
        _err("%s\n（加环境变量 CADBRIDGE_DEBUG=1 看完整堆栈）" % e)
        return 1
