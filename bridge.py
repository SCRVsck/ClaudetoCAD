#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AutoCAD 双向实时桥接进程 (bridge.py)
====================================
- 常驻运行，通过 win32com COM 长连接 AutoCAD 2022，图形状态全程驻留。
- 本地 TCP 服务 (127.0.0.1)，接收 JSON 指令并实时返回结果（下行）。
- 订阅 AutoCAD 事件并写入 events.jsonl 日志（上行，事件回传）。
- 运行时信息写入 state.json（端口、模式、路径）。

指令协议（每行一个 JSON，返回一行 JSON）：
  {"cmd":"ping"}
  {"cmd":"info"}
  {"cmd":"add_line","start":[x,y,z],"end":[x,y,z]}
  {"cmd":"add_circle","center":[x,y,z],"radius":r}
  {"cmd":"add_text","text":"...","insert":[x,y,z],"height":h}
  {"cmd":"add_polyline","points":[[x,y],...]}
  {"cmd":"add_point","point":[x,y,z]}
  {"cmd":"textstyle","name":"S23","font":"simhei.ttf"}   # 建样式并设为当前
  # ---- 三维实体 ----
  {"cmd":"add_region","handles":[...],"closed":true}     # 闭合曲线 -> 面域
  {"cmd":"extrude","region":"H","height":h,"taper":0}    # 面域 -> 拉伸实体
  {"cmd":"add_box","origin":[x,y,z],"l":..,"w":..,"h":..}
  {"cmd":"add_cylinder","center":[x,y,z],"radius":r,"height":h}
  {"cmd":"boolean","op":"union|subtract|intersect","target":"H","tools":["H",...]}
  {"cmd":"move","handle":"H","from":[..],"to":[..]}
  {"cmd":"rotate3d","handle":"H","p1":[..],"p2":[..],"angle":弧度}
  {"cmd":"setprop","handle":"H","color":256,"layer":"0"}
  {"cmd":"erase","handles":["H",...]}
  {"cmd":"bbox","handle":"H"}                            # 读包围盒，验证位置
  {"cmd":"view3d","dir":[1,1,1]}                         # 设三维视点
  {"cmd":"visualstyle","name":"概念"}                     # 着色显示
  {"cmd":"count"}
  {"cmd":"entities","limit":n}
  {"cmd":"getvar","name":"..."}
  {"cmd":"setvar","name":"...","value":...}
  {"cmd":"sendcommand","text":"..."}      # 原始命令串（异步，无返回值）
  {"cmd":"zoom","mode":"extents|all"}
  {"cmd":"selection"}                       # 当前拾取集 handle 列表
  {"cmd":"save","path":"..."}
  {"cmd":"shutdown"}                        # 仅退出桥接进程（CAD 保留）
  {"cmd":"quit"}                            # 关闭 AutoCAD 并退出桥接
