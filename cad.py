#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CAD 桥接客户端 (cad.py)
=======================
用法：
  python cad.py '{"cmd":"ping"}'
  python cad.py '{"cmd":"add_line","start":[0,0,0],"end":[10,10,0]}'
  python cad.py count                     # 简写：裸词 -> {"cmd":"<词>"}
  python cad.py events [N]                # 读取最近 N 条事件（默认 20）
  python cad.py state                     # 查看运行状态

通过 state.json 找到桥接进程端口，建立本地 TCP 连接，发送一行 JSON 指令，
打印返回的一行 JSON。
"""

import os
import sys
import json
import socket

# Windows 下 argv 默认按 ANSI 代码页解码，中文会被破坏。
# 用宽字符版 CommandLineToArgvW 重新取回正确的 Unicode argv。
if sys.platform == "win32":
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32
        _k32.GetCommandLineW.restype = ctypes.c_wchar_p
        _nArgs = ctypes.c_int()
        _fn = ctypes.windll.shell32.CommandLineToArgvW
        _fn.restype = ctypes.POINTER(ctypes.c_wchar_p)
        _fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        _raw = _fn(_k32.GetCommandLineW(), ctypes.byref(_nArgs))
        # CommandLineToArgvW 的第 0 项是 python.exe，第 1 项才是脚本名；
        # Python 的 sys.argv[0] 应为脚本名，故从第 1 项起取。
        sys.argv = [_raw[i] for i in range(1, _nArgs.value)]
    except Exception:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE, "state.json")


def _state():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def send(obj):
    st = _state()
    s = socket.create_connection(("127.0.0.1", st["port"]), timeout=120)
    s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf.decode("utf-8", "replace").strip() or "{}")


def main():
    argv = sys.argv[1:]
    if not argv:
        print(json.dumps({"error": "usage: cad.py '<json>' | <word> | events [N] | state"},
                         ensure_ascii=False))
        return

    arg = argv[0]

    if arg == "state":
        print(json.dumps(_state(), ensure_ascii=False, indent=2))
        return

    if arg == "events":
        n = int(argv[1]) if len(argv) > 1 else 20
        path = _state().get("events_path")
        if not path or not os.path.exists(path):
            print(json.dumps({"events": []}, ensure_ascii=False))
            return
        lines = open(path, "r", encoding="utf-8").read().splitlines()
        out = [json.loads(l) for l in lines[-n:]]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # 指令
    if arg.startswith("{"):
        obj = json.loads(arg)
    else:
        obj = {"cmd": arg}

    resp = send(obj)
    print(json.dumps(resp, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
