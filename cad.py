#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容入口 —— 旧用法 ``python cad.py '<json>'`` 仍可用。

新代码请用 ``python cadbridge.py <命令>``（或打包后的 ``cadbridge.exe``）。
旧的裸词 / 裸 JSON 用法一并保留。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cadkit.cli import main  # noqa: E402


def send(obj):
    """兼容旧脚本的 ``cad.send({...})`` —— 发一条指令，返回响应 dict。

    旧实现每次自己读 state.json 开 socket；现在走 protocol.request，
    额外获得「桥接没跑就自动拉起」和统一超时处理，返回结构不变。
    """
    from cadkit import protocol
    return protocol.request(obj)


if __name__ == "__main__":
    # 老客户端支持 `cad.py state` / `cad.py events [N]` 这两个本地查询
    argv = sys.argv[1:]
    if argv and argv[0] == "state":
        from cadkit import protocol
        import json
        print(json.dumps(protocol.read_state() or {}, ensure_ascii=False, indent=2))
        sys.exit(0)
    if argv and argv[0] == "events":
        from cadkit import paths
        import json
        n = int(argv[1]) if len(argv) > 1 else 20
        p = paths.events_path()
        if not os.path.exists(p):
            print(json.dumps({"events": []}, ensure_ascii=False))
            sys.exit(0)
        with open(p, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        print(json.dumps([json.loads(l) for l in lines[-n:]],
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    sys.exit(main())
