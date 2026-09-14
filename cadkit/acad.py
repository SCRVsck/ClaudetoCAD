# -*- coding: utf-8 -*-
"""AutoCAD 探测 · 连接 · 自动拉起。

原型的做法是硬编码 ``AutoCAD.Application.24.1``（即 2022），换台机器就废。
这里改成三级探测，逐级降级：

1. 已在运行的实例（``GetActiveObject``，最快的路径，也不打扰用户）；
2. 本机注册表里**已注册**的 ProgID，按版本从新到旧取第一个；
3. 从注册表的 ``LocalServer32`` 反查出 ``acad.exe`` 路径，主动拉起。

拉起用 ``acad.exe /Automation`` 而不是 ``Dispatch``：``Dispatch`` 会一直阻塞到
CAD 完全就绪，超时不可控；自己 Popen 则能设定上限、能提前反馈进度。
"""

import os
import subprocess
import time

try:
    import pythoncom
    import win32com.client
    from win32com.client import dynamic
    HAVE_PYWIN32 = True
except ImportError:  # pragma: no cover - 非 Windows 或缺依赖
    pythoncom = None
    win32com = None
    dynamic = None
    HAVE_PYWIN32 = False


class AcadError(RuntimeError):
    """探测 / 连接 AutoCAD 失败，message 面向最终用户。"""


# ProgID 次版本号 = AutoCAD 的 release 代号，从新到旧。
# 最后一项是「版本无关」的兜底 ProgID —— 它在不同机器上可能指向不同年份，
# 所以标成"版本无关"而不是硬写年份，并且排在最末（有具体版本就优先用具体的）。
PROGIDS = [
    ("AutoCAD.Application.25.1", "2026"),
    ("AutoCAD.Application.25.0", "2025"),
    ("AutoCAD.Application.24.3", "2024"),
    ("AutoCAD.Application.24.2", "2023"),
    ("AutoCAD.Application.24.1", "2022"),
    ("AutoCAD.Application.24.0", "2021"),
    ("AutoCAD.Application.23.1", "2020"),
    ("AutoCAD.Application.23.0", "2019"),
    ("AutoCAD.Application.22.0", "2018"),
    ("AutoCAD.Application.24", "版本无关"),
]

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


def _hkey_root():
    return winreg.HKEY_CLASSES_ROOT if winreg else None


def registered_progids():
    """本机 HKCR 里已注册的 AutoCAD ProgID，按 PROGIDS 的顺序（新→旧）。

    返回 ``[(progid, 年份), ...]``。注册表不可读时返回空列表。
    """
    if winreg is None:
        return []
    out = []
    for progid, ver in PROGIDS:
        try:
            k = winreg.OpenKey(_hkey_root(), progid)
            winreg.CloseKey(k)
            out.append((progid, ver))
        except OSError:
            continue
    return out


def _split_server_path(raw):
    """从 LocalServer32 的值里切出 exe 路径。

    值的形态不统一，实测本机是**不加引号**且路径带空格：
        D:\\Programs\\cad22\\AutoCAD 2022\\acad.exe /Automation
    所以不能简单地按空格切第一段 —— 那会得到不存在的
    ``D:\\Programs\\cad22\\AutoCAD``。按优先级尝试：

    1. 有引号 -> 取引号内；
    2. 找到 ``.exe`` 结尾并确认该文件存在；
    3. 退化成按空格切第一段。
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    if raw.startswith('"'):
        end = raw.find('"', 1)
        if end > 0:
            return raw[1:end]

    low = raw.lower()
    idx = low.find(".exe")
    if idx >= 0:
        cand = raw[:idx + 4].strip()
        if os.path.exists(cand):
            return cand

    return raw.split(" ")[0]


def exe_for_progid(progid):
    """从注册表反查该 ProgID 对应的 acad.exe 路径；查不到返回 None。"""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(_hkey_root(), progid + r"\CLSID") as k:
            clsid = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(_hkey_root(), r"CLSID\%s\LocalServer32" % clsid) as k:
            raw = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None

    path = _split_server_path(raw)
    return path if path and os.path.exists(path) else None


def running_instance(progid=None):
    """找正在运行的 AutoCAD。返回 ``(app, progid, 年份)``，没有则 ``(None, None, None)``。

    指定 progid 时只试它；否则按 PROGIDS 顺序试（含已注册才试，减少无谓异常）。
    """
    if not HAVE_PYWIN32:
        return None, None, None

    if progid:
        candidates = [(progid, dict(PROGIDS).get(progid, "?"))]
    else:
        seen = registered_progids()
        rest = [(p, v) for p, v in PROGIDS if (p, v) not in seen]
        candidates = seen + rest

    for pid, ver in candidates:
        try:
            app = win32com.client.GetActiveObject(pid)
            if app is not None:
                return app, pid, ver
        except Exception:
            continue
    return None, None, None


def _wait_for_document(app, timeout):
    """等 AutoCAD 把文档准备好 —— 刚拉起时它还在加载，Documents 会短暂不可用。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            if app.Documents.Count == 0:
                app.Documents.Add()
            doc = app.ActiveDocument
            if doc is not None:
                return doc
        except Exception as e:
            last = e
        time.sleep(0.15)
    raise AcadError("AutoCAD 已启动，但 %d 秒内没能取得文档（可能卡在启动对话框或许可界面）。"
                    "请手动打开 AutoCAD 看一眼。%s" % (timeout, ("最后错误：%s" % last) if last else ""))


