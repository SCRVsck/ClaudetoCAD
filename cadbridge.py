#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CadBridge 入口。打包后这就是 exe 的主模块。

源码运行：python cadbridge.py <命令>
打包运行：cadbridge.exe <命令>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cadkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
