# -*- coding: utf-8 -*-
"""CadBridge 图形控制台（tkinter）。

定位：**CLI 的一层皮，不是另一套实现**。所有实际操作都走
``protocol.request`` → 桥接进程 → AutoCAD，GUI 自己绝不碰 COM ——
第二路 COM 连接会把 AutoCAD 卡进 RPC_E_CALL_REJECTED，这是本项目最贵的故障。

线程规则：tkinter 只能在主线程碰控件。耗时的操作（启动桥接要拉起 AutoCAD，
可能几十秒）一律丢到工作线程，结果经队列回主线程用 ``after()`` 消费。

选 tkinter 是因为它是标准库：不加依赖、PyInstaller 打包也不折腾。
"""

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import ttk

from . import __version__, config, daemon, doctor, paths, protocol

# 中文字体优先级（Windows 上雅黑最好看）
_PREFERRED_FONTS = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "TkDefaultFont"]

LEVEL_TAG = {doctor.OK: "ok", doctor.WARN: "warn", doctor.FAIL: "fail"}
LEVEL_TEXT = {doctor.OK: "正常", doctor.WARN: "注意", doctor.FAIL: "故障"}


def gather_status():
    """查桥接状态（含实体数）。返回 dict；桥接没跑则返回 None。

    刻意不碰任何控件，纯函数 —— 这样能脱离 Tk 写回归测试。
    早先这段逻辑内联在 refresh_status 里，写成了
    ``protocol.request(..., state=st)``，而 ``request()`` 并没有 ``state``
    参数（那是 ``send()`` 的），抛出的 TypeError 被 except 吞掉，
    于是实体数永远不显示、还查不出原因。
    """
    st = protocol.live_state()
    if not st:
        return None
    st = dict(st)
    try:
        r = protocol.request({"cmd": "count"}, timeout=60)
        if r.get("ok"):
            st["entities"] = r.get("count")
        else:
            st["note"] = "取实体数失败：%s" % r.get("error")
    except Exception as e:
        st["note"] = "取实体数失败：%s" % e
    return st


