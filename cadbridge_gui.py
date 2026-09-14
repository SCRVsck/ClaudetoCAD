#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CadBridge 图形控制台入口（窗口程序，双击即用）。

命令行用法请用同目录的 cadbridge.exe；这个 exe 只为图形界面存在 ——
它是窗口子系统程序，不会弹出多余的控制台窗口。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # 这个 exe 也可能被 daemon 用 --serve 拉起来当桥接跑（只单独分发了
    # GUI 而没有 cadbridge.exe 的场景）。必须支持，否则桥接起不来。
    if "--serve" in sys.argv[1:]:
        from cadkit.server import BridgeServer
        return BridgeServer().serve_forever()

    try:
        from cadkit import gui
        return gui.run()
    except Exception:
        # 窗口程序没有控制台，出错必须弹窗，否则用户只看到「什么都没发生」
        import traceback
        msg = traceback.format_exc()
        try:
            import tkinter.messagebox as mb
            import tkinter as tk
            r = tk.Tk()
            r.withdraw()
            mb.showerror("CadBridge 启动失败", msg)
            r.destroy()
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, msg, "CadBridge 启动失败", 0x10)
            except Exception:
                sys.stderr.write(msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())
