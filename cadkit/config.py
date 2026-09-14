# -*- coding: utf-8 -*-
"""用户配置：``%LOCALAPPDATA%\\CadBridge\\config.json``。

设计原则是「缺省即可用」——文件不存在、字段缺失、JSON 损坏都退回默认值，
绝不让配置问题把工具卡死。
"""

import copy
import json
import os

from . import paths

DEFAULTS = {
    # None = 自动探测；也可写死 "AutoCAD.Application.24.1"
    "progid": None,
    # 桥接启动时若没有运行中的 AutoCAD，是否自动拉起
    "autostart_cad": True,
    # 客户端在桥接没跑时是否自动拉起桥接
    "autostart_bridge": True,
    # 等 AutoCAD 就绪的上限（秒）
    "cad_launch_timeout": 120,
    # 客户端单次请求超时（秒）；建模大图可能很久，给宽点
    "request_timeout": 180,
    # RPC_E_CALL_REJECTED 重试次数与间隔
    "retries": 8,
    "retry_delay": 0.6,
    # 空闲多久做一次 AutoCAD 健康探测（秒）；0 = 关闭
    "health_interval": 15.0,
    # 客户端长连接的空闲上限（秒）；超时后服务端释放连接
    "conn_idle_timeout": 300.0,
    # 桥接日志轮转
    "log_max_bytes": 2_000_000,
    "log_backups": 3,
}


def load():
    """读配置；任何异常都退回默认值。"""
    cfg = copy.deepcopy(DEFAULTS)
    p = paths.config_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        cfg[k] = data[k]
        except Exception:
            pass
    return cfg


def save(cfg):
    """写回配置（只保留已知字段）。"""
    out = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    p = paths.config_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def get(key):
    return load().get(key, DEFAULTS.get(key))


def set(key, value):
    if key not in DEFAULTS:
        raise KeyError("未知配置项：%s（可选：%s）" % (key, ", ".join(sorted(DEFAULTS))))
    cfg = load()
    cfg[key] = value
    save(cfg)
    return cfg