def _pick_font(root):
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families(root))
    except Exception:
        return None
    for name in _PREFERRED_FONTS:
        if name in available:
            return name
    return None


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        self.grid(row=0, column=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        self._q = queue.Queue()
        self._busy = False          # 有用户发起的操作在跑（会禁用按钮）
        self._refreshing = False    # 有后台刷新在跑（不打扰界面）
        self._auto = tk.BooleanVar(value=True)

        self._build_style()
        self._build_header()
        self._build_toolbar()
        self._build_tabs()
        self._build_statusbar()

        self._pump()
        self.refresh_status(silent=True)      # 启动时静默查一次，不打扰界面
        if self._auto.get():
            self._schedule_auto()

    # ------------------------------------------------------------ 外观
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        fam = _pick_font(self)
        if fam:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                         "TkHeadingFont", "TkTooltipFont"):
                try:
                    from tkinter import font as tkfont
                    f = tkfont.nametofont(name)
                    f.configure(family=fam, size=9)
                except Exception:
                    pass

    def _build_header(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        self.dot = tk.Canvas(bar, width=14, height=14, highlightthickness=0)
        self.dot.grid(row=0, column=0, padx=(2, 6))
        self._dot_id = self.dot.create_oval(2, 2, 12, 12, fill="#b0b0b0", outline="")

        self.headline = ttk.Label(bar, text="正在检查…", font=("", 11, "bold"))
        self.headline.grid(row=0, column=1, sticky="w")

        self.subline = ttk.Label(bar, text="", foreground="#666")
        self.subline.grid(row=0, column=1, sticky="w", pady=(18, 0))

        ttk.Separator(self).grid(row=1, column=0, sticky="ew", pady=8)

    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")

        # 所有会发起操作的按钮都登记进来：忙的时候统一禁用。
        # 早先只是靠 _bg() 里的 `if self._busy: return` 挡着，结果是
        # 点击被**静默吞掉** —— 自动刷新每 5 秒一次，用户点「启动桥接」
        # 恰好撞上就会「按了没反应」，且没有任何提示。
        self.action_buttons = []

        def add_btn(col, text, cmd, pad=(0, 6)):
            b = ttk.Button(bar, text=text, command=cmd)
            b.grid(row=0, column=col, padx=pad)
            self.action_buttons.append(b)
            return b

        self.btn_start = add_btn(0, "启动桥接", self.on_start)
        self.btn_stop = add_btn(1, "停止桥接", self.on_stop)
        self.btn_doctor = add_btn(2, "自检", self.on_doctor)
        self.btn_refresh = add_btn(3, "刷新", self.refresh_status, pad=(0, 16))

        ttk.Checkbutton(bar, text="自动刷新", variable=self._auto,
                        command=self._on_auto_toggle).grid(row=0, column=4)

        self.spinner = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.spinner.grid(row=0, column=5, padx=(16, 0), sticky="w")

        self.busy_label = ttk.Label(bar, text="", foreground="#0a6")
        self.busy_label.grid(row=0, column=6, padx=(8, 0), sticky="w")

    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.grid(row=3, column=0, sticky="nsew", pady=(10, 6))
        self.rowconfigure(3, weight=1)
        self.columnconfigure(0, weight=1)

        self._tab_status()
        self._tab_draw()
        self._tab_console()
        self._tab_log()

    def _tab_status(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="  状态  ")
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(f, columns=("lvl", "item", "detail"),
                                 show="headings", selectmode="browse")
        self.tree.heading("lvl", text="级别")
        self.tree.heading("item", text="检查项")
        self.tree.heading("detail", text="详情")
        self.tree.column("lvl", width=70, anchor="center", stretch=False)
        self.tree.column("item", width=230, stretch=False)
        self.tree.column("detail", width=560)
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("warn", foreground="#9a6700")
        self.tree.tag_configure("fail", foreground="#c0392b")

        vs = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")

    def _tab_draw(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="  绘图  ")
        f.columnconfigure(1, weight=1)

        self.shape = tk.StringVar(value="直线")
        ttk.Label(f, text="图形").grid(row=0, column=0, sticky="w", pady=4)
        cb = ttk.Combobox(f, textvariable=self.shape, state="readonly", width=12,
                          values=["直线", "圆", "文字", "多段线矩形"])
        cb.grid(row=0, column=1, sticky="w", pady=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._sync_shape_hint())

        self.hint = ttk.Label(f, text="", foreground="#666")
        self.hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.fields = {}
        self.field_labels = {}
        for i, key in enumerate(("a", "b", "c")):
            lab = ttk.Label(f, text="")
            lab.grid(row=2 + i, column=0, sticky="w", pady=3)
            e = ttk.Entry(f, width=34)
            e.grid(row=2 + i, column=1, sticky="w", pady=3)
            self.fields[key] = e
            self.field_labels[key] = lab
        self.fields["a"].insert(0, "0,0")
        self.fields["b"].insert(0, "100,100")

        row = ttk.Frame(f)
        row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 4))

        def add_btn(col, text, cmd, pad=(0, 0)):
            b = ttk.Button(row, text=text, command=cmd)
            b.grid(row=0, column=col, padx=pad)
            self.action_buttons.append(b)
            return b

        add_btn(0, "绘制", self.on_draw)
        add_btn(1, "缩放到全图",
                lambda: self._send_simple({"cmd": "zoom", "mode": "extents"}),
                pad=(6, 0))
        add_btn(2, "统计实体",
                lambda: self._send_simple({"cmd": "count"}), pad=(6, 0))

        self.draw_out = tk.Text(f, height=8, wrap="word", state="disabled",
                                relief="solid", borderwidth=1)
        self.draw_out.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        f.rowconfigure(6, weight=1)
        self._sync_shape_hint()

    def _tab_console(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="  控制台  ")
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

        self.console = tk.Text(f, wrap="word", state="disabled", relief="solid",
                               borderwidth=1)
        self.console.grid(row=0, column=0, columnspan=2, sticky="nsew")
        vs = ttk.Scrollbar(f, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=vs.set)
        vs.grid(row=0, column=2, sticky="ns")
        self.console.tag_configure("err", foreground="#c0392b")
        self.console.tag_configure("echo", foreground="#0a58ca")

        row = ttk.Frame(f)
        row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text="指令").grid(row=0, column=0, sticky="w")
        self.entry = ttk.Entry(row)
        self.entry.grid(row=1, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.on_console())
        send = ttk.Button(row, text="发送", command=self.on_console)
        send.grid(row=1, column=1, padx=(6, 0))
        self.action_buttons.append(send)
        ttk.Label(row, text="支持短命令（info / count / changes）或完整 JSON",
                  foreground="#666").grid(row=2, column=0, columnspan=2,
                                          sticky="w", pady=(4, 0))

    def _tab_log(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="  日志  ")
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

        self.logtext = tk.Text(f, wrap="none", state="disabled", relief="solid",
                               borderwidth=1)
        self.logtext.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(f, orient="vertical", command=self.logtext.yview)
        self.logtext.configure(yscrollcommand=vs.set)
        vs.grid(row=0, column=1, sticky="ns")

        row = ttk.Frame(f)
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(row, text="刷新日志", command=self.load_log).grid(row=0, column=0)
        ttk.Button(row, text="打开数据目录",
                   command=self.open_data_dir).grid(row=0, column=1, padx=6)
        self.logpath = ttk.Label(row, text=paths.log_path(), foreground="#666")
        self.logpath.grid(row=0, column=2, padx=8)

    def _build_statusbar(self):
        self.status = ttk.Label(self, text="就绪", foreground="#666", anchor="w")
        self.status.grid(row=4, column=0, sticky="ew")

    # ------------------------------------------------------- 后台任务
    def _pump(self):
        """主线程轮询工作线程的结果 —— tkinter 不能在别的线程里更新控件。"""
        try:
            while True:
                fn, result, quiet = self._q.get_nowait()
                if quiet:
                    self._refreshing = False
                else:
                    self._set_busy(False)
                if fn:
                    try:
                        fn(result)
                    except Exception:
                        traceback.print_exc()
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _bg(self, work, done=None, busy_text="处理中…", quiet=False):
        """跑一个后台任务。

        ``quiet=True`` 用于自动刷新这类**后台**任务：不占 _busy、不禁用按钮、
        不显示忙碌提示。早先所有任务共用一个 _busy，自动刷新每 5 秒就把按钮
        禁用一次（而探活又要 1.5 秒才超时），界面三成时间是「点不动」的，
        看着就像坏了。
        """
        if self._busy:
            if not quiet:
                self._say("上一个操作还没结束，请稍候…")
            return
        if quiet:
            if self._refreshing:
                return
            self._refreshing = True
        else:
            self._set_busy(True, busy_text)

        def run():
            try:
                r = work()
            except Exception as e:
                r = e
            self._q.put((done, r, quiet))

        threading.Thread(target=run, daemon=True).start()

    def _set_busy(self, busy, text=""):
        self._busy = busy
        # 忙碌时禁用操作按钮：既是反馈，也避免点击被静默丢弃
        state = "disabled" if busy else "normal"
        for b in getattr(self, "action_buttons", []):
            try:
                b.configure(state=state)
            except Exception:
                pass
        if busy:
            self.spinner.start(12)
            self.busy_label.configure(text=text)
            self.status.configure(text=text, foreground="#666")
        else:
            self.spinner.stop()
            self.busy_label.configure(text="")

    def _say(self, text, err=False):
        self.status.configure(text=text, foreground="#c0392b" if err else "#666")

    # ---------------------------------------------------------- 状态
    def _apply_status(self, info):
        """info 为 None 表示桥接没在跑。"""
        if isinstance(info, Exception) or info is None:
            self.dot.itemconfigure(self._dot_id, fill="#b0b0b0")
            self.headline.configure(text="桥接未运行")
            self.subline.configure(text="点「启动桥接」即可，AutoCAD 会自动拉起")
            self._say("桥接未运行")
            return
        self.dot.itemconfigure(self._dot_id, fill="#2da44e")
        self.headline.configure(text="桥接运行中")
        parts = []
        if info.get("acad_version"):
            parts.append("AutoCAD %s" % info["acad_version"])
        if info.get("entities") is not None:
            parts.append("%s 个实体" % info["entities"])
        if info.get("port"):
            parts.append("端口 %s" % info["port"])
        if info.get("doc"):
            parts.append(info["doc"])
        self.subline.configure(text=" · ".join(parts))
        # 状态栏必须在这里落一个最终文案：_set_busy(False) 只停转圈，
        # 不清文字，否则「正在查询状态…」会一直挂在底下。
        if info.get("note"):
            self._say(info["note"], err=True)
        else:
            self._say("已连接到桥接")

    def refresh_status(self, silent=False):
        self._bg(gather_status, self._apply_status, "正在查询状态…", quiet=silent)

    def _schedule_auto(self):
        if self._auto.get():
            self.after(5000, self._auto_tick)

    def _auto_tick(self):
        if self._auto.get() and not self._busy:
            self.refresh_status(silent=True)
        self._schedule_auto()

    def _on_auto_toggle(self):
        self._say("自动刷新已开启" if self._auto.get() else "自动刷新已关闭")

    # ---------------------------------------------------------- 动作
    def on_start(self):
        def work():
            return daemon.ensure_running()

        def done(r):
            if isinstance(r, Exception):
                self._say("启动失败：%s" % r, err=True)
            else:
                self._say("桥接已就绪")
            self.refresh_status()

        # 首次启动要拉起 AutoCAD，给足时间
        self._bg(work, done, "正在启动桥接（首次需拉起 AutoCAD，可能要几十秒）…")

    def on_stop(self):
        def work():
            return daemon.stop()

        def done(r):
            if isinstance(r, Exception):
                self._say("停止失败：%s" % r, err=True)
            else:
                self._say("桥接已停止（AutoCAD 保留运行）")
            self.refresh_status()

        self._bg(work, done, "正在停止桥接…")

    def on_doctor(self):
        def work():
            return doctor.run(deep=False)

        def done(rep):
            if isinstance(rep, Exception):
                self._say("自检失败：%s" % rep, err=True)
                return
            self.tree.delete(*self.tree.get_children())
            for level, title, detail in rep.items:
                self.tree.insert("", "end", values=(LEVEL_TEXT[level], title, detail),
                                 tags=(LEVEL_TAG[level],))
            summary = {doctor.OK: "一切正常", doctor.WARN: "可用，但有需注意项",
                       doctor.FAIL: "存在故障，见红色项"}[rep.worst]
            self._say("自检完成：" + summary,
                      err=(rep.worst == doctor.FAIL))
            self.nb.select(0)

        self._bg(work, done, "正在自检…")

    # ---------------------------------------------------------- 绘图
    def _sync_shape_hint(self):
        s = self.shape.get()
        spec = {
            "直线": (("起点 x,y", "终点 x,y", "（不使用）"), "两点画直线"),
            "圆": (("圆心 x,y", "半径（数字）", "（不使用）"), "圆心 + 半径画圆"),
            "文字": (("插入点 x,y", "字高（数字，可留空）", "文字内容"),
                     "写单行文字；中文可直接用（会自动建好字体样式）"),
            "多段线矩形": (("左下角 x,y", "右上角 x,y", "（不使用）"),
                          "按左下 / 右上两点画闭合矩形"),
        }
        labels, hint = spec.get(s, (("参数 1", "参数 2", "参数 3"), ""))
        for key, text in zip(("a", "b", "c"), labels):
            self.field_labels[key].configure(text=text)
        self.hint.configure(text=hint)

    def _parse_pt(self, s):
        vals = []
        for part in s.replace(" ", ",").split(","):
            if part.strip():
                vals.append(float(part))
        if not vals:
            raise ValueError("坐标不能为空")
        while len(vals) < 3:
            vals.append(0.0)
        return vals[:3]

    def on_draw(self):
        s = self.shape.get()
        a = self.fields["a"].get()
        b = self.fields["b"].get()
        c = self.fields["c"].get()

        try:
            if s == "直线":
                req = {"cmd": "add_line", "start": self._parse_pt(a),
                       "end": self._parse_pt(b)}
            elif s == "圆":
                req = {"cmd": "add_circle", "center": self._parse_pt(a),
                       "radius": float(b)}
            elif s == "文字":
                if not c.strip():
                    raise ValueError("文字内容不能为空")
                req = {"cmd": "add_text", "text": c,
                       "insert": self._parse_pt(a), "height": float(b or 2.5)}
            elif s == "多段线矩形":
                p1, p2 = self._parse_pt(a), self._parse_pt(b)
                req = {"cmd": "add_polyline", "closed": True,
                       "points": [[p1[0], p1[1]], [p2[0], p1[1]],
                                  [p2[0], p2[1]], [p1[0], p2[1]]]}
            else:
                raise ValueError("未知图形")
        except ValueError as e:
            self._draw_log("参数错误：%s" % e, err=True)
            return

        # 画中文前先确保有可用的 TrueType 样式（默认 Standard 是 SHX，中文会变 ?）
        def work():
            if s == "文字":
                protocol.request({"cmd": "textstyle", "name": "CadBridge",
                                  "font": "SimHei"}, timeout=60)
            return protocol.request(req)

        def done(r):
            if isinstance(r, Exception):
                self._draw_log("失败：%s" % r, err=True)
            elif not r.get("ok"):
                self._draw_log("失败：%s" % r.get("error"), err=True)
            else:
                self._draw_log("已绘制 %s，句柄 %s" % (s, r.get("handle") or "-"))
            self.refresh_status()

        self._bg(work, done, "正在绘制…")

    def _draw_log(self, text, err=False):
        self.draw_out.configure(state="normal")
        self.draw_out.insert("end", text + "\n", ("err",) if err else ())
        self.draw_out.see("end")
        self.draw_out.configure(state="disabled")
        self._say(text, err=err)

    def _send_simple(self, req):
        def work():
            return protocol.request(req)

        def done(r):
            if isinstance(r, Exception):
                self._draw_log("失败：%s" % r, err=True)
            else:
                self._draw_log("返回：%s" % r)
            self.refresh_status()

        self._bg(work, done, "正在执行…")

    # -------------------------------------------------------- 控制台
    def on_console(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._console_log("> " + text, tag="echo")

        if text.startswith("{"):
            import json
            try:
                req = json.loads(text)
            except ValueError as e:
                self._console_log("JSON 解析失败：%s" % e, err=True)
                return
        else:
            req = {"cmd": text}

        def work():
            return protocol.request(req)

        def done(r):
            if isinstance(r, Exception):
                self._console_log("失败：%s" % r, err=True)
            else:
                import json
                self._console_log(json.dumps(r, ensure_ascii=False, indent=2),
                                  err=not r.get("ok"))
            self.refresh_status()

        self._bg(work, done, "正在执行…")

    def _console_log(self, text, err=False, tag=None):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n", (tag or ("err" if err else ""),))
        self.console.see("end")
        self.console.configure(state="disabled")

    # ------------------------------------------------------------ 日志
    def load_log(self):
        p = paths.log_path()
        self.logpath.configure(text=p)
        if not os.path.exists(p):
            self._setlog("（还没有日志文件：%s）" % p)
            return
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            self._setlog("读取日志失败：%s" % e)
            return
        self._setlog("\n".join(lines[-400:]) or "（日志为空）")

    def _setlog(self, text):
        self.logtext.configure(state="normal")
        self.logtext.delete("1.0", "end")
        self.logtext.insert("1.0", text)
        self.logtext.see("end")
        self.logtext.configure(state="disabled")

    def open_data_dir(self):
        d = paths.data_dir()
        try:
            os.startfile(d)          # noqa: S606 - Windows 专用，打开资源管理器
        except Exception as e:
            self._say("打开目录失败：%s" % e, err=True)


def run():
    """启动 GUI 主循环。"""
    root = tk.Tk()
    root.title("CadBridge 控制台  v%s" % __version__)
    root.geometry("980x660")
    root.minsize(820, 560)
    try:
        root.iconbitmap(default=os.path.join(paths.install_dir(),
                                             "assets", "cadbridge.ico"))
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
