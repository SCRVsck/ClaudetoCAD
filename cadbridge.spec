# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 产出两个 exe，共用同一套 cadkit：

    cadbridge.exe       控制台程序，CLI（体积优先：排除 tkinter）
    cadbridge-gui.exe   窗口程序，图形控制台（双击即用，无多余控制台窗口）

为什么要分成两个而不是一个：
  做成一个的话，要么 GUI 用户看到多余的黑窗口，要么 CLI 用户白背几 MB 的
  tkinter。分开最干净，代价只是分析跑两遍。

构建：
    python build.py
"""

import os

block_cipher = None

PATHEX = [os.path.abspath(os.getcwd())]

# win32com 家族大量使用运行时动态导入，静态分析追不到，必须显式列出
HIDDEN = [
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32com",
    "win32com.client",
    "win32com.client.dynamic",
    "win32com.client.gencache",
    "win32timezone",
    "win32com.shell",
]

# 被 import 到但用不上的重量级库，排掉能明显缩小体积
COMMON_EXCLUDES = [
    "unittest", "pydoc", "doctest", "email", "http", "xml", "xmlrpc",
    "pdb", "difflib", "lib2to3", "distutils", "setuptools", "pip",
    "numpy", "PIL", "matplotlib", "pytest",
]

# CLI 用不到 tkinter，单独排掉
CLI_EXCLUDES = COMMON_EXCLUDES + ["tkinter", "_tkinter", "turtle"]

ICON = "assets/cadbridge.ico" if os.path.exists("assets/cadbridge.ico") else None
VERSION = "version_info.txt" if os.path.exists("version_info.txt") else None


def _exe(entry, name, excludes, console, version_file=None):
    a = Analysis(
        [entry],
        pathex=PATHEX,
        binaries=[],
        datas=[],
        hiddenimports=HIDDEN,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=excludes,
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    return EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,          # AutoCAD COM 进程注入对 UPX 压缩壳敏感，不开
        upx_exclude=[],
        runtime_tmpdir=None,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON,
        version=version_file,
    )


# CLI：控制台程序
exe = _exe("cadbridge.py", "cadbridge", CLI_EXCLUDES, console=True,
           version_file=VERSION)

# GUI：窗口程序，保留 tkinter
exe_gui = _exe("cadbridge_gui.py", "cadbridge-gui", COMMON_EXCLUDES, console=False,
               version_file=VERSION)
