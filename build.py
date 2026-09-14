#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键打包：把 CadBridge 冻成单文件 exe。

    python build.py            # 打包
    python build.py --clean    # 先清掉上次的产物再打
"""

import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist")
BUILD = os.path.join(BASE, "build")
EXE = os.path.join(DIST, "cadbridge.exe")


def clean():
    for d in (DIST, BUILD):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            print("已清理 %s" % d)
    for d in ("__pycache__", os.path.join("cadkit", "__pycache__")):
        p = os.path.join(BASE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        pass
    print("未安装 PyInstaller，正在安装…")
    r = subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    return r == 0


def build():
    if not ensure_pyinstaller():
        print("PyInstaller 安装失败，请手动：pip install pyinstaller")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "cadbridge.spec", "--noconfirm"]
    print("运行：%s" % " ".join(cmd))
    r = subprocess.call(cmd, cwd=BASE)
    if r != 0:
        print("打包失败（退出码 %d）" % r)
        return r

    if not os.path.exists(EXE):
        print("打包流程结束，但没找到 %s" % EXE)
        return 1

    size = os.path.getsize(EXE) / 1024.0 / 1024.0
    print("\n打包完成：%s（%.1f MB）" % (EXE, size))
    print("自检：%s doctor --deep" % EXE)
    return 0


def main():
    if "--clean" in sys.argv:
        clean()
    return build()


if __name__ == "__main__":
    sys.exit(main())