"""

import os
import sys
import json
import socket
import time
import traceback

import pythoncom
import win32com.client

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE, "state.json")
EVENTS_PATH = os.path.join(BASE, "events.jsonl")
LOG_PATH = os.path.join(BASE, "bridge.log")

PROGID = "AutoCAD.Application.24.1"

# 事件订阅开关。本版本 AutoCAD 在 AddLine 等 COM 调用期间触发 ObjectAdded/
# ObjectModified 事件回调会重入并抛异常（RPC_E_SERVERFAULT -> 污染数据库），
# 故默认关闭，改用轮询变更检测（changes 指令）实现上行实时。
ENABLE_EVENTS = False

_evt_lock = None  # threading.Lock, set in main


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def emit_event(name, args):
    """把 AutoCAD 事件实时追加到 events.jsonl。"""
    try:
        rec = {"ts": time.time(), "t": time.strftime("%H:%M:%S"),
               "event": name, "args": [str(a) for a in args]}
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def write_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 事件接收器（best-effort；方法名与 AutoCAD 事件接口一致）
# ----------------------------------------------------------------------------
class _AppEvents:
    def _emit(self, name, *a):
        emit_event("app:" + name, a)

    def OnAppActivate(self, *a): self._emit("AppActivate", *a)
    def OnAppDeactivate(self, *a): self._emit("AppDeactivate", *a)
    def OnBeginFileDrop(self, *a): self._emit("BeginFileDrop", *a)
    def OnBeginLisp(self, *a): self._emit("BeginLisp", *a)
    def OnBeginModal(self, *a): self._emit("BeginModal", *a)
    def OnBeginOpen(self, *a): self._emit("BeginOpen", *a)
    def OnBeginPlot(self, *a): self._emit("BeginPlot", *a)
    def OnBeginQuit(self, *a): self._emit("BeginQuit", *a)
    def OnBeginSave(self, *a): self._emit("BeginSave", *a)
    def OnEndLisp(self, *a): self._emit("EndLisp", *a)
    def OnEndModal(self, *a): self._emit("EndModal", *a)
    def OnEndOpen(self, *a): self._emit("EndOpen", *a)
    def OnEndPlot(self, *a): self._emit("EndPlot", *a)
    def OnEndSave(self, *a): self._emit("EndSave", *a)
    def OnLispCancelled(self, *a): self._emit("LispCancelled", *a)
    def OnNewDrawing(self, *a): self._emit("NewDrawing", *a)
    def OnSysVarChanged(self, *a): self._emit("SysVarChanged", *a)
    def OnWindowChanged(self, *a): self._emit("WindowChanged", *a)
    def OnARXLoaded(self, *a): self._emit("ARXLoaded", *a)
    def OnARXUnloaded(self, *a): self._emit("ARXUnloaded", *a)
    def OnBeginCommand(self, *a): self._emit("BeginCommand", *a)
    def OnEndCommand(self, *a): self._emit("EndCommand", *a)
    def OnEndQuit(self, *a): self._emit("EndQuit", *a)


class _DocEvents:
    def _emit(self, name, *a):
        emit_event("doc:" + name, a)

    def OnActivate(self, *a): self._emit("Activate", *a)
    def OnDeactivate(self, *a): self._emit("Deactivate", *a)
    def OnBeginClose(self, *a): self._emit("BeginClose", *a)
    def OnBeginCommand(self, *a): self._emit("BeginCommand", *a)
    def OnEndCommand(self, *a): self._emit("EndCommand", *a)
    def OnBeginDocClose(self, *a): self._emit("BeginDocClose", *a)
    def OnBeginDoubleClick(self, *a): self._emit("BeginDoubleClick", *a)
    def OnBeginRightClick(self, *a): self._emit("BeginRightClick", *a)
    def OnBeginSave(self, *a): self._emit("BeginSave", *a)
    def OnEndSave(self, *a): self._emit("EndSave", *a)
    def OnBeginPlot(self, *a): self._emit("BeginPlot", *a)
    def OnEndPlot(self, *a): self._emit("EndPlot", *a)
    def OnEndLisp(self, *a): self._emit("EndLisp", *a)
    def OnLispCancelled(self, *a): self._emit("LispCancelled", *a)
    def OnLayoutSwitched(self, *a): self._emit("LayoutSwitched", *a)
    def OnObjectAdded(self, *a): self._emit("ObjectAdded", *a)
    def OnObjectErased(self, *a): self._emit("ObjectErased", *a)
    def OnObjectModified(self, *a): self._emit("ObjectModified", *a)
    def OnSelectionChanged(self, *a): self._emit("SelectionChanged", *a)
    def OnWindowChanged(self, *a): self._emit("WindowChanged", *a)


# ----------------------------------------------------------------------------
# COM 连接
# ----------------------------------------------------------------------------
def connect():
    """连接（或拉起）AutoCAD，并尽量订阅事件。返回 (app, doc, mode)。"""
    app = None
    attached = False
    try:
        app = win32com.client.GetActiveObject(PROGID)
        attached = True
        log("attached to running AutoCAD instance")
    except Exception:
        pass

    events_ok = False
    if app is None:
        if ENABLE_EVENTS:
            try:
                app = win32com.client.DispatchWithEvents(PROGID, _AppEvents)
                events_ok = True
                log("launched AutoCAD via DispatchWithEvents")
            except Exception as e:
                log("DispatchWithEvents failed (%s); falling back to Dispatch" % e)
                app = win32com.client.Dispatch(PROGID)
        else:
            app = win32com.client.Dispatch(PROGID)
            log("launched AutoCAD via Dispatch (events disabled)")
    else:
        if ENABLE_EVENTS:
            try:
                app = win32com.client.DispatchWithEvents(app, _AppEvents)
                events_ok = True
                log("wrapped existing app with events")
            except Exception as e:
                log("event wrap of existing app failed: %s" % e)
                events_ok = False
        else:
            log("attached; events disabled")

    try:
        app.Visible = True
    except Exception as e:
        log("set Visible failed: %s" % e)

    # 等待文档就绪
    doc = None
    for _ in range(200):
        try:
            if app.Documents.Count == 0:
                app.Documents.Add()
            doc = app.ActiveDocument
            if doc is not None:
                break
        except Exception:
            pass
        time.sleep(0.1)

    if doc is None:
        raise RuntimeError("无法取得 AutoCAD 文档")

    doc_events_ok = False
    if ENABLE_EVENTS:
        try:
            doc = win32com.client.DispatchWithEvents(doc, _DocEvents)
            doc_events_ok = True
        except Exception as e:
            log("doc event wrap failed: %s" % e)

    mode = "attached" if attached else "launched"
    if ENABLE_EVENTS:
        ev = ("app" if events_ok else "-") + "+" + ("doc" if doc_events_ok else "-")
    else:
        ev = "off"
    log("connect OK. mode=%s events=%s" % (mode, ev))
    return app, doc, mode, ev


# ----------------------------------------------------------------------------
# 指令处理
# ----------------------------------------------------------------------------
def _pt(x, y=0.0, z=0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                   [float(x), float(y), float(z)])


def _entity_info(e):
    from win32com.client import dynamic
    d = dynamic.Dispatch(e)  # 迟绑定，可访问具体图元接口的属性
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


def handle(cmd, app, doc):
    c = cmd.get("cmd", "")
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
                "entities": int(ms.Count), "visible": bool(app.Visible)}

    if c == "add_line":
        e = ms.AddLine(_pt(*cmd["start"]), _pt(*cmd["end"]))
        return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

    if c == "add_circle":
        e = ms.AddCircle(_pt(*cmd["center"]), float(cmd["radius"]))
        return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

    if c == "add_text":
        e = ms.AddText(str(cmd["text"]), _pt(*cmd["insert"]), float(cmd.get("height", 2.5)))
        return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

    if c == "add_polyline":
        pts = []
        for p in cmd["points"]:
            pts.append(float(p[0])); pts.append(float(p[1]))
            if len(p) > 2:
                pts.append(float(p[2]))
            else:
                pts.append(0.0)
        arr = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, pts)
        e = ms.AddPolyline(arr)
        if cmd.get("closed"):
            try:
                e.Closed = True
            except Exception:
                pass
        return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

    # ---------------- 三维实体建模 ----------------
    if c == "add_region":
        objs = [doc.HandleToObject(str(h)) for h in cmd["handles"]]
        arr = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, objs)
        regs = ms.AddRegion(arr)
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
        op = {"union": 0, "intersect": 1, "subtract": 2}[str(cmd.get("op", "union")).lower()]
        tgt = doc.HandleToObject(str(cmd["target"]))
        for h in cmd["tools"]:
            tgt.Boolean(op, doc.HandleToObject(str(h)))
        return {"ok": True, "handle": tgt.Handle}

    if c == "move":
        e = doc.HandleToObject(str(cmd["handle"]))
        e.Move(_pt(*cmd["from"]), _pt(*cmd["to"]))
        return {"ok": True}

    if c == "rotate3d":
        e = doc.HandleToObject(str(cmd["handle"]))
        e.Rotate3D(_pt(*cmd["p1"]), _pt(*cmd["p2"]), float(cmd["angle"]))
        return {"ok": True}

    if c == "setprop":
        # IAcad3DSolid 的早绑定包装不含 Color/GeometricExtents，必须走迟绑定
        from win32com.client import dynamic
        e = dynamic.Dispatch(doc.HandleToObject(str(cmd["handle"])))
        if cmd.get("color") is not None:
            e.Color = int(cmd["color"])
        if cmd.get("layer"):
            e.Layer = str(cmd["layer"])
        return {"ok": True}

    if c == "erase":
        for h in (cmd.get("handles") or [cmd["handle"]]):
            try:
                doc.HandleToObject(str(h)).Delete()
            except Exception:
                pass
        return {"ok": True}

    if c == "bbox":
        from win32com.client import dynamic
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

    if c == "add_point":
        e = ms.AddPoint(_pt(*cmd["point"]))
        return {"ok": True, "handle": e.Handle, "object": e.ObjectName}

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
        import hashlib
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

    if c == "textstyle":
        # 创建/更新文字样式并设为当前样式（用于中文 TrueType 字体）
        name = str(cmd.get("name", "S23"))
        font = str(cmd.get("font", "simhei.ttf"))
        charset = int(cmd.get("charset", 134))   # 134 = GB2312_CHARSET
        try:
            ts = doc.TextStyles.Item(name)
        except Exception:
            ts = doc.TextStyles.Add(name)
        ts.SetFont(font, bool(cmd.get("bold", False)),
                   bool(cmd.get("italic", False)), charset, 0)
        try:
            ts.Height = 0.0        # 0 = 文字高度不固定，由每次 AddText 指定
            ts.Width = 1.0
        except Exception:
            pass
        doc.ActiveTextStyle = ts
        try:
            ffile = str(ts.fontFile)
        except Exception:
            ffile = None
        return {"ok": True, "name": str(ts.Name), "font": ffile}

    if c == "getvar":
        return {"ok": True, "name": cmd["name"], "value": doc.GetVariable(cmd["name"])}

    if c == "setvar":
        doc.SetVariable(cmd["name"], cmd["value"])
        return {"ok": True}

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


# ----------------------------------------------------------------------------
# 主循环
# ----------------------------------------------------------------------------
def main():
    global _evt_lock
    import threading
    _evt_lock = threading.Lock()

    app, doc, mode, ev = connect()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    server.settimeout(0.2)

    write_state({"port": port, "mode": mode, "events": ev,
                 "events_path": EVENTS_PATH, "log_path": LOG_PATH,
                 "pid": os.getpid(), "started": time.time()})
    log("bridge listening on 127.0.0.1:%d" % port)
    print("BRIDGE_READY port=%d mode=%s events=%s" % (port, mode, ev), flush=True)

    try:
        while True:
            # 泵 COM 消息，让事件回调能实时送达（仅事件开启时）
            if ENABLE_EVENTS:
                try:
                    pythoncom.PumpWaitingMessages()
                except Exception:
                    pass

            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                conn.settimeout(60)
                buf = b""
                while b"\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > 50 * 1024 * 1024:
                        break
                req = json.loads(buf.decode("utf-8", "replace").strip() or "{}")
                resp = None
                last_err = None
                for _attempt in range(8):
                    try:
                        resp = handle(req, app, doc)
                        break
                    except Exception as e:
                        hr = getattr(e, "hresult", None)
                        if hr is None and getattr(e, "args", None):
                            hr = e.args[0] if isinstance(e.args[0], int) else None
                        # RPC_E_CALL_REJECTED (-2147418111)：AutoCAD 忙/模态时拒绝，
                        # 稍等重试即可恢复。
                        if hr == -2147418111 and _attempt < 7:
                            last_err = e
                            time.sleep(0.6)
                            continue
                        raise
                if resp is None:
                    raise last_err
                if resp.get("shutdown") or resp.get("quit"):
                    conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    conn.close()
                    break
                conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            except Exception as e:
                try:
                    conn.sendall((json.dumps({"ok": False, "error": str(e), "tb": traceback.format_exc()},
                                             ensure_ascii=False) + "\n").encode("utf-8"))
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    finally:
        server.close()
        log("bridge exited")
        write_state({"port": port, "exited": True, "at": time.time()})


if __name__ == "__main__":
    main()
