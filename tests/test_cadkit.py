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
import sys
import tempfile
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


class TestServerEmptyRequest(unittest.TestCase):
    """空连接是存活探测，绝不能被当成指令去触发 AutoCAD 健康检查/重启。"""

    def test_empty_buffer_is_treated_as_probe(self):
        from cadkit import server
        srv = server.BridgeServer.__new__(server.BridgeServer)
        srv.app = srv.doc = None
        srv.cfg = {}
        touched = []
        srv._dispatch_with_retry = lambda req: touched.append(req) or {"ok": True}
        srv._ensure_alive = lambda: touched.append("alive")

        class FakeConn:
            def settimeout(self, t): pass
            def recv(self, n): return b""      # 连上就关 = 探测
            def sendall(self, b): touched.append(("send", b))
            def close(self): pass

        self.assertTrue(srv._serve_one(FakeConn()))
        self.assertEqual(touched, [], "空连接不该触发任何指令处理")


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
                    resp = b'{"ok":true,"n":%d}\n' % self.requests
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
