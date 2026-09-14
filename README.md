# CadBridge · AutoCAD 双向实时桥接

通过 COM 自动化长连接本机 AutoCAD，让脚本和程序能直接驱动它画图、建模、读回状态。

- **架构**：`cadbridge.exe`（或 `cadbridge.py`）一个入口，既是客户端也是常驻桥接
- **完整参考**：见 [`使用指南.md`](使用指南.md)

## 三步上手

```bash
# 1) 先看环境缺什么（这一步会告诉你 AutoCAD 找不找得到）
cadbridge doctor

# 2) 画点东西 —— 桥接和 AutoCAD 都会自动起来，不用手动开
cadbridge line 0,0 100,100
cadbridge circle 50,50 25
cadbridge text "中文标注" --at 10,10 --height 8

# 3) 看状态
cadbridge info
```

> **不需要预先启动任何东西。** 第一次调用会自动拉起后台桥接，桥接再自动拉起 AutoCAD。

## 常用命令

| 命令 | 说明 |
|------|------|
| `cadbridge doctor [--deep]` | 自检：哪一环断了、怎么修。`--deep` 会真画一条线做端到端验证 |
| `cadbridge info` / `status` | 桥接与 AutoCAD 的状态 |
| `cadbridge line 0,0 100,100` | 直线 |
| `cadbridge circle 50,50 25` | 圆 |
| `cadbridge text "内容" --at x,y --height h` | 文字（中文直接传） |
| `cadbridge count` / `entities` / `changes` | 实体数 / 枚举 / 变更签名 |
| `cadbridge zoom extents` | 缩放到全图 |
| `cadbridge save out.dwg` | 另存为 |
| `cadbridge start` / `stop` | 手动管理桥接（AutoCAD 不受影响） |
| `cadbridge config <键> [值]` | 查看/修改配置 |
| `cadbridge '<JSON>'` | 原样透传任意指令（给脚本用） |

完整的指令协议（含三维实体建模）见 [`使用指南.md`](使用指南.md) §5。

## 打包发布

```bash
python build.py           # 产出 dist/cadbridge.exe（单文件，约 9 MB）
python build.py --clean   # 先清理再打包
```

打包后目标机器**不需要装 Python**，只需要装 AutoCAD。

| 项 | 值 |
|----|----|
| 产物 | `dist/cadbridge.exe` |
| 运行期数据 | `%LOCALAPPDATA%\CadBridge\`（state / log / config） |
| 安装目录 | exe 所在目录（只读资源） |

数据目录可用环境变量 `CADBRIDGE_HOME` 覆盖（多实例隔离 / 测试用）。

## 运行前提

- Windows + 已安装 AutoCAD（**不捆绑、不附带**，需要用户自备正版授权）
- 支持的版本：2018–2026（按 `AutoCAD.Application.*` ProgID 自动探测，优先用最新版）

## 测试

```bash
python -m unittest discover -s tests -v
```

39 项回归测试，不需要 AutoCAD。

## 示例：三星 Galaxy S23 Ultra

两个脚本，产出的图形都存进 `S23Ultra.dwg`：

| 脚本 | 产物 |
|------|------|
| `draw_s23ultra.py` | **斜轴测立体图**：正面 / 背面并排两个视图，含屏占比、打孔前摄、侧键、后置四摄、尺寸标注与规格说明（99 个图元） |
| `build_s23_3d.py` | **真三维实体模型**：ACIS 实体，圆角机身 + 铣槽屏幕 + 4 个环形镜圈 + 布尔挖孔，可旋转、剖切（21 个实体） |

```bash
python draw_s23ultra.py      # 二维立体图
python build_s23_3d.py       # 三维实体（会自动切到三维视图 + 着色）
```

尺寸按官方规格：163.4 × 78.1 × 8.9 mm。三维模型放在世界坐标 x≈520 处，与二维图错开。

**看模型**：`3DORBIT` 转视角 · `VPOINT -1,-1,1` 看背面四摄 · `VPOINT 0,0,1` 回平面图 · `VSCURRENT` 换视觉样式。

## 目录结构

```
cadbridge.py        # 入口（打包主模块）
cadkit/             # 全部实现
  cli.py            #   命令行
  server.py         #   桥接服务端（唯一 COM 连接者）
  acad.py           #   AutoCAD 探测 / 连接 / 自动拉起
  protocol.py       #   state.json 握手 + TCP 长连接
  daemon.py         #   桥接进程管理 + 单实例
  doctor.py         #   自检
  config.py         #   配置
  paths.py          #   冻结感知的路径解析
bridge.py / cad.py  # 兼容入口（旧用法仍可用）
build.py            # 打包
tests/              # 回归测试
```
