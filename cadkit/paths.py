# -*- coding: utf-8 -*-
"""路径解析：区分「安装目录（只读）」与「运行期数据目录（可写）」。

打包成 exe 后 ``__file__`` 指向 PyInstaller 的临时解包目录，重启即消失，
所以 state / log / config 一律放用户数据目录（默认 ``%LOCALAPPDATA%\\CadBridge``）。

可用环境变量 ``CADBRIDGE_HOME`` 覆盖数据目录（测试与多实例隔离用）。
"""

import os
import sys

APP_NAME = "CadBridge"


def is_frozen():
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def install_dir():
    """程序自身所在目录 —— 放只读资源（示例、图标、模板）。

    冻结后是 exe 所在目录；源码运行时是本包的上一级（项目根）。
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """可写的用户数据目录，不存在则创建。"""
    override = os.environ.get("CADBRIDGE_HOME")
    if override:
        d = os.path.abspath(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def state_path():
    return os.path.join(data_dir(), "state.json")


def config_path():
    return os.path.join(data_dir(), "config.json")


def log_path():
    return os.path.join(data_dir(), "bridge.log")


def events_path():
    return os.path.join(data_dir(), "events.jsonl")


def lock_path():
    """互斥锁：保证同时只有一个桥接在跑。"""
    return os.path.join(data_dir(), "bridge.lock")


def describe():
    return {
        "frozen": is_frozen(),
        "install_dir": install_dir(),
        "data_dir": data_dir(),
    }
