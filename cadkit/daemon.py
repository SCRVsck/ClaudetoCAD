# -*- coding: utf-8 -*-
"""桥接进程的启动 / 停止 / 单实例保证。

桥接是个常驻后台进程，产品化要求用户**不需要知道它的存在** ——
``ensure_running()`` 负责「没跑就悄悄拉起来，跑着就直接用」。
"""

import os
import subprocess
import sys
import time

from . import paths, protocol


def _spawn_cmd():
    """构造拉起桥接的命令行 —— 区分源码运行与 exe 运行。

    打包后有两个 exe（cadbridge.exe 控制台 / cadbridge-gui.exe 窗口），
    桥接必须由**控制台那个**来跑：从 GUI 里派生 ``sys.executable --serve``
    会得到 ``cadbridge-gui.exe --serve``，而 GUI 的 main 不解析参数、
    直接开窗口 —— 于是桥接没起来，反而弹出一堆窗口。
    """
    if paths.is_frozen():
        here = os.path.dirname(os.path.abspath(sys.executable))
        cli = os.path.join(here, "cadbridge.exe")
        if os.path.exists(cli):
            return [cli, "--serve"]
        # 只单独分发了 GUI exe 的情况：退回自己（cadbridge_gui.py 里
        # 也处理了 --serve，会转而跑桥接）
        return [sys.executable, "--serve"]
    return [sys.executable, os.path.join(paths.install_dir(), "cadbridge.py"), "--serve"]


def _clean_env():
    """去掉 PyInstaller 注入的环境变量再派生子进程。

    onefile 模式下引导器会把解包目录通过 ``_MEIPASS2`` 传给子进程，
    子进程看到它就不再自己解包，直接复用父进程的临时目录。这很危险：
    父进程退出时会去删那个目录，而桥接是**长期驻留**的 —— 目录一旦被删掉，
    正在运行的桥接立刻崩溃。实测报的就是
    ``Failed to remove temporary directory: ...\\_MEIxxxx``。

    清掉这些变量，让 daemon 走完整的自解包流程、用属于自己的目录。
    """
    env = os.environ.copy()
    for k in list(env):
        if k.startswith("_MEI") or k.startswith("_PYI_"):
            env.pop(k, None)
    return env


def is_running():
    return protocol.live_state() is not None


def ensure_running(timeout=180, log=None):
    """确保桥接在跑；已在跑就直接返回 state。"""
    log = log or (lambda m: None)
    st = protocol.live_state()
    if st:
        return st

    log("桥接未运行，正在启动…")
    try:
        subprocess.Popen(
            _spawn_cmd(),
            cwd=paths.install_dir(),
            env=_clean_env(),
            # 必须用 CREATE_NO_WINDOW，不能只用 DETACHED_PROCESS：
            # 从窗口子系统的 GUI exe 里派生控制台程序时，DETACHED_PROCESS
            # 拦不住 Windows 给子进程新建控制台，结果会冒出一个黑色终端窗口
            # 挂在旁边。CLI 场景看不出来（父进程本来就有控制台），
            # 只有打包成 cadbridge-gui.exe 后才暴露。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as e:
        raise protocol.BridgeError("启动桥接进程失败：%s" % e)

    deadline = time.time() + timeout
    while time.time() < deadline:
        st = protocol.live_state()
        if st:
            return st
        time.sleep(0.3)

    raise protocol.BridgeError(
        "桥接启动超时（%ds）。首次启动要拉起 AutoCAD，可能要 10~60 秒。\n"
        "看日志排查：%s" % (timeout, paths.log_path()))


def stop(timeout=10):
    """请桥接退出（AutoCAD 保留运行）。"""
    if not is_running():
        protocol.clear_state()
        return False
    try:
        protocol.send({"cmd": "shutdown"}, timeout=timeout)
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running():
            protocol.clear_state()
            return True
        time.sleep(0.2)
    return False


def quit_cad(timeout=30):
    """桥接退出，并关闭 AutoCAD。"""
    if is_running():
        try:
            protocol.send({"cmd": "quit"}, timeout=timeout)
        except Exception:
            pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running():
            protocol.clear_state()
            return True
        time.sleep(0.3)
    return False


class SingleInstance:
    """单实例守卫，确保同时只有一个桥接在跑。

    多开桥接 = 多路 COM 连接，会把 AutoCAD 卡进 ``RPC_E_CALL_REJECTED``，
    是这个项目里最贵的故障，必须挡住。

    实现用 Windows 命名互斥体（内核对象），而不是文件锁 —— 早先的文件锁版本
    在「锁定第 0 字节」之后又 ``truncate()`` 把文件截成 0 字节，
    等于把刚锁上的区域截没了，锁形同虚设（现场表现就是 lock 文件是空的）。
    互斥体还有个好处：进程无论怎么死，内核都会自动释放，不留残留锁。

    互斥体名由数据目录派生：默认目录下全局唯一，而设了 ``CADBRIDGE_HOME``
    的实例各锁各的 —— 隔离测试和多套并行环境都靠这个。
    """

    def __init__(self, path=None):
        self.path = path or paths.lock_path()
        self.handle = None
        self._fallback = None

    def _name(self):
        import hashlib
        h = hashlib.md5(paths.data_dir().lower().encode("utf-8")).hexdigest()[:16]
        return "Local\\CadBridge.SingleInstance.%s" % h

    def acquire(self):
        """拿到锁返回 True；已被别的进程持有返回 False。"""
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateMutexW.restype = wintypes.HANDLE
                k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                             wintypes.LPCWSTR]
                self.handle = k32.CreateMutexW(None, False, self._name())
                if not self.handle:
                    return True          # 建不出来就别拦着，宁可多跑
                # ERROR_ALREADY_EXISTS = 183
                if ctypes.get_last_error() == 183:
                    k32.CloseHandle(self.handle)
                    self.handle = None
                    return False
                self._write_pid()
                return True
            except Exception:
                return True
        return self._acquire_filelock()

    def _write_pid(self):
        """把 PID 写进 lock 文件，纯粹给人看（不承担加锁职责）。"""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass

    def _acquire_filelock(self):
        try:
            self._fallback = open(self.path, "a+")
            import fcntl
            fcntl.flock(self._fallback.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            if self._fallback:
                try:
                    self._fallback.close()
                except Exception:
                    pass
                self._fallback = None
            return False

    def release(self):
        if self.handle:
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
        if self._fallback:
            try:
                self._fallback.close()
            except Exception:
                pass
            self._fallback = None
        try:
            os.remove(self.path)
        except OSError:
            pass
