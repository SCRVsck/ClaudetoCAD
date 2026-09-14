# -*- coding: utf-8 -*-
"""桥接服务端：常驻进程，持有唯一的 AutoCAD COM 连接。

相对于原型的三处产品化改造：

1. **CAD 掉线自愈** —— 原型里 AutoCAD 一崩，桥接手里的 COM 引用就成僵尸，
   之后每个请求都报 ``RPC_E_CALL_REJECTED`` 却永远好不了。现在每个请求前做一次
   轻量健康探测，发现死了就重新连接（必要时重新拉起 CAD）。
2. **日志轮转** —— 原型只往一个文件无限追加，跑久了会撑爆磁盘。
3. **单实例** —— 锁文件保证同时只有一个桥接，避免多路 COM 连接互相打架
   （这正是文档里反复警告的 ``RPC_E_CALL_REJECTED`` 根因）。
"""

import hashlib
import json
import os
import select
import socket
import sys
import time
import traceback

from . import acad, config, daemon, paths, protocol

try:
    import pythoncom
    import win32com.client
    from win32com.client import dynamic
    HAVE_PYWIN32 = True
except ImportError:  # pragma: no cover
    pythoncom = None
    win32com = None
    dynamic = None
    HAVE_PYWIN32 = False


# 本版本 AutoCAD 在 AddLine 等 COM 调用期间触发 ObjectAdded/ObjectModified
# 回调会重入并抛 RPC_E_SERVERFAULT、污染数据库，故事件默认关闭，
# 上行实时改走 changes 轮询。
ENABLE_EVENTS = False


# --------------------------------------------------------------------- 日志
class Logger:
    """带轮转的简单日志器。"""

    def __init__(self, path, max_bytes=2_000_000, backups=3):
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups

    def _rotate(self):
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) >= self.max_bytes:
                for i in range(self.backups - 1, 0, -1):
                    src, dst = "%s.%d" % (self.path, i), "%s.%d" % (self.path, i + 1)
                    if os.path.exists(src):
                        os.replace(src, dst)
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def __call__(self, msg):
        try:
            self._rotate()
            line = "[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


# ------------------------------------------------------------------- 工具
def _pt(x, y=0.0, z=0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                   [float(x), float(y), float(z)])


def _arr_dispatch(objs):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, objs)


def _entity_info(e):
    d = dynamic.Dispatch(e)  # 迟绑定才能访问具体图元接口的属性
    info = {"Handle": None, "ObjectName": None, "Layer": None}
    for k in ("Handle", "ObjectName", "Layer", "Color"):
        try:
            info[k] = getattr(d, k)
        except Exception:
            pass
    name = info.get("ObjectName") or ""
    try:
        if name.endswith("Line"):
            info["Start"] = list(d.StartPoint)
            info["End"] = list(d.EndPoint)
        elif name.endswith("Circle"):
            info["Center"] = list(d.Center)
            info["Radius"] = float(d.Radius)
        elif name.endswith("Text") or name.endswith("MText"):
            info["Text"] = d.TextString
            info["Insert"] = list(d.InsertionPoint)
        elif name.endswith("Point"):
            info["Coord"] = list(d.Coordinate)
        elif "Polyline" in name:
            try:
                info["Coords"] = list(d.Coordinates)
            except Exception:
                pass
    except Exception:
        pass
    return info


def emit_event(path, name, args):
    try:
        rec = {"ts": time.time(), "t": time.strftime("%H:%M:%S"),
               "event": name, "args": [str(a) for a in args]}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------- 服务
