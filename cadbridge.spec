# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 产出单个 cadbridge.exe。

一个 exe 同时是客户端和服务端：前台跑命令是客户端，
被 daemon 以 ``--serve`` 拉起时是常驻桥接。

构建：
    python build.py
或直接：
    pyinstaller cadbridge.spec --noconfirm
"""

import os

block_cipher = None

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

a = Analysis(
    ["cadbridge.py"],
    pathex=[os.path.abspath(os.getcwd())],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 这些是被 import 但不常用的重量级库，排掉能显著缩小体积
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest", "email", "http",
        "xml", "xmlrpc", "pdb", "difflib", "lib2to3", "distutils",
        "setuptools", "pip", "numpy", "PIL", "matplotlib", "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="cadbridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # AutoCAD COM 进程注入对 UPX 压缩壳敏感，不开
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # CLI 工具，保留控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/cadbridge.ico" if os.path.exists("assets/cadbridge.ico") else None,
    version="version_info.txt" if os.path.exists("version_info.txt") else None,
)
