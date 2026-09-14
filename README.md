# CadBridge · AutoCAD 双向实时桥接

通过 COM 自动化长连接本机 AutoCAD，让脚本和程序能直接驱动它画图、建模、读回状态。
提供 **命令行** 和 **图形控制台** 两种用法。

- **架构**：`cadkit` 一套实现，两种前端（`cadbridge.exe` / `cadbridge-gui.exe`）
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

想要图形界面就双击 `cadbridge-gui.exe`，或运行 `cadbridge gui`。

## 图形控制台

双击 `cadbridge-gui.exe` 打开，四个标签页：

| 页 | 用途 |
|----|------|
| **状态** | 一键自检，按「正常 / 注意 / 故障」着色列出每一项 |
| **绘图** | 选图形（直线 / 圆 / 文字 / 矩形），填参数直接画 |
| **控制台** | 内嵌命令行，支持短命令与完整 JSON |
| **日志** | 桥接日志尾部，可直接打开数据目录 |

顶部是实时状态条（桥接 / AutoCAD 版本 / 实体数 / 端口），带自动刷新开关。
耗时操作都在后台线程跑，界面不卡；忙碌时按钮会置灰而不是默默无视点击。

## 常用命令

| 命令 | 说明 |
|------|------|
| `cadbridge doctor [--deep]` | 自检：哪一环断了、怎么修。`--deep` 会真画一条线做端到端验证 |
| `cadbridge gui` | 打开图形控制台 |
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
python build.py              # 打包 exe（图标不存在会自动生成）
python build.py --clean      # 先清理再打
python build.py --portable   # 额外产出免安装 zip
python build.py --installer  # 额外产出安装程序（需要 Inno Setup）
python build.py --all        # 三样都出
```

三种分发形态：

| 形态 | 产物 | 适用 |
|------|------|------|
| 裸 exe | `dist/cadbridge.exe` + `dist/cadbridge-gui.exe` | 单文件，拷过去就能用 |
| 便携包 | `dist/CadBridge-<版本>-portable.zip` | 内含两个 exe + 文档 + 「安装.cmd / 卸载.cmd」（把目录加进用户 PATH） |
| 安装程序 | `dist/CadBridge-<版本>-setup.exe` | 向导式安装，自动配 PATH，卸载时会**先停桥接**再删文件 |

两个 exe 共用同一套 `cadkit`，但分成两个而不是合一：做成一个的话，要么 GUI 用户
看到多余的黑窗口，要么 CLI 用户白背几 MB 的 tkinter。分开最干净。

打包后目标机器**不需要装 Python**，只需要装 AutoCAD。安装程序按用户安装
（`PrivilegesRequired=lowest`），不弹 UAC；卸载会精确还原用户 PATH。

> 编译安装程序需要 [Inno Setup 6](https://jrsoftware.org/isdl.php)
> （`winget install JRSoftware.InnoSetup`）；缺了不会导致构建失败，只会跳过并提示。
> 想要中文向导界面需另加 `ChineseSimplified.isl`（Inno Setup 不自带），
> 没有就是英文界面，功能不受影响。

安装程序已实测走通「静默安装 → 校验 → 静默卸载」全流程：文件、开始菜单、
用户 PATH、注册表卸载项均正确写入并在卸载后清理干净。

| 项 | 值 |
|----|----|
| 入口模块 | `cadbridge.py`（CLI）· `cadbridge_gui.py`（GUI） |
| 打包配置 | `cadbridge.spec` · 安装脚本 `installer/cadbridge.iss` |
| 图标 | `assets/cadbridge.ico`（由 `assets/make_icon.py` 生成） |
| 运行期数据 | `%LOCALAPPDATA%\CadBridge\`（state / log / config） |

数据目录可用环境变量 `CADBRIDGE_HOME` 覆盖（多实例隔离 / 测试用）。

## 安全

桥接监听在回环地址（127.0.0.1），**并且要求接入 token**。token 每次启动随机生成，
写在 `%LOCALAPPDATA%\CadBridge\state.json`（按用户 ACL 隔离），客户端自动携带、
服务端常数时间比对。

没有这道校验的话，本机任意进程都能连上端口发指令 —— 其中 `sendcommand` 是
原样执行的 AutoCAD 命令串（例如 `_ERASE _ALL`），等于把 CAD 完全交出去。

> 同一用户下的进程仍能读到 token。要防住这个量级的攻击者需要 OS 级隔离
> （具名管道 + 安全描述符），目前没做。

## 运行前提

- Windows + 已安装 AutoCAD（**不捆绑、不附带**，需要用户自备正版授权）
- 支持的版本：2018–2026（按 `AutoCAD.Application.*` ProgID 自动探测，优先用最新版）

## 测试

```bash
python -m unittest discover -s tests -v
```

39 项回归测试，不需要 AutoCAD。

## 示例

**自动绘图**（读计算书 → 出施工图）：

```bash
# 一份计算书出一张图
python draw_section.py --rtf eg/桩悬臂.rtf