def connect(progid=None, autostart=True, timeout=None, log=None):
    """连接 AutoCAD，必要时拉起。返回 ``(app, doc, info)``。

    ``info`` = ``{"progid", "version", "mode": "attached"|"launched", "exe"}``
    """
    from . import config
    cfg = config.load()
    timeout = float(timeout if timeout is not None else cfg["cad_launch_timeout"])
    progid = progid or cfg.get("progid")
    log = log or (lambda m: None)

    if not HAVE_PYWIN32:
        raise AcadError("缺少 pywin32。请先安装：pip install pywin32")

    # --- 1) 已在运行？----------------------------------------------------
    app, pid, ver = running_instance(progid)
    if app is not None:
        log("已连接到运行中的 AutoCAD（%s）" % pid)
        app.Visible = True
        doc = _wait_for_document(app, timeout)
        return app, doc, {"progid": pid, "version": ver,
                          "mode": "attached", "exe": exe_for_progid(pid)}

    if not autostart:
        raise AcadError("没有运行中的 AutoCAD，且配置里禁用了自动启动"
                        "（autostart_cad=false）。")

    # --- 2) 挑一个本机装了的版本 ----------------------------------------
    reg = registered_progids()
    if progid:
        target = (progid, dict(PROGIDS).get(progid, "?"))
    elif reg:
        target = reg[0]
    else:
        raise AcadError("本机没有检测到任何 AutoCAD（注册表里找不到 AutoCAD.Application.*）。"
                        "请先安装 AutoCAD。")

    tgt_progid, tgt_ver = target
    exe = exe_for_progid(tgt_progid) or exe_for_progid("AutoCAD.Application.24")

    # --- 3) 拉起 ---------------------------------------------------------
    if exe:
        log("正在启动 AutoCAD %s：%s" % (tgt_ver, exe))
        try:
            # /Automation 让 CAD 以可自动化模式启动；不阻塞，随后轮询。
            subprocess.Popen([exe, "/Automation"],
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError as e:
            raise AcadError("启动 AutoCAD 失败（%s）：%s" % (exe, e))
        app = _wait_for_instance(tgt_progid, timeout)
    else:
        log("注册表里没解析出 acad.exe，改用 COM Dispatch 启动 AutoCAD %s" % tgt_ver)
        try:
            app = win32com.client.Dispatch(tgt_progid)
        except Exception as e:
            raise AcadError("通过 COM 启动 AutoCAD 失败：%s。"
                            "请确认 AutoCAD 已正确安装。" % e)

    log("AutoCAD %s 就绪" % tgt_ver)
    try:
        app.Visible = True
    except Exception:
        pass
    doc = _wait_for_document(app, timeout)
    return app, doc, {"progid": tgt_progid, "version": tgt_ver,
                      "mode": "launched", "exe": exe}


def _wait_for_instance(progid, timeout):
    """拉起之后轮询，等 COM 对象出现。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            app = win32com.client.GetActiveObject(progid)
            if app is not None:
                return app
        except Exception:
            pass
        time.sleep(0.4)
    raise AcadError("等了 %d 秒，AutoCAD 还没注册成 COM 对象。"
                    "可能是启动被对话框挡住、或需要登录 Autodesk 账号。" % timeout)


def healthy(app, doc):
    """一次极轻量的健康探测：CAD 还活着吗？

    比 ping 更实在 —— 真的去碰一下 COM 对象。
    """
    try:
        _ = app.Version
        _ = doc.Name
        return True, None
    except Exception as e:
        return False, e
