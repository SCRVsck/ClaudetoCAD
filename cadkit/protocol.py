# -*- coding: utf-8 -*-
"""桥接协议：state.json 握手 + 本地 TCP 单行 JSON 请求/响应。

服务端（bridge）与客户端（cli）共用这一层，保证两边对协议的理解不会漂移。
"""

import json
import os
import socket
import threading

from . import paths

# 协议版本。写进 state.json，客户端据此判断对面那个桥接是不是同一代的 ——
# 桥接是常驻进程，工具升级后老桥接还在跑的情形很常见（比如连接复用规则变了，
# 新客户端的长连接打到「一条连接一条指令」的老服务端上就会出错）。
# 版本不符时客户端自动重启桥接，用户不用手动 stop/start。
PROTO = 2

# 单条指令的字节上限（防止畸形请求把内存吃爆）
MAX_FRAME = 64 * 1024 * 1024


# ---------------------------------------------------------------- state.json
def read_state():
    """读 state.json；不存在 / 损坏 / 是陈旧文件都返回 None。"""
    p = paths.state_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return None
    if not isinstance(st, dict) or "port" not in st:
        return None
    return st


def write_state(state):
    """原子写 state.json。"""
    p = paths.state_path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        pass


def clear_state():
    try:
        os.remove(paths.state_path())
    except OSError:
        pass


def is_alive(state):
    """state.json 里记的端口还有人在听吗？（判断桥接是真活着还是残留文件）"""
    if not state:
        return False
    try:
        s = socket.create_connection(("127.0.0.1", int(state["port"])), timeout=1.5)
        s.close()
        return True
    except Exception:
        return False


def live_state():
    """拿一份确认可用的 state；桥接已死则返回 None。"""
    st = read_state()
    return st if is_alive(st) else None


# ------------------------------------------------------------------- 传输
class BridgeError(RuntimeError):
    pass


class NotConnected(BridgeError):
    """连接层失败 —— 桥接不在、或连接已失效。指令本身的错误不会走到这里
    （那种情况桥接会正常返回 ``{"ok": false}``）。"""


# 长连接复用。脚本里常见「发几百次请求」的用法（如三维建模脚本 ~150 次），
# 每请求一条连接会把本机临时端口耗尽 —— TIME_WAIT 堆积后 connect 直接报
# WSAEADDRINUSE(10048)，实测就这么炸过一次。这里缓存一条连接反复用。
_conn = None
_conn_port = None
_lock = threading.Lock()


def _drop_conn():
    global _conn, _conn_port
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
    _conn_port = None


def close():
    """主动断开缓存的连接（进程收尾时调用）。"""
    with _lock:
        _drop_conn()


def _connect(port, timeout):
    global _conn, _conn_port
    if _conn is not None and _conn_port == port:
        return _conn
    _drop_conn()
    try:
        _conn = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    except OSError as e:
        raise NotConnected("连不上桥接端口 %s：%s" % (port, e))
    _conn_port = port
    return _conn


def _read_line(conn, timeout):
    conn.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        try:
            chunk = conn.recv(65536)
        except socket.timeout:
            raise BridgeError("等待桥接响应超时（%ss）。AutoCAD 可能正忙或卡在对话框。" % timeout)
        except OSError as e:
            raise NotConnected("读取桥接响应失败：%s" % e)
        if not chunk:
            raise NotConnected("桥接在返回结果前关闭了连接")
        buf += chunk
        if len(buf) > MAX_FRAME:
            raise BridgeError("响应体过大（>%dMB）" % (MAX_FRAME // 1024 // 1024))
    return buf.split(b"\n", 1)[0]


def send(obj, timeout=180, state=None):
    """把一条指令发给桥接，返回响应 dict。

    连接是复用的；若缓存连接已失效（桥接重启过），自动重连并重试一次。
    重试只在**发送阶段**失败时进行 —— 那条路径上服务端还没收到请求，
    重发不会造成重复执行。
    """
    st = state or read_state()
    if not st:
        raise NotConnected("桥接没有在运行")
    port = int(st["port"])
    payload = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    with _lock:
        for attempt in (0, 1):
            conn = _connect(port, timeout)
            try:
                conn.sendall(payload)
            except OSError as e:
                _drop_conn()
                if attempt == 0:
                    continue          # 多半是陈旧连接，重连后再发一次
                raise NotConnected("发送指令失败：%s" % e)
            try:
                line = _read_line(conn, timeout)
            except NotConnected:
                _drop_conn()
                raise                 # 已发送，不重试，避免重复执行
            break

    text = line.decode("utf-8", "replace").strip()
    if not text:
        raise BridgeError("桥接没有返回任何内容（可能已崩溃，看 bridge.log）")
    try:
        return json.loads(text)
    except ValueError:
        raise BridgeError("桥接返回的不是合法 JSON：%s" % text[:200])


def request(obj, timeout=None, autostart=None):
    """发送指令；桥接没跑时按配置自动拉起再重试。

    这是 CLI 的正常入口 —— 用户不该先手动起一个后台进程再用工具。
    不做额外的「探活连接」：直接用请求本身探，连不上就说明桥接不在。
    """
    from . import config
    cfg = config.load()
    timeout = float(timeout if timeout is not None else cfg["request_timeout"])
    if autostart is None:
        autostart = bool(cfg["autostart_bridge"])

    st = read_state()
    if st and st.get("proto") != PROTO:
        # 对面是旧版桥接，先请它退场再按新协议拉起来
        from . import daemon
        daemon.stop()
        st = None
    if st:
        try:
            return send(obj, timeout=timeout, state=st)
        except NotConnected:
            pass                      # 桥接不在了，走下面的自动拉起

    if not autostart:
        raise NotConnected("桥接没有在运行，且自动启动已禁用。可手动运行：cadbridge start")

    from . import daemon
    st = daemon.ensure_running()
    return send(obj, timeout=timeout, state=st)