# 一个目录的计算书批量出一册（按演示图的方式并排排开）
python draw_section.py --dir 计算书目录/

# 用内置参数（不读计算书）
python draw_section.py CD段 --template     # 桩锚/悬臂桩
python draw_section.py EF段 --template     # 放坡土钉
python draw_section.py GH段 --template     # 双排桩
```

参数从**天汉基坑设计软件**导出的计算书里解析：土层（编号/名称/层底埋深/C/φ）、
桩排（桩顶标高/桩长/间距/直径）、冠梁、放坡、地面超载、支护结构类型。
图纸画在**演示图复制出来的模板**里 —— 图框块、23 个图层、文字样式都是标准图里那套，
图签栏也按标准位置自动填。

**支护类型支持情况**（见 `cadkit/sections/`）：

| 类别 | 类型 | 状态 |
|------|------|------|
| 主体 | `pile` 桩锚 / 悬臂桩 | ✅ |
| 主体 | `slope` 放坡土钉（多级台阶） | ✅ |
| 主体 | `double` 双排桩 | ✅ |
| 附加 | `passive` 被动区加固 | ✅ |
| 附加 | `bracing` 内支撑 / 格构柱 | ✅ |
| 附加 | `reinforce` 桩身配筋大样 | ✅ |
| 附加 | `notes` 设计施工说明 | ✅ |

主体决定开挖轮廓、出一张独立图纸；附加叠加在主体剖面上。
参数里用 `附加: ["passive", "notes"]` 指定要叠哪些 —— 任一主体都能配任一组附加。

**基坑支护剖面图**（按工程图标准生成）：

```bash
python draw_section.py       # CD段悬臂桩：土层填充 + 冠梁 + 支护桩 + 尺寸 + 图签
```

**长方形 + 尺寸标注**（最小示例，适合先跑这个）：

```bash
python draw_rect_dim.py      # 画 200×120 长方形，下方/右侧各标一个绿色尺寸
```

**三星 Galaxy S23 Ultra** —— 两个脚本，产出的图形都存进 `S23Ultra.dwg`：

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
cadbridge.py        # CLI 入口（打包主模块）
cadbridge_gui.py    # GUI 入口（窗口程序）
cadkit/             # 全部实现
  cli.py            #   命令行
  gui.py            #   图形控制台（tkinter）
  server.py         #   桥接服务端（唯一 COM 连接者，select 多路复用）
  acad.py           #   AutoCAD 探测 / 连接 / 自动拉起
  protocol.py       #   state.json 握手 + TCP 长连接 + 接入 token
  daemon.py         #   桥接进程管理 + 单实例
  standard.py       #   工程图标准（图层表 / 土层图案表）
  doctor.py         #   自检
  config.py         #   配置
  paths.py          #   冻结感知的路径解析
bridge.py / cad.py  # 兼容入口（旧用法仍可用）
assets/             # 图标与其生成脚本
installer/          # Inno Setup 脚本
tools/              # 辅助工具（RTF 取文本、VBA 模块取过程）
build.py            # 打包
tests/              # 回归测试
```
