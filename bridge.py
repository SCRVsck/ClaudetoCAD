#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容入口 —— 旧用法 ``python bridge.py`` 仍可用。

新代码请用 ``python cadbridge.py start``（或打包后的 ``cadbridge.exe start``）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cadkit.server import BridgeServer  # noqa: E402

if __name__ == "__main__":
    sys.exit(BridgeServer().serve_forever())
