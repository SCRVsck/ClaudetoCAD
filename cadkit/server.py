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
            for k in ("StyleName", "Height", "Rotation"):
                try:
                    info[k] = getattr(d, k)
                except Exception:
                    pass
        elif name.endswith("Point"):
            info["Coord"] = list(d.Coordinate)
        elif "Polyline" in name:
            try:
                info["Coords"] = list(d.Coordinates)
            except Exception:
                pass
        elif "Hatch" in name:
            # 填充图案名 / 比例 / 面积 —— 复刻工程图时要靠它对齐土层的填充约定
            for k in ("PatternName", "PatternScale", "PatternAngle"):
                try:
                    info[k] = getattr(d, k)
                except Exception:
                    pass
            try:
                info["Area"] = float(d.Area)
            except Exception:
                pass
            try:
                # 边界可能有很多条，只回报数量，免得分量太大
                info["Loops"] = int(d.NumberOfLoops)
            except Exception:
                pass
        elif "Dimension" in name:
            try:
                info["Measurement"] = float(d.Measurement)
            except Exception:
                pass
            for k in ("TextOverride", "TextHeight"):
                try:
                    info[k] = getattr(d, k)
                except Exception:
                    pass
        elif "BlockReference" in name:
            try:
                info["BlockName"] = d.Name
            except Exception:
                pass
            try:
                info["Insert"] = list(d.InsertionPoint)
            except Exception:
                pass
            # 插入比例很关键：这套图框块是 420×297 的**纸面毫米**尺寸，
            # 插进 mm 绘图环境要放 100 倍才对得上 1:100。
            for k in ("XScaleFactor", "YScaleFactor", "Rotation"):
                try:
                    info[k] = float(getattr(d, k))
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

    def _current_doc(self):
        """跟随 AutoCAD 当前的活动文档。

        原先把文档对象在连接时缓存住，用户在 CAD 里打开/切换图纸后，
        桥接仍然对着旧图纸操作 —— 画出来的东西「不知道去哪了」。
        每个请求前重新取一次活动文档，行为就跟用户看到的一致。
        """
        try:
            d = self.app.ActiveDocument
            if d is not None:
                self.doc = d
        except Exception:
            pass          # 取不到就继续用缓存的，别让整个请求失败
        return self.doc

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
        app = self.app
        doc = self._current_doc()
        ms = doc.ModelSpace

        if c == "ping":
            return {"ok": True, "pong": True, "time": time.time()}

        # ---------------- 文档管理 ----------------
        if c == "docs":
            out = []
            for i in range(int(app.Documents.Count)):
                try:
                    d = app.Documents.Item(i)
                    out.append({"index": i, "name": d.Name, "full": d.FullName,
                                "active": i == int(app.ActiveDocument.Index)})
                except Exception:
                    out.append({"index": i, "name": None})
            return {"ok": True, "count": len(out), "documents": out}

        if c == "open":
            path = os.path.abspath(str(cmd["path"]))
            if not os.path.exists(path):
                return {"ok": False, "error": "文件不存在：%s" % path}
            # 已经打开就激活它 —— 重复 Open 同一个文件会**再开一个新文档**，
            # 结果一堆同名标签页，后续操作落在哪个上完全不确定。
            for i in range(int(app.Documents.Count)):
                try:
                    d = app.Documents.Item(i)
                    if os.path.abspath(str(d.FullName)).lower() == path.lower():
                        d.Activate()
                        self.doc = d
                        return {"ok": True, "name": d.Name, "full": d.FullName,
                                "already_open": True,
                                "entities": int(d.ModelSpace.Count)}
                except Exception:
                    pass
            try:
                d = app.Documents.Open(path)
            except Exception as e:
                return {"ok": False, "error": "打开失败：%s" % e}
            if cmd.get("focus", True):
                self.doc = d
            return {"ok": True, "name": d.Name, "full": d.FullName,
                    "entities": int(d.ModelSpace.Count)}

        if c == "closedocs":
            """关掉所有文档（默认不保存），只留 keep 指定的那张。"""
            keep = cmd.get("keep")
            closed = []
            for i in range(int(app.Documents.Count) - 1, -1, -1):
                try:
                    d = app.Documents.Item(i)
                    if keep and str(d.Name).lower() == str(keep).lower():
                        continue
                    nm = str(d.Name)
                    d.Close(False)
                    closed.append(nm)
                except Exception:
                    pass
            self.doc = app.ActiveDocument if int(app.Documents.Count) else None
            return {"ok": True, "closed": closed,
                    "remaining": int(app.Documents.Count)}

        if c == "activate":
            # 切到某张已打开的图纸（按名字）
            name = str(cmd["name"])
            for i in range(int(app.Documents.Count)):
                d = app.Documents.Item(i)
                if d.Name.lower() == name.lower() or d.FullName.lower() == name.lower():
                    d.Activate()
                    self.doc = d
                    return {"ok": True, "name": d.Name}
            return {"ok": False, "error": "没有打开名为 %r 的图纸" % name}

        if c == "new":
            d = app.Documents.Add()
            self.doc = d
            return {"ok": True, "name": d.Name}

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
        # 建图元时直接支持 layer / color：早先是「先创建、再按句柄 setprop」，
        # 那条路要 HandleToObject 回查，偶发「未找到主键」失败，
        # 结果图元留在当前层上（比如模板的「地下室」），很难发现。
        def _finish(e, spec):
            if spec.get("layer") or spec.get("color") is not None:
                de = dynamic.Dispatch(e)
                if spec.get("layer"):
                    de.Layer = str(spec["layer"])
                if spec.get("color") is not None:
                    de.Color = int(spec["color"])
            return {"ok": True, "handle": e.Handle, "object": e.ObjectName,
                    "layer": str(spec.get("layer") or "")}

        if c == "add_line":
            e = ms.AddLine(_pt(*cmd["start"]), _pt(*cmd["end"]))
            return _finish(e, cmd)

        if c == "add_circle":
            e = ms.AddCircle(_pt(*cmd["center"]), float(cmd["radius"]))
            return _finish(e, cmd)

        if c == "add_text":
            e = ms.AddText(str(cmd["text"]), _pt(*cmd["insert"]),
                           float(cmd.get("height", 2.5)))
            return _finish(e, cmd)

        if c == "add_mtext":
            e = ms.AddMText(_pt(*cmd["insert"]), float(cmd.get("width", 0.0)),
                            str(cmd["text"]))
            try:
                e.Height = float(cmd.get("height", 2.5))
            except Exception:
                pass
            out = _finish(e, cmd)
            try:
                out["width"] = float(e.Width)
            except Exception:
                pass
            return out

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
            return _finish(e, cmd)

        if c == "add_point":
            e = ms.AddPoint(_pt(*cmd["point"]))
            return _finish(e, cmd)

        # ---------------- 图面标准（表对象）----------------
        # 复刻一套既有图纸的标准，第一步就是把它真实用到的图层/块/样式读出来，
        # 而不是凭印象另建一套 —— 后者做出来永远「像但不是」。
        if c == "tables":
            from win32com.client import dynamic as _dyn
            out = {}

            if cmd.get("layers", True):
                lyr = []
                for i in range(int(doc.Layers.Count)):
                    try:
                        L = _dyn.Dispatch(doc.Layers.Item(i))
                        lyr.append({
                            "name": str(L.Name),
                            "color": int(L.Color),
                            "linetype": str(L.Linetype),
                            "lineweight": int(L.Lineweight),
                            "plottable": bool(L.Plottable),
                            # 从既有图纸当模板时，图层开关状态会一并带过来 ——
                            # 被关掉的图层上画什么都是「看不见」，很容易误判成没画上
                            "on": bool(L.LayerOn),
                            "frozen": bool(L.Freeze),
                            "locked": bool(L.Lock),
                        })
                    except Exception:
                        pass
                out["layers"] = lyr

            if cmd.get("blocks"):
                blk = []
                for i in range(int(doc.Blocks.Count)):
                    try:
                        B = doc.Blocks.Item(i)
                        nm = str(B.Name)
                        if nm.startswith("*"):      # 跳过 *Model_Space 等匿名块
                            continue
                        blk.append({"name": nm,
                                    "count": int(B.Count),
                                    "is_layout": bool(B.IsLayout)})
                    except Exception:
                        pass
                out["blocks"] = blk

            if cmd.get("textstyles"):
                ts = []
                for i in range(int(doc.TextStyles.Count)):
                    try:
                        T = _dyn.Dispatch(doc.TextStyles.Item(i))
                        ts.append({"name": str(T.Name),
                                   "font": str(T.fontFile),
                                   "height": float(T.Height),
                                   "width": float(T.Width)})
                    except Exception:
                        pass
                out["textstyles"] = ts

            if cmd.get("dimstyles"):
                ds = []
                for i in range(int(doc.DimStyles.Count)):
                    try:
                        D = _dyn.Dispatch(doc.DimStyles.Item(i))
                        ds.append({"name": str(D.Name)})
                    except Exception:
                        pass
                out["dimstyles"] = ds

            return {"ok": True, **out}

        if c == "attrs":
            """读块引用的属性（图签栏那些格子都是属性，不是普通文字）。"""
            br = doc.HandleToObject(str(cmd["handle"]))
            out = []
            try:
                for a in br.GetAttributes():
                    out.append({"tag": str(a.TagString),
                                "value": str(a.TextString),
                                "prompt": str(a.PromptString)})
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": True, "count": len(out), "attributes": out}

        if c == "setattrs":
            """按 tag 填块属性值。填完必须 Update()，否则图上不刷新。"""
            br = doc.HandleToObject(str(cmd["handle"]))
            want = dict(cmd.get("values") or {})
            done, missing = [], list(want)
            try:
                atts = br.GetAttributes()
            except Exception as e:
                return {"ok": False, "error": "取属性失败：%s" % e}
            for a in atts:
                t = str(a.TagString)
                if t in want:
                    try:
                        a.TextString = str(want[t])
                        done.append(t)
                        if t in missing:
                            missing.remove(t)
                    except Exception:
                        pass
            try:
                br.Update()
            except Exception:
                pass
            return {"ok": True, "set": done, "not_found": missing}

        if c == "activestyle":
            """把已存在的文字样式设为当前，**不动它的字体**。

            标准图里的 PM-TEXT / STYLE2 / HZTXT 都是配好的，直接切过去用，
            比自己新建样式更贴近原图（字体文件、字宽都跟着走）。
            """
            name = str(cmd["name"])
            try:
                ts = doc.TextStyles.Item(name)
            except Exception as e:
                return {"ok": False, "error": "没有文字样式 %r：%s" % (name, e)}
            doc.ActiveTextStyle = ts
            return {"ok": True, "name": str(ts.Name)}

        if c == "blocktexts":
            """只取块定义里的文字（含位置/字高）。

            图框块有一万多个图元，全量拉回来太重；而填图签栏只需要知道
            各标签（项目名称、图名、设计号…）在哪一行。
            """
            B = doc.Blocks.Item(str(cmd["name"]))
            out = []
            for i in range(int(B.Count)):
                try:
                    e = dynamic.Dispatch(B.Item(i))
                    nm = str(e.ObjectName)
                    if not (nm.endswith("Text") or nm.endswith("MText")):
                        continue
                    out.append({"text": str(e.TextString),
                                "at": list(e.InsertionPoint),
                                "h": float(getattr(e, "Height", 0) or 0)})
                except Exception:
                    continue
            return {"ok": True, "name": str(B.Name), "count": len(out),
                    "texts": out}

        if c == "blockbbox":
            """算块定义里所有图元的坐标范围。

            块的原点常常不在内容上（这套图框就是 —— 插到 (0,0) 后图元落在很远处），
            所以放置前必须先把真实范围量出来。
            块引用上的 GeometricExtents 对含属性的块会报「范围无效」，只能自己扫。
            """
            B = doc.Blocks.Item(str(cmd["name"]))
            xs, ys = [], []
            names = []
            for i in range(int(B.Count)):
                try:
                    e = dynamic.Dispatch(B.Item(i))
                    nm = str(e.ObjectName)
                    names.append(nm)
                except Exception:
                    continue
                try:
                    if nm.endswith("Line"):
                        for p in (e.StartPoint, e.EndPoint):
                            xs.append(p[0]); ys.append(p[1])
                    elif nm.endswith("Circle"):
                        c0 = e.Center
                        r = float(e.Radius)
                        xs += [c0[0] - r, c0[0] + r]
                        ys += [c0[1] - r, c0[1] + r]
                    elif "Polyline" in nm:
                        co = list(e.Coordinates)
                        if nm.endswith("AcDb3dPolyline"):
                            xs += co[0::3]; ys += co[1::3]
                        elif nm.endswith("AcDb2dPolyline"):
                            xs += co[0::3]; ys += co[1::3]
                        else:
                            xs += co[0::2]; ys += co[1::2]
                    elif nm.endswith("Text") or nm.endswith("MText"):
                        p = e.InsertionPoint
                        xs.append(p[0]); ys.append(p[1])
                    elif nm.endswith("Point"):
                        p = e.Coordinates
                        xs.append(p[0]); ys.append(p[1])
                except Exception:
                    continue
            if not xs:
                import collections as _c
                return {"ok": False, "error": "块 %s 里量不到坐标" % cmd["name"],
                        "sample_names": list(_c.Counter(names).items())[:8],
                        "scanned": len(names)}
            return {"ok": True, "name": str(B.Name),
                    "min": [min(xs), min(ys)], "max": [max(xs), max(ys)],
                    "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                    "scanned": int(B.Count)}

        if c == "blockinfo":
            """读某个块定义里的图元构成 —— 判断图框栏里都是什么。"""
            B = doc.Blocks.Item(str(cmd["name"]))
            items = []
            for i in range(int(B.Count)):
                try:
                    items.append(_entity_info(B.Item(i)))
                except Exception:
                    pass
            try:
                base = list(B.Origin)
            except Exception:
                base = None
            return {"ok": True, "name": str(B.Name), "count": len(items),
                    "origin": base, "entities": items}

        if c == "insert":
            pt = cmd.get("point", [0, 0, 0])
            br = ms.InsertBlock(_pt(*pt), str(cmd["name"]),
                                float(cmd.get("xscale", 1.0)),
                                float(cmd.get("yscale", 1.0)),
                                float(cmd.get("zscale", 1.0)),
                                float(cmd.get("rotation", 0.0)))
            out = {"ok": True, "handle": br.Handle, "name": str(br.Name)}
            db = dynamic.Dispatch(br)
            if cmd.get("layer"):
                db.Layer = str(cmd["layer"])
            if cmd.get("color") is not None:
                db.Color = int(cmd["color"])
            return out

        if c == "erase_all":
            """清空模型空间。**如实回报失败** —— 早先这里 `except: pass`
            把删除失败全吞了，报「erased: 1685」但其实只删掉一部分，
            残留的图元混在新图里，看起来像是画错了。"""
            n = int(ms.Count)
            failed, first_err = 0, None
            for i in range(n - 1, -1, -1):
                try:
                    ms.Item(i).Delete()
                except Exception as e:
                    failed += 1
                    if first_err is None:
                        first_err = str(e)
            left = int(ms.Count)
            out = {"ok": failed == 0, "before": n, "after": left,
                   "erased": n - left, "failed": failed}
            if failed:
                out["error"] = "有 %d 个图元删不掉：%s" % (failed, first_err)
            return out

        # ---------------- 图层 / 线型 / 填充 ----------------
        # 复刻工程图标准要用：图层表（名/线型/颜色）和图案填充是那套图纸的骨架。
        #
        # 注意：IAcadLayer / IAcadHatch 和 IAcad3DSolid 一样，**早绑定包装里
        # 不带 Color**，必须 dynamic.Dispatch 迟绑定。这个坑在三维实体、
        # 尺寸标注、图层、填充上已经踩到第四次了，凡是设属性一律走迟绑定。
        if c == "layer":
            name = str(cmd["name"])
            try:
                ly = doc.Layers.Item(name)
            except Exception:
                ly = doc.Layers.Add(name)
            dly = dynamic.Dispatch(ly)
            if cmd.get("color") is not None:
                dly.Color = int(cmd["color"])
            if cmd.get("linetype"):
                lt = str(cmd["linetype"])
                if lt.lower() != "continuous":
                    # 线型没加载就先用着 Continuous，别让整条指令失败
                    try:
                        doc.Linetypes.Item(lt)
                    except Exception:
                        try:
                            doc.Linetypes.Load(
                                lt, str(cmd.get("linetype_file", "acad.lin")))
                        except Exception:
                            lt = "Continuous"
                try:
                    dly.Linetype = lt
                except Exception:
                    pass
            if cmd.get("active"):
                doc.ActiveLayer = ly
            out = {"ok": True, "name": str(dly.Name)}
            for k in ("Linetype", "Color"):
                try:
                    out[k.lower()] = getattr(dly, k)
                except Exception:
                    pass
            return out

        if c == "layers":
            return {"ok": True}

        if c == "linetype":
            name = str(cmd["name"])
            f = str(cmd.get("file", "acad.lin"))
            try:
                doc.Linetypes.Load(name, f)
            except Exception as e:
                # 已经加载过也会报错，不当成失败
                return {"ok": True, "name": name, "note": str(e)[:120]}
            return {"ok": True, "name": name}

        if c == "hatch":
            geo = doc.HandleToObject(str(cmd["boundary"]))
            # 0 = 预定义（.pat 里的图案），1 = 用户自定义，2 = 自定义
            ptype = int(cmd.get("pattern_type", 0))
            pat = str(cmd.get("pattern", "ANSI31"))
            try:
                h = ms.AddHatch(ptype, pat, bool(cmd.get("associative", True)))
            except Exception as e:
                return {"ok": False, "error": "填充图案 %r 不可用：%s" % (pat, e)}
            for k, attr in (("scale", "PatternScale"), ("angle", "PatternAngle")):
                if cmd.get(k) is not None:
                    try:
                        setattr(h, attr, float(cmd[k]))
                    except Exception:
                        pass
            try:
                h.AppendOuterLoop(_arr_dispatch([geo]))
                h.Evaluate()
            except Exception as e:
                try:
                    h.Delete()
                except Exception:
                    pass
                return {"ok": False, "error": "填充边界失败：%s" % e}
            out = {"ok": True, "handle": h.Handle}
            # 颜色/图层放最后设：有些属性会触发重算，先设容易被覆盖
            dh = dynamic.Dispatch(h)
            if cmd.get("layer"):
                dh.Layer = str(cmd["layer"])
            if cmd.get("color") is not None:
                dh.Color = int(cmd["color"])
            try:
                out["area"] = float(h.Area)
            except Exception:
                pass
            return out

        # ---------------- 尺寸标注 ----------------
        # 走 COM 的 AddDim*，而不是 sendcommand 敲 DIMLINEAR ——
        # 后者会停在命令行等输入，把 AutoCAD 卡成忙态（见使用指南 §8 约束 7）。
        if c == "add_dim":
            mode = str(cmd.get("mode", "rotated")).lower()
            p1, p2 = _pt(*cmd["p1"]), _pt(*cmd["p2"])
            if mode == "aligned":
                d = ms.AddDimAligned(p1, p2, _pt(*cmd["loc"]))
            elif mode == "rotated":
                d = ms.AddDimRotated(p1, p2, _pt(*cmd["loc"]),
                                     float(cmd.get("angle", 0.0)))
            else:
                return {"ok": False,
                        "error": "mode 只支持 aligned / rotated，收到 %r" % mode}

            out = {"ok": True, "handle": d.Handle, "object": d.ObjectName}
            try:
                out["measurement"] = float(d.Measurement)
            except Exception:
                pass

            # 尺寸也是普通图元，颜色/图层照样能改。
            # 注意尺寸对象和三维实体一样：早绑定包装里未必有 Color，走迟绑定。
            if (cmd.get("color") is not None or cmd.get("layer")):
                dd = dynamic.Dispatch(d)
                if cmd.get("color") is not None:
                    dd.Color = int(cmd["color"])
                if cmd.get("layer"):
                    dd.Layer = str(cmd["layer"])
            if cmd.get("text_height") is not None:
                try:
                    d.TextHeight = float(cmd["text_height"])
                except Exception:
                    pass
            return out

        if c == "dimstyle":
            # 改当前标注样式。颜色走 DIMCLRD，是「尺寸线颜色」的专用系统变量，
            # 想只把尺寸线染绿而不动文字就用它。
            doc.SetVariable("DIMCLRD", int(cmd["color"]))
            return {"ok": True}

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
            try:
                ts = doc.TextStyles.Item(name)
            except Exception:
                ts = doc.TextStyles.Add(name)
            if cmd.get("font") is not None:
                font = str(cmd["font"])
                charset = int(cmd.get("charset", 134))  # 134 = GB2312_CHARSET
                # TrueType 要传**字体名**（SimHei），传文件名（simhei.ttf）会报「输入无效」
                ok = False
                try:
                    ts.SetFont(font, bool(cmd.get("bold", False)),
                               bool(cmd.get("italic", False)), charset, 0)
                    ok = True
                except Exception:
                    ok = False
                # SHX 走不通 SetFont（实测 gbenor.shx / gbcbig.shx 一律「输入无效」），
                # 直接写 fontFile 属性才行
                if not ok:
                    try:
                        ts.fontFile = font
                        ok = True
                    except Exception as e:
                        return {"ok": False,
                                "error": "设置字体失败（SetFont 与 fontFile 都不接受 %r）：%s"
                                         % (font, e)}
            # 中文字体是「西文 SHX + 大字库 SHX」两件套，只设前一个中文照样不显示
            if cmd.get("bigfont") is not None:
                try:
                    ts.BigFontFile = str(cmd["bigfont"])
                except Exception:
                    pass
            try:
                ts.Height = float(cmd.get("height", 0.0))   # 0 = 高度不固定
                ts.Width = float(cmd.get("width", 1.0))
            except Exception:
                pass
            doc.ActiveTextStyle = ts
            out = {"ok": True, "name": str(ts.Name)}
            try:
                out["font"] = str(ts.fontFile)
                out["bigfont"] = str(ts.BigFontFile)
            except Exception:
                pass
            return out

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