class BridgeServer:
    def __init__(self):
        cfg = config.load()
        self.cfg = cfg
        self.log = Logger(paths.log_path(), cfg["log_max_bytes"], cfg["log_backups"])
        self.app = None
        self.doc = None
        self.info = {}
        self.port = None
        self.token = None
        self.last_health = 0.0

    # ---------------------------------------------------------- 连接管理
    def connect(self):
        self.app, self.doc, self.info = acad.connect(
            autostart=self.cfg.get("autostart_cad", True), log=self.log)
        self.last_health = time.time()

    def _ensure_alive(self):
        """请求前轻量探测；CAD 已死则重连。"""
        if self.app is None:
            self.connect()
            return
        interval = float(self.cfg.get("health_interval", 15.0) or 0)
        if interval and (time.time() - self.last_health) < interval:
            return
        ok, err = acad.healthy(self.app, self.doc)
        self.last_health = time.time()
        if ok:
            return
        self.log("健康探测失败（%s），正在重连 AutoCAD…" % err)
        self.app = self.doc = None
        try:
            self.connect()
            self.log("重连成功")
        except Exception as e:
            self.log("重连失败：%s" % e)
            raise

    # ------------------------------------------------------------ 指令
    def handle(self, cmd):
        c = cmd.get("cmd", "")
        app, doc = self.app, self.doc
        ms = doc.ModelSpace

        if c == "ping":
            return {"ok": True, "pong": True, "time": time.time()}

        if c == "info":
            try:
                ver = app.Version
            except Exception:
                ver = None
            try:
                dname = doc.Name
            except Exception:
                dname = None
            return {"ok": True, "version": ver, "doc": dname,
                    "entities": int(ms.Count), "visible": bool(app.Visible),
                    "progid": self.info.get("progid"),
                    "acad_version": self.info.get("version"),
                    "mode": self.info.get("mode")}

        if c == "health":
            ok, err = acad.healthy(app, doc)
            return {"ok": True, "healthy": ok, "error": str(err) if err else None,
                    "entities": int(ms.Count) if ok else None}

        # ---------------- 基础绘图 ----------------
        if c == "add_line":
            e = ms.AddLine(_pt(*cmd["start"]), _pt(*cmd["end"]))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "add_circle":
            e = ms.AddCircle(_pt(*cmd["center"]), float(cmd["radius"]))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "add_text":
            e = ms.AddText(str(cmd["text"]), _pt(*cmd["insert"]),
                           float(cmd.get("height", 2.5)))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "add_polyline":
            pts = []
            for p in cmd["points"]:
                pts.append(float(p[0]))
                pts.append(float(p[1]))
                pts.append(float(p[2]) if len(p) > 2 else 0.0)
            arr = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, pts)
            e = ms.AddPolyline(arr)
            if cmd.get("closed"):
                try:
                    e.Closed = True
                except Exception:
                    pass
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "add_point":
            e = ms.AddPoint(_pt(*cmd["point"]))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        # ---------------- 三维实体 ----------------
        if c == "add_region":
            objs = [doc.HandleToObject(str(h)) for h in cmd["handles"]]
            regs = ms.AddRegion(_arr_dispatch(objs))
            try:
                out = [regs.Item(i).Handle for i in range(int(regs.Count))]
            except Exception:
                out = [r.Handle for r in regs]
            return {"ok": True, "handles": out, "count": len(out)}

        if c == "extrude":
            r = doc.HandleToObject(str(cmd["region"]))
            s = ms.AddExtrudedSolid(r, float(cmd["height"]), float(cmd.get("taper", 0.0)))
            return {"ok": True, "handle": s.Handle, "object": s.ObjectName}

        if c == "add_box":
            e = ms.AddBox(_pt(*cmd["origin"]), float(cmd["l"]),
                          float(cmd["w"]), float(cmd["h"]))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "add_cylinder":
            e = ms.AddCylinder(_pt(*cmd["center"]), float(cmd["radius"]),
                               float(cmd["height"]))
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

        if c == "boolean":
            op = {"union": 0, "intersect": 1, "subtract": 2}[
                str(cmd.get("op", "union")).lower()]
            tgt = doc.HandleToObject(str(cmd["target"]))
            for h in cmd["tools"]:
                tgt.Boolean(op, doc.HandleToObject(str(h)))
            return {"ok": True, "handle": tgt.Handle}

        if c == "move":
            doc.HandleToObject(str(cmd["handle"])).Move(
                _pt(*cmd["from"]), _pt(*cmd["to"]))
            return {"ok": True}

        if c == "rotate3d":
            doc.HandleToObject(str(cmd["handle"])).Rotate3D(
                _pt(*cmd["p1"]), _pt(*cmd["p2"]), float(cmd["angle"]))
            return {"ok": True}

        if c == "setprop":
            # IAcad3DSolid 的早绑定包装不含 Color，必须走迟绑定
            e = dynamic.Dispatch(doc.HandleToObject(str(cmd["handle"])))
            if cmd.get("color") is not None:
                e.Color = int(cmd["color"])
            if cmd.get("layer"):
                e.Layer = str(cmd["layer"])
            return {"ok": True}

        if c == "erase":
            for h in (cmd.get("handles") or [cmd.get("handle")]):
                try:
                    doc.HandleToObject(str(h)).Delete()
                except Exception:
                    pass
            return {"ok": True}

        if c == "bbox":
            e = dynamic.Dispatch(doc.HandleToObject(str(cmd["handle"])))
            try:
                ext = e.GeometricExtents
                return {"ok": True, "min": list(ext.MinPoint),
                        "max": list(ext.MaxPoint), "via": "extents"}
            except Exception:
                p1 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                             [0.0, 0.0, 0.0])
                p2 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                             [0.0, 0.0, 0.0])
                e.GetBoundingBox(p1, p2)
                return {"ok": True, "min": list(p1.value),
                        "max": list(p2.value), "via": "getbbox"}

        if c == "view3d":
            try:
                vp = doc.ActiveViewport
                vp.Direction = _pt(*cmd.get("dir", [1, 1, 1]))
                doc.ActiveViewport = vp
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": True}

        # ---------------- 查询 ----------------
        if c == "count":
            return {"ok": True, "count": int(ms.Count)}

        if c == "changes":
            n = int(ms.Count)
            handles = []
            for i in range(n):
                try:
                    handles.append(ms.Item(i).Handle)
                except Exception:
                    handles.append(None)
            sig = hashlib.md5(repr((n, handles)).encode("utf-8")).hexdigest()[:12]
            return {"ok": True, "count": n, "sig": sig, "handles": handles}

        if c == "entities":
            limit = int(cmd.get("limit", 500))
            n = int(ms.Count)
            out = []
            for i in range(min(n, limit)):
                try:
                    out.append(_entity_info(ms.Item(i)))
                except Exception:
                    out.append({"Handle": None, "error": "read failed"})
            return {"ok": True, "count": n, "returned": len(out), "entities": out}

        if c == "selection":
            sel = doc.PickfirstSelectionSet
            out = []
            if sel is not None:
                for i in range(sel.Count):
                    try:
                        out.append(_entity_info(sel.Item(i)))
                    except Exception:
                        pass
            return {"ok": True, "count": len(out), "entities": out}

        if c == "getvar":
            return {"ok": True, "name": cmd["name"], "value": doc.GetVariable(cmd["name"])}

        if c == "setvar":
            doc.SetVariable(cmd["name"], cmd["value"])
            return {"ok": True}

        # ---------------- 文字样式 ----------------
        if c == "textstyle":
            name = str(cmd.get("name", "CadBridge"))
            font = str(cmd.get("font", "SimHei"))
            charset = int(cmd.get("charset", 134))  # 134 = GB2312_CHARSET
            try:
                ts = doc.TextStyles.Item(name)
            except Exception:
                ts = doc.TextStyles.Add(name)
            ts.SetFont(font, bool(cmd.get("bold", False)),
                       bool(cmd.get("italic", False)), charset, 0)
            try:
                ts.Height = 0.0   # 0 = 高度不固定，由每次 AddText 指定
                ts.Width = 1.0
            except Exception:
                pass
            doc.ActiveTextStyle = ts
            try:
                ffile = str(ts.fontFile)
            except Exception:
                ffile = None
            return {"ok": True, "name": str(ts.Name), "font": ffile}

        # ---------------- 控制 ----------------
        if c == "sendcommand":
            doc.SendCommand(str(cmd["text"]) + "\n")
            return {"ok": True, "async": True}

        if c == "zoom":
            mode = cmd.get("mode", "extents")
            if mode == "center":
                ct = cmd["center"]
                doc.SendCommand("_.ZOOM _C %f,%f,%f %f " %
                                (ct[0], ct[1], ct[2], float(cmd["height"])))
            else:
                doc.SendCommand("ZOOM %s \n" % mode)
            return {"ok": True, "async": True}

        if c == "visualstyle":
            doc.SendCommand("_.VSCURRENT _%s " % cmd["name"])
            return {"ok": True, "async": True}

        if c == "save":
            path = cmd["path"]
            doc.SaveAs(path)
            return {"ok": True, "path": path}

        if c == "shutdown":
            return {"ok": True, "shutdown": True}

        if c == "quit":
            try:
                app.Quit()
            except Exception:
                pass
            return {"ok": True, "quit": True}

        return {"ok": False, "error": "unknown cmd: %s" % c}

    # ------------------------------------------------------------ 鉴权
    def _authorized(self, req):
        """校验接入 token。用常数时间比较，避免时序侧信道。"""
        import hmac
        got = req.get(protocol.TOKEN_FIELD)
        if not self.token or not isinstance(got, str):
            return False
        return hmac.compare_digest(got, self.token)

    # ------------------------------------------------------------ 主循环
    def serve_forever(self):
        lock = daemon.SingleInstance()
        if not lock.acquire():
            # 已有桥接在跑；确认它还活着就安静退出，否则夺锁重来
            if protocol.live_state():
                print("BRIDGE_ALREADY_RUNNING", flush=True)
                return 0
            self.log("发现残留锁但桥接无响应，接管")

        try:
            self.connect()
        except Exception as e:
            self.log("启动失败：%s" % e)
            print("BRIDGE_FAILED %s" % e, flush=True)
            lock.release()
            return 2

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))          # 只监听回环
        server.listen(32)
        self.port = server.getsockname()[1]

        # 每次启动换一把新 token，和 state.json 一起放在用户私有目录里
        self.token = protocol.new_token()

        protocol.write_state({
            "port": self.port, "pid": os.getpid(),
            "proto": protocol.PROTO,
            "token": self.token,
            "mode": self.info.get("mode"), "progid": self.info.get("progid"),
            "acad_version": self.info.get("version"),
            "events": "off", "started": time.time(),
            "data_dir": paths.data_dir(),
            "log_path": paths.log_path(), "events_path": paths.events_path(),
        })
        self.log("桥接已监听 127.0.0.1:%d（AutoCAD %s，%s）"
                 % (self.port, self.info.get("version"), self.info.get("mode")))
        print("BRIDGE_READY port=%d" % self.port, flush=True)

        # 多路复用而不是「一条连接处理到底」。
        # 客户端会复用长连接（为了不耗尽临时端口），而长连接大部分时间是空闲的；
        # 单线程 accept 循环会在那条空闲连接上阻塞住，别的客户端根本进不来 ——
        # 现场表现是：桥接明明在监听，status 却报「桥接未运行」（新连接的 SYN
        # 堆在 backlog 里，堆满就被内核丢掉）。
        #
        # 这里刻意**不用「每连接一个线程」**：AutoCAD 的 COM 对象是在主线程
        # 创建的，跨线程调用需要 marshaling，风险比收益大。select 循环让所有
        # COM 调用仍然只发生在主线程。
        conns = {}          # socket -> {"buf": bytearray, "last": float}
        idle = float(self.cfg.get("conn_idle_timeout", 300))
        stopping = False

        try:
            while not stopping:
                socks = [server] + list(conns)
                try:
                    ready, _, _ = select.select(socks, [], [], 0.5)
                except (OSError, ValueError):
                    continue

                for s in ready:
                    if s is server:
                        try:
                            conn, _addr = server.accept()
                        except OSError:
                            continue
                        conns[conn] = {"buf": bytearray(), "last": time.time()}
                        continue

                    state = conns.get(s)
                    if state is None:
                        continue

                    try:
                        chunk = s.recv(65536)
                    except OSError:
                        self._drop(conns, s)
                        continue
                    if not chunk:
                        self._drop(conns, s)      # 客户端正常关闭
                        continue

                    state["last"] = time.time()
                    state["buf"] += chunk
                    if len(state["buf"]) > protocol.MAX_FRAME:
                        self._drop(conns, s)
                        continue

                    # 一条连接上可能一次到达多条指令，逐行处理
                    def _send(resp, _s=s):
                        _s.sendall((json.dumps(resp, ensure_ascii=False) + "\n")
                                   .encode("utf-8"))

                    try:
                        if self._process_buffer(state["buf"], _send):
                            stopping = True
                            break
                    except OSError:
                        self._drop(conns, s)
                        continue

                # 清掉空闲太久的连接，别让死掉的客户端一直占着
                now = time.time()
                for s in [c for c, st in conns.items() if now - st["last"] > idle]:
                    self._drop(conns, s)
        finally:
            for s in list(conns):
                self._drop(conns, s)
            try:
                server.close()
            except Exception:
                pass
            protocol.clear_state()
            self.log("桥接已退出")
            lock.release()
        return 0

    def _drop(self, conns, sock):
        conns.pop(sock, None)
        try:
            sock.close()
        except Exception:
            pass

    def _process_buffer(self, buf, send):
        """处理缓冲区里所有完整行。返回 True 表示桥接应当退出。

        ``buf`` 是 bytearray，未消费的尾巴留在里面；``send`` 是发送响应的回调，
        便于测试时替换掉真实 socket。

        空行必须跳过：客户端探活时会开一条连接立刻关闭，若把它当成
        ``{"cmd": ""}`` 走完整流程，就会触发 AutoCAD 健康检查 ——
        一次只读的 status 查询会把 AutoCAD 给重启了。
        """
        stopping = False
        while not stopping and b"\n" in buf:
            line, _, rest = bytes(buf).partition(b"\n")
            buf[:] = rest
            if not line.strip():
                continue
            resp = self._handle_line(line)
            send(resp)
            stopping = bool(resp.get("shutdown") or resp.get("quit"))
        return stopping

    def _handle_line(self, line):
        """把一行原始请求变成一行响应。鉴权、解析、重试都在这里。"""
        try:
            req = json.loads(line.decode("utf-8", "replace"))
        except ValueError as e:
            return {"ok": False, "error": "请求不是合法 JSON：%s" % e}

        if not self._authorized(req):
            self.log("拒绝了一个未通过鉴权的请求（cmd=%r）" % req.get("cmd"))
            return {"ok": False,
                    "error": "鉴权失败：token 不匹配。"
                             "若刚升级过工具，跑一次 cadbridge stop 让桥接重启。"}
        try:
            return self._dispatch_with_retry(req)
        except Exception as e:
            payload = {"ok": False, "error": str(e)}
            if os.environ.get("CADBRIDGE_DEBUG"):
                payload["tb"] = traceback.format_exc()
            return payload

    def _dispatch_with_retry(self, req):
        """执行指令；AutoCAD 忙时按配置重试，掉线则重连后重试一次。"""
        retries = int(self.cfg.get("retries", 8))
        delay = float(self.cfg.get("retry_delay", 0.6))
        reconnected = False
        last = None

        # ping 探的是「桥接进程还活着吗」，不是 AutoCAD 的状态。
        # 让它绕过健康探测与重连 —— 否则一个纯粹的探活调用会有
        # 拉起 AutoCAD 这种重副作用。
        light = req.get("cmd") in ("ping",)

        for attempt in range(retries):
            try:
                if not light:
                    self._ensure_alive()
                return self.handle(req)
            except Exception as e:
                hr = getattr(e, "hresult", None)
                if hr is None and getattr(e, "args", None):
                    hr = e.args[0] if isinstance(e.args[0], int) else None

                # RPC_E_CALL_REJECTED：AutoCAD 忙（模态对话框 / 命令进行中），等一下就好
                if hr == -2147418111 and attempt < retries - 1:
                    last = e
                    time.sleep(delay)
                    continue

                # 其它 COM 错误先试一次重连（CAD 可能被关了或崩了）
                if not reconnected:
                    reconnected = True
                    last = e
                    self.log("指令 %s 失败（%s），尝试重连后重试" % (req.get("cmd"), e))
                    self.app = self.doc = None
                    continue

                raise
        raise last
