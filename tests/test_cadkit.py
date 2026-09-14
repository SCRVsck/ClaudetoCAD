# -*- coding: utf-8 -*-
"""CadBridge 回归测试（不依赖 AutoCAD，随时可跑）。

    python -m unittest discover -s tests -v
或
    python tests/test_cadkit.py

这里覆盖的都是**踩过的坑**，不是凑覆盖率：
- 注册表 LocalServer32 里不带引号且路径含空格（曾导致定位不到 acad.exe）
- 冻结 / 源码两种模式下 argv 起点不同（曾导致打包版所有子命令失效）
- config 缺字段 / 文件损坏都要能退回默认值
- 单实例锁必须真的互斥（曾因 truncate 把锁截掉而形同虚设）
"""

import json
import os
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadkit import acad, cli, config, doctor, paths, protocol  # noqa: E402
from cadkit import daemon  # noqa: E402


class TempHome(unittest.TestCase):
    """把数据目录指向临时目录，避免污染真实用户目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CADBRIDGE_HOME")
        os.environ["CADBRIDGE_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CADBRIDGE_HOME", None)
        else:
            os.environ["CADBRIDGE_HOME"] = self._old
        self._tmp.cleanup()


class TestPaths(TempHome):
    def test_data_dir_honours_override(self):
        self.assertEqual(paths.data_dir(), os.path.abspath(self._tmp.name))

    def test_data_dir_created(self):
        self.assertTrue(os.path.isdir(paths.data_dir()))

    def test_derived_paths_live_in_data_dir(self):
        for p in (paths.state_path(), paths.config_path(),
                  paths.log_path(), paths.events_path(), paths.lock_path()):
            self.assertEqual(os.path.dirname(p), paths.data_dir())

    def test_install_dir_is_not_data_dir(self):
        # 安装目录（只读）与数据目录（可写）必须分开 —— 打包后前者在临时解包目录
        self.assertNotEqual(paths.install_dir(), paths.data_dir())


class TestAcadPathParsing(unittest.TestCase):
    """注册表 LocalServer32 的值形态不统一，这是实测踩到的坑。"""

    def test_quoted_path(self):
        raw = '"D:\\Programs\\cad22\\acad.exe" /Automation'
        self.assertEqual(acad._split_server_path(raw), "D:\\Programs\\cad22\\acad.exe")

    def test_unquoted_path_with_spaces(self):
        # 本机实测就是这个形态；早先按空格切第一段会得到不存在的
        # "D:\Programs\cad22\AutoCAD"
        raw = "D:\\Programs\\cad22\\AutoCAD 2022\\acad.exe /Automation"
        self.assertEqual(acad._split_server_path(raw),
                         "D:\\Programs\\cad22\\AutoCAD 2022\\acad.exe")

    def test_path_without_args(self):
        raw = "C:\\ACAD\\acad.exe"
        self.assertEqual(acad._split_server_path(raw), "C:\\ACAD\\acad.exe")

    def test_empty(self):
        self.assertIsNone(acad._split_server_path(""))

    def test_nonexistent_falls_back_to_first_token(self):
        raw = "Z:\\nope\\acad.exe /Automation"
        self.assertEqual(acad._split_server_path(raw), "Z:\\nope\\acad.exe")


class TestAcadProgids(unittest.TestCase):
    def test_progid_list_is_ordered_newest_first(self):
        vers = [v for _, v in acad.PROGIDS]
        years = [int(v) for v in vers if v.isdigit()]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_registered_progids_shape(self):
        for progid, ver in acad.registered_progids():
            self.assertTrue(progid.startswith("AutoCAD.Application"))


class TestConfig(TempHome):
    def test_defaults_when_missing(self):
        cfg = config.load()
        self.assertEqual(cfg, config.DEFAULTS)

    def test_roundtrip(self):
        config.set("retries", 3)
        self.assertEqual(config.load()["retries"], 3)
        self.assertEqual(config.get("retries"), 3)

    def test_unknown_key_rejected(self):
        with self.assertRaises(KeyError):
            config.set("nonsense", 1)

    def test_corrupt_file_falls_back(self):
        with open(paths.config_path(), "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        self.assertEqual(config.load(), config.DEFAULTS)

    def test_partial_file_merges_with_defaults(self):
        with open(paths.config_path(), "w", encoding="utf-8") as f:
            json.dump({"retries": 2}, f)
        cfg = config.load()
        self.assertEqual(cfg["retries"], 2)
        # 没写的字段仍要有默认值
        self.assertEqual(cfg["request_timeout"], config.DEFAULTS["request_timeout"])

    def test_unknown_fields_ignored(self):
        with open(paths.config_path(), "w", encoding="utf-8") as f:
            json.dump({"retries": 2, "bogus": "x"}, f)
        self.assertNotIn("bogus", config.load())


class TestProtocolState(TempHome):
    def test_missing_state_is_none(self):
        self.assertIsNone(protocol.read_state())

    def test_corrupt_state_is_none(self):
        with open(paths.state_path(), "w", encoding="utf-8") as f:
            f.write("garbage")
        self.assertIsNone(protocol.read_state())

    def test_state_without_port_is_none(self):
        protocol.write_state({"pid": 1})
        self.assertIsNone(protocol.read_state())

    def test_roundtrip(self):
        protocol.write_state({"port": 1234, "pid": 99})
        st = protocol.read_state()
        self.assertEqual(st["port"], 1234)

    def test_dead_port_not_alive(self):
        # 端口 1 几乎不可能有人监听
        self.assertFalse(protocol.is_alive({"port": 1}))

    def test_is_alive_fails_fast(self):
        """探活死端口必须快速失败。

        这是自动刷新反复走的热路径：早先超时给到 1.5s，界面就三成时间
        处在「忙碌」状态（按钮被禁用），看起来像坏了。
        """
        import socket as _s
        import time
        s = _s.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                      # 端口随即关闭，确定无人监听
        t = time.time()
        self.assertFalse(protocol.is_alive({"port": port}))
        elapsed = time.time() - t
        self.assertLess(elapsed, 1.0,
                        "探活耗时 %.2fs，太慢，会拖垮界面刷新" % elapsed)

    def test_is_alive_false_for_none(self):
        self.assertFalse(protocol.is_alive(None))

    def test_live_state_none_when_dead(self):
        protocol.write_state({"port": 1, "pid": 1})
        self.assertIsNone(protocol.live_state())

    def test_clear_state(self):
        protocol.write_state({"port": 1})
        protocol.clear_state()
        self.assertIsNone(protocol.read_state())


class TestSingleInstance(TempHome):
    def test_second_acquire_fails(self):
        a = daemon.SingleInstance()
        b = daemon.SingleInstance()
        self.assertTrue(a.acquire())
        try:
            self.assertFalse(b.acquire(), "第二个实例不该拿到锁")
        finally:
            a.release()

    def test_lock_released_allows_reacquire(self):
        a = daemon.SingleInstance()
        self.assertTrue(a.acquire())
        a.release()
        b = daemon.SingleInstance()
        self.assertTrue(b.acquire())
        b.release()


class TestDoctor(unittest.TestCase):
    def test_report_worst_level(self):
        r = doctor.Report()
        self.assertEqual(r.worst, doctor.OK)
        r.add(doctor.WARN, "w")
        self.assertEqual(r.worst, doctor.WARN)
        r.add(doctor.FAIL, "f")
        self.assertEqual(r.worst, doctor.FAIL)

    def test_render_includes_titles_and_detail(self):
        r = doctor.Report()
        r.add(doctor.OK, "标题", "细节")
        out = r.render()
        self.assertIn("标题", out)
        self.assertIn("细节", out)

    def test_non_deep_run_returns_report(self):
        r = doctor.run(deep=False)
        self.assertIsInstance(r, doctor.Report)
        self.assertTrue(r.items)


class TestCli(TempHome):
    def test_point_parsing_2d(self):
        self.assertEqual(cli._pt("1,2"), [1.0, 2.0, 0.0])

    def test_point_parsing_3d(self):
        self.assertEqual(cli._pt("1,2,3"), [1.0, 2.0, 3.0])

    def test_point_parsing_spaces(self):
        self.assertEqual(cli._pt("1 2 3"), [1.0, 2.0, 3.0])

    def test_all_subcommands_registered(self):
        p = cli.build_parser()
        subs = p.get_default("_subcommands")
        for name in ("doctor", "info", "start", "stop", "status", "config",
                     "line", "circle", "text", "count", "entities",
                     "changes", "zoom", "textstyle", "save", "raw"):
            self.assertIn(name, subs)

    def test_parser_accepts_key_subcommands(self):
        p = cli.build_parser()
        for argv in (["doctor"], ["status"], ["line", "0,0", "1,1"],
                     ["circle", "0,0", "5"], ["config", "retries"],
                     ["text", "hi"], ["zoom", "extents"]):
            ns = p.parse_args(argv)
            self.assertTrue(callable(getattr(ns, "func", None)),
                            "子命令 %s 没有绑定处理函数" % argv[0])

    def test_bare_json_is_not_a_subcommand(self):
        p = cli.build_parser()
        subs = p.get_default("_subcommands")
        self.assertNotIn('{"cmd":"count"}', subs)


class TestServerBuffer(unittest.TestCase):
    """缓冲区分行处理：探活连接与空行绝不能触发任何指令。"""

    def _srv(self, token="t" * 64):
        from cadkit import server
        s = server.BridgeServer.__new__(server.BridgeServer)
        s.app = s.doc = None
        s.cfg = {}
        s.token = token
        s.log = lambda m: None
        s.handled = []
        s._dispatch_with_retry = lambda req: (s.handled.append(req),
                                              {"ok": True})[1]
        return s

    def _line(self, cmd, token="t" * 64):
        import json
        return (json.dumps({"cmd": cmd, protocol.TOKEN_FIELD: token}) + "\n").encode()

    def test_probe_connection_triggers_nothing(self):
        """连上就关（探活）不该触发任何处理。"""
        srv = self._srv()
        sent = []
        self.assertFalse(srv._process_buffer(bytearray(), sent.append))
        self.assertEqual(srv.handled, [])
        self.assertEqual(sent, [])

    def test_blank_lines_triggers_nothing(self):
        srv = self._srv()
        sent = []
        srv._process_buffer(bytearray(b"\n\n\n"), sent.append)
        self.assertEqual(srv.handled, [], "空行不该被当成指令")
        self.assertEqual(sent, [])

    def test_multiple_requests_in_one_packet(self):
        srv = self._srv()
        sent = []
        buf = bytearray(self._line("a") + self._line("b") + self._line("c"))
        srv._process_buffer(buf, sent.append)
        self.assertEqual([r["cmd"] for r in srv.handled], ["a", "b", "c"])
        self.assertEqual(len(sent), 3)

    def test_partial_line_stays_buffered(self):
        srv = self._srv()
        sent = []
        buf = bytearray(self._line("a") + b'{"cmd":"b"')
        srv._process_buffer(buf, sent.append)
        self.assertEqual([r["cmd"] for r in srv.handled], ["a"])
        self.assertEqual(bytes(buf), b'{"cmd":"b"', "半行必须留在缓冲区里")

    def test_shutdown_stops_further_processing(self):
        srv = self._srv()
        srv._dispatch_with_retry = lambda req: {"ok": True, "shutdown": True}
        sent = []
        buf = bytearray(self._line("shutdown") + self._line("after"))
        self.assertTrue(srv._process_buffer(buf, sent.append))
        self.assertEqual(len(sent), 1, "shutdown 之后的指令不该再执行")

    def test_bad_token_rejected_without_dispatch(self):
        srv = self._srv()
        sent = []
        srv._process_buffer(bytearray(self._line("count", token="x" * 64)),
                            sent.append)
        self.assertEqual(srv.handled, [], "鉴权不过就不该走到指令分发")
        self.assertFalse(sent[0]["ok"])


class TestServerConcurrency(TempHome):
    """回归：一条空闲的长连接不能堵死其他客户端。

    客户端为省临时端口而复用长连接，而长连接大部分时间空闲。早先服务端是
    「accept 一条 → 处理到它关闭为止」，于是那条空闲连接会把整个 accept 循环
    卡住：新连接的 SYN 堆在 backlog 里，堆满就被内核丢掉 ——
    现场表现是桥接明明在监听，status 却报「桥接未运行」，绘图请求则超时。
    """

    def setUp(self):
        super().setUp()
        import threading
        from cadkit import server
        self.threads = []

        self.srv = server.BridgeServer.__new__(server.BridgeServer)
        self.srv.cfg = dict(config.DEFAULTS)
        self.srv.log = lambda m: None
        self.srv.app = self.srv.doc = None
        self.srv.info = {"mode": "test", "progid": "test", "version": "test"}
        self.srv.token = None
        self.srv.last_health = time.time()
        self.srv.connect = lambda: None          # 不碰 COM
        self.srv._ensure_alive = lambda: None
        self.srv.handle = lambda req: {"ok": True, "cmd": req.get("cmd")}

        t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        t.start()
        self.threads.append(t)

        deadline = time.time() + 10
        while time.time() < deadline and not protocol.live_state():
            time.sleep(0.05)
        self.assertTrue(protocol.live_state(), "测试用桥接没能起来")

    def tearDown(self):
        try:
            protocol.send({"cmd": "shutdown"})
        except Exception:
            pass
        protocol.close()
        for t in self.threads:
            t.join(timeout=5)
        super().tearDown()

    def test_idle_connection_does_not_block_others(self):
        # 第一条连接：连上后保持空闲（模拟 GUI 挂着的那条长连接）
        idle = socket.create_connection(("127.0.0.1", self.srv.port), timeout=5)
        try:
            time.sleep(0.3)
            # 此时第二条客户端必须仍然能被服务
            r = protocol.request({"cmd": "count"}, timeout=10)
            self.assertTrue(r["ok"], "空闲长连接把别的客户端堵住了")
            self.assertEqual(r["cmd"], "count")
        finally:
            idle.close()

    def test_second_connection_served_while_first_is_open(self):
        port = self.srv.port
        a = socket.create_connection(("127.0.0.1", port), timeout=5)
        b = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            payload = (json.dumps({"cmd": "ping", protocol.TOKEN_FIELD: self.srv.token})
                       + "\n").encode()
            for s in (a, b):
                s.sendall(payload)
            for name, s in (("a", a), ("b", b)):
                s.settimeout(10)
                buf = b""
                while b"\n" not in buf:
                    c = s.recv(65536)
                    self.assertTrue(c, "连接 %s 没有得到响应" % name)
                    buf += c
                self.assertTrue(json.loads(buf.split(b"\n")[0])["ok"],
                                "连接 %s 的响应不 ok" % name)
        finally:
            a.close()
            b.close()


class FakeBridge:
    """极简的假桥接，用来数「客户端开了几条连接」并记录收到的 token。"""

    def __init__(self):
        import socket as _s
        self.sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
        self.sock.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.requests = 0
        self.tokens = []
        self._stop = False

    def serve_forever(self):
        import socket as _s
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except (_s.timeout, OSError):
                continue
            self.connections += 1
            conn.settimeout(2.0)
            buf = b""
            try:
                while not self._stop:
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            raise ConnectionError
                        buf += chunk
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    self.requests += 1
                    self.tokens.append(json.loads(line.decode("utf-8")).get(
                        protocol.TOKEN_FIELD))
                    resp = ('{"ok":true,"n":%d,"count":%d}\n'
                            % (self.requests, self.requests)).encode("utf-8")
                    conn.sendall(resp)
            except Exception:
                pass
            finally:
                conn.close()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


class TestConnectionReuse(TempHome):
    """客户端必须复用长连接 —— 每请求一条连接会把本机临时端口耗光
    （实测 TIME_WAIT 堆到 16448 / 端口范围 16384，connect 直接报 10048）。"""

    def setUp(self):
        super().setUp()
        import threading
        self.bridge = FakeBridge()
        self.thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.thread.start()
        protocol.close()
        self.token = "t" * 64
        protocol.write_state({"port": self.bridge.port, "proto": protocol.PROTO,
                              "token": self.token})

    def tearDown(self):
        protocol.close()
        self.bridge.close()
        self.thread.join(timeout=3)
        super().tearDown()

    def test_many_requests_share_one_connection(self):
        for i in range(25):
            r = protocol.request({"cmd": "ping"})
            self.assertTrue(r["ok"])
        self.assertEqual(self.bridge.requests, 25)
        self.assertEqual(self.bridge.connections, 1,
                         "25 条请求不该开 25 条连接（实际开了 %d 条）"
                         % self.bridge.connections)

    def test_request_carries_token(self):
        protocol.request({"cmd": "ping"})
        self.assertEqual(self.bridge.tokens, [self.token],
                         "请求必须带上 state.json 里的接入 token")

    def test_reconnects_after_connection_dropped(self):
        protocol.request({"cmd": "ping"})
        self.assertEqual(self.bridge.connections, 1)
        protocol.close()                       # 模拟连接失效（如桥接重启）
        r = protocol.request({"cmd": "ping"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.bridge.connections, 2, "断线后应能重连")


class TestSpawnCmd(unittest.TestCase):
    """打包后有两个 exe，桥接必须由**控制台那个**跑。

    从 GUI 里派生 ``sys.executable --serve`` 会得到
    ``cadbridge-gui.exe --serve``，而 GUI 的 main 不解析参数、直接开窗口 ——
    结果是桥接没起来，反而弹出一堆窗口。
    """

    def _frozen_cmd(self, exe_name, cli_exists):
        import sys as _sys
        from unittest import mock
        exe = os.path.join(r"C:\apps", exe_name)

        def fake_exists(p):
            return cli_exists if p.lower().endswith("cadbridge.exe") else True

        with mock.patch.object(daemon.paths, "is_frozen", return_value=True), \
             mock.patch.object(_sys, "executable", exe), \
             mock.patch("os.path.exists", side_effect=fake_exists):
            return daemon._spawn_cmd()

    def test_cli_exe_spawns_itself(self):
        self.assertEqual(self._frozen_cmd("cadbridge.exe", True),
                         [r"C:\apps\cadbridge.exe", "--serve"])

    def test_gui_exe_prefers_sibling_cli(self):
        self.assertEqual(self._frozen_cmd("cadbridge-gui.exe", True),
                         [r"C:\apps\cadbridge.exe", "--serve"],
                         "GUI exe 必须去叫同目录的 cadbridge.exe，而不是自己")

    def test_gui_exe_alone_falls_back_to_self(self):
        self.assertEqual(self._frozen_cmd("cadbridge-gui.exe", False),
                         [r"C:\apps\cadbridge-gui.exe", "--serve"])

    def test_source_mode_runs_script(self):
        from unittest import mock
        with mock.patch.object(daemon.paths, "is_frozen", return_value=False):
            cmd = daemon._spawn_cmd()
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith("cadbridge.py"))
        self.assertEqual(cmd[2], "--serve")

    def test_gui_entry_handles_serve(self):
        """cadbridge_gui.py 收到 --serve 时必须去跑桥接，而不是开窗口。"""
        import cadbridge_gui
        from unittest import mock
        ran = []
        with mock.patch("cadkit.server.BridgeServer") as BS, \
             mock.patch.object(sys, "argv", ["cadbridge-gui.exe", "--serve"]):
            BS.return_value.serve_forever.side_effect = lambda: ran.append(1) or 0
            cadbridge_gui.main()
        self.assertEqual(ran, [1], "GUI 入口没有把 --serve 转给桥接")


class TestGuiStatus(TempHome):
    """GUI 的状态采集刻意做成不碰控件的纯函数，因此能脱离 Tk 测。

    这条测试守的是一个真实 bug：早先状态采集内联在控件方法里，写成了
    ``protocol.request(..., state=st)``，而 ``request()`` 没有 ``state``
    参数（那是 ``send()`` 的），TypeError 被 except 吞掉，
    结果实体数永远不显示且查不出原因。
    """

    def setUp(self):
        super().setUp()
        import threading
        self.bridge = FakeBridge()
        self.thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.thread.start()
        protocol.close()

    def tearDown(self):
        protocol.close()
        self.bridge.close()
        self.thread.join(timeout=3)
        super().tearDown()

    def _write_state(self):
        protocol.write_state({"port": self.bridge.port, "proto": protocol.PROTO,
                              "token": "t" * 64, "acad_version": "2022",
                              "pid": 1234})

    def test_returns_none_when_bridge_down(self):
        from cadkit import gui
        protocol.clear_state()
        self.assertIsNone(gui.gather_status())

    def test_includes_entity_count(self):
        from cadkit import gui
        self._write_state()
        st = gui.gather_status()
        self.assertIsNotNone(st)
        self.assertIn("entities", st,
                      "必须带上实体数 —— 这正是当初被静默吞掉的那一项")
        self.assertEqual(st["entities"], self.bridge.requests)
        self.assertNotIn("note", st)

    def test_reports_note_when_count_fails(self):
        from cadkit import gui
        self._write_state()
        # 桥接要活着（否则 live_state 直接返回 None，走不到取数那一步），
        # 只让 request 抛错来模拟取数失败

        class Boom:
            @staticmethod
            def request(*a, **k):
                raise RuntimeError("模拟失败")
        import cadkit.gui as gui_mod
        orig = gui_mod.protocol.request
        gui_mod.protocol.request = Boom.request
        try:
            st = gui_mod.gather_status()
        finally:
            gui_mod.protocol.request = orig
        self.assertIsNotNone(st)
        self.assertIn("note", st, "取数失败必须留下可见提示，不能再静默吞掉")

    def test_keeps_going_without_entities_when_request_rejects_kwarg(self):
        """回归：request() 不接受 state 关键字。"""
        with self.assertRaises(TypeError):
            protocol.request({"cmd": "ping"}, state={"port": 1})


class TestAuth(unittest.TestCase):
    """桥接挂在回环端口上，不加鉴权的话任意本地进程都能发指令 ——
    其中 sendcommand 是原样执行的 AutoCAD 命令串，等于把 CAD 交出去。"""

    def _srv(self, token):
        from cadkit import server
        s = server.BridgeServer.__new__(server.BridgeServer)
        s.token = token
        return s

    def test_correct_token_accepted(self):
        self.assertTrue(self._srv("abc")._authorized({protocol.TOKEN_FIELD: "abc"}))

    def test_wrong_token_rejected(self):
        self.assertFalse(self._srv("abc")._authorized({protocol.TOKEN_FIELD: "abd"}))

    def test_missing_token_rejected(self):
        self.assertFalse(self._srv("abc")._authorized({"cmd": "count"}))

    def test_non_string_token_rejected(self):
        self.assertFalse(self._srv("abc")._authorized({protocol.TOKEN_FIELD: 123}))

    def test_none_token_rejected(self):
        self.assertFalse(self._srv("abc")._authorized({protocol.TOKEN_FIELD: None}))

    def test_server_without_token_rejects_everything(self):
        self.assertFalse(self._srv(None)._authorized({protocol.TOKEN_FIELD: "abc"}))

    def test_tokens_are_random(self):
        self.assertNotEqual(protocol.new_token(), protocol.new_token())

    def test_token_is_long_enough(self):
        self.assertGreaterEqual(len(protocol.new_token()), 32)


if __name__ == "__main__":
    unittest.main(verbosity=2)
