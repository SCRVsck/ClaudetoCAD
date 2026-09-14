#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键构建 CadBridge。

    python build.py                 # 打包 exe（必要时先生成图标）
    python build.py --clean         # 先清理再打
    python build.py --portable      # 额外产出一个免安装 zip
    python build.py --installer     # 额外产出安装程序（需要 Inno Setup）
    python build.py --all           # 打包 + 便携包 + 安装程序
"""

import os
import shutil
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist")
BUILD = os.path.join(BASE, "build")
ICON = os.path.join(BASE, "assets", "cadbridge.ico")
EXE = os.path.join(DIST, "cadbridge.exe")
EXE_GUI = os.path.join(DIST, "cadbridge-gui.exe")
ISS = os.path.join(BASE, "installer", "cadbridge.iss")

DOCS = ["README.md", "使用指南.md", "LICENSE"]

# Inno Setup 可能会装在这两个位置
ISCC_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 "Inno Setup 6", "ISCC.exe"),
]


def version():
    sys.path.insert(0, BASE)
    from cadkit import __version__
    return __version__


def clean():
    for d in (DIST, BUILD):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            print("已清理 %s" % d)
    for d in ("__pycache__", os.path.join("cadkit", "__pycache__")):
        p = os.path.join(BASE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def ensure_icon():
    if os.path.exists(ICON):
        return True
    print("图标不存在，正在生成…")
    try:
        r = subprocess.call([sys.executable,
                             os.path.join(BASE, "assets", "make_icon.py")], cwd=BASE)
        return r == 0 and os.path.exists(ICON)
    except Exception as e:
        print("生成图标失败（%s），将不带图标打包。" % e)
        return False


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        pass
    print("未安装 PyInstaller，正在安装…")
    return subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"]) == 0


def build_exe():
    if not ensure_pyinstaller():
        print("PyInstaller 安装失败，请手动：pip install pyinstaller")
        return 1
    ensure_icon()

    cmd = [sys.executable, "-m", "PyInstaller", "cadbridge.spec", "--noconfirm"]
    print("运行：%s" % " ".join(cmd))
    r = subprocess.call(cmd, cwd=BASE)
    if r != 0:
        print("打包失败（退出码 %d）" % r)
        return r

    missing = [p for p in (EXE, EXE_GUI) if not os.path.exists(p)]
    if missing:
        print("打包流程结束，但缺少产物：%s" % ", ".join(missing))
        return 1

    for p in (EXE, EXE_GUI):
        print("打包完成：%s（%.1f MB）" % (p, os.path.getsize(p) / 1024.0 / 1024.0))
    return 0


# ---------------------------------------------------------------- 便携包
# PATH 的增删逻辑放在 .ps1 里，.cmd 只做转发。
# 早先把逻辑直接写在 .cmd 里，靠 %~dp0 + 多层引号 + chcp 拼 PowerShell 命令，
# 结果卸载时匹配不上（PATH 没被移除）。chcp 在批处理中途切代码页会让 cmd.exe
# 读错后续行，这类拼字符串的做法太脆，不值得修 —— 换掉。
_INSTALL_PS1 = r"""# 把 CadBridge 所在目录加入当前用户的 PATH（不碰系统 PATH，不需要管理员）
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot.TrimEnd('\')
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { $path = '' }

$parts = $path -split ';' | Where-Object { $_ }
if ($parts | Where-Object { $_.TrimEnd('\') -ieq $dir }) {
    Write-Host '该目录已在 PATH 中，跳过。'
} else {
    $new = (($parts + $dir) -join ';')
    [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    Write-Host "已加入 PATH：$dir"
}
Write-Host ''
Write-Host '完成。请重新打开一个命令行窗口，然后运行： cadbridge doctor'
"""

_UNINSTALL_PS1 = r"""# 从当前用户的 PATH 中移除 CadBridge 所在目录
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot.TrimEnd('\')
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { $path = '' }

$parts = $path -split ';' | Where-Object { $_ }
$kept = $parts | Where-Object { $_.TrimEnd('\') -ine $dir }
if ($kept.Count -eq $parts.Count) {
    Write-Host '该目录本来就不在 PATH 中，无需移除。'
} else {
    [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
    Write-Host "已从 PATH 移除：$dir"
}
Write-Host ''
Write-Host 'CadBridge 已从便携目录卸载；程序文件请直接删除本文件夹。'
"""

_CMD_WRAPPER = r"""@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0{script}"
if errorlevel 1 pause
"""


def build_portable():
    ver = version()
    out = os.path.join(DIST, "CadBridge-%s-portable.zip" % ver)
    stage = os.path.join(BUILD, "portable", "CadBridge-%s" % ver)
    if os.path.isdir(os.path.dirname(stage)):
        shutil.rmtree(os.path.dirname(stage), ignore_errors=True)
    os.makedirs(stage, exist_ok=True)

    shutil.copy2(EXE, os.path.join(stage, "cadbridge.exe"))
    shutil.copy2(EXE_GUI, os.path.join(stage, "cadbridge-gui.exe"))
    for name in DOCS:
        src = os.path.join(BASE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(stage, name))

    def w(name, content, encoding="utf-8"):
        with open(os.path.join(stage, name), "w", encoding=encoding,
                  newline="\r\n") as f:
            f.write(content)

    # 编码是这里的关键，两种脚本的要求正好相反：
    #   .ps1 —— Windows PowerShell 5.1 对无 BOM 的 UTF-8 会按 ANSI 解码，
    #           中文变乱码字节后直接把脚本解析搞崩（实测报 UnexpectedToken）。
    #           所以必须带 BOM。
    #   .cmd —— 反过来，带 BOM 的批处理首行会被 cmd.exe 误读，必须纯 ASCII 无 BOM。
    w("_path-install.ps1", _INSTALL_PS1, "utf-8-sig")
    w("_path-uninstall.ps1", _UNINSTALL_PS1, "utf-8-sig")
    w("安装.cmd", _CMD_WRAPPER.format(script="_path-install.ps1"), "ascii")
    w("卸载.cmd", _CMD_WRAPPER.format(script="_path-uninstall.ps1"), "ascii")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, os.path.dirname(stage)))
    print("便携包：%s（%.1f MB）" % (out, os.path.getsize(out) / 1024.0 / 1024.0))
    return 0


# -------------------------------------------------------------- 安装程序
def find_iscc():
    for p in ISCC_CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which("ISCC") or shutil.which("iscc")


def build_installer():
    iscc = find_iscc()
    if not iscc:
        print("\n未找到 Inno Setup 编译器（ISCC.exe），跳过安装程序。")
        print("安装后重试：https://jrsoftware.org/isdl.php")
        print("（或 winget install JRSoftware.InnoSetup）")
        return 1
    ver = version()
    cmd = [iscc, ISS, "/DMyAppVersion=%s" % ver]
    print("运行：%s" % " ".join(cmd))
    r = subprocess.call(cmd, cwd=BASE)
    if r != 0:
        print("安装程序编译失败（退出码 %d）" % r)
        return r
    print("\n安装程序已输出到 %s" % DIST)
    return 0


def main():
    args = sys.argv[1:]
    if "--clean" in args:
        clean()

    rc = build_exe()
    if rc != 0:
        return rc

    want_all = "--all" in args
    if want_all or "--portable" in args:
        rc = build_portable() or rc
    if want_all or "--installer" in args:
        build_installer()   # 缺 Inno Setup 只提示，不算失败
    return rc


if __name__ == "__main__":
    sys.exit(main())
