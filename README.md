# Dhyana-95-V2 Camera Control

这是一个基于 TUCam SDK 的 Dhyana-95-V2 科学相机采集、Raman 光谱处理和气体浓度分析程序。程序支持真实相机采集，也支持加载 TIF 图片进行离线测试。

## 主要功能

### 相机采集

- 自动初始化 TUCam SDK 并连接 Dhyana 相机
- 支持单帧采集和连续采集
- 支持曝光时间设置，默认 `1000 ms`
- 支持温度目标、风扇档位、工作模式设置
- 自动记录 SDK 返回码、相机数量、设备句柄、帧格式和图像统计值
- 支持自动保存采集图像
- 支持加载单张 TIF 图片进行测试
- 支持批量加载 TIF 文件夹，模拟连续采集流程

### 数据处理

- 支持行组设置，例如 `1-40, 91-130, 200-250`
- 行组内部支持求和或平均，默认使用求和
- 支持一次处理最多 16 个行组的使用场景
- 支持列合并，降低噪声或数据量
- 支持 arPLS 基线校正
- 支持原始数据、校正后数据、仅基线等输出模式
- 设置页参数和气体表自动保存到 `config/user_settings.json`
- 采集后的数据处理在后台线程执行，避免界面卡死
- 后台任务忙时只保留最新待处理帧，避免任务队列无限堆积

### 浓度分析

- 支持多气体配置
- 支持峰位、搜索窗口、浓度系数和 Raman 位移配置
- 支持按行组计算气体浓度
- 支持浓度历史趋势显示
- 支持 CSV 导出

## 运行环境

- Windows 10/11 64-bit
- Python 3.10+
- TUCam SDK / Dhyana 相机驱动
- 项目内需要包含 `lib/x64/TUCam.dll` 及其依赖 DLL

离线 TIF 测试模式不需要连接相机。

## 已确认设备

当前目标设备为 `Dhyana 95 V2`。根据厂商资料，该型号的关键参数如下：

- 传感器：BSI sCMOS，Gpixel GSENSE400BSI
- 分辨率：`2048 x 2048`
- 像素尺寸：`11 um x 11 um`
- 快门类型：Rolling
- 曝光范围：`21 us ~ 10 s`
- 数据接口：`USB 3.0` 或 `CameraLink`
- 帧数据：固定使用 `16 bit` 容器；不同工作模式的有效位深由相机决定
- 制冷方式：风冷、水冷
- SDK：C、C++、C#、Python

连接时需要先确认实际使用的是 `USB 3.0` 还是 `CameraLink`：

- USB 连接应使用主机后置 USB 3.0 接口，避免 HUB、扩展坞和过长延长线。
- CameraLink 连接需要采集卡、两根 CameraLink 线、采集卡驱动，并确认线缆接口顺序。
- 设备管理器中 USB 相机应出现在图像设备下且无黄色警告标志。
- CameraLink 采集卡应正常识别，厂商资料中推荐 Active Silicon FireBird 采集卡。
- 如果厂商 Mosaic 或 SamplePro 不能正常出图，应优先排查驱动、接口、电源和硬件连接，再排查本程序。

## 安装与启动

推荐使用项目内已有的虚拟环境或 `uv` 安装依赖。

```powershell
cd C:\Users\Lenovo\Desktop\tucam
uv sync
uv run tucam-control
```

也可以使用项目根目录下的快捷启动脚本：

```powershell
.\start_tucam.bat
```

需要创建或修复桌面快捷方式时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1
```

脚本会根据项目当前目录重新写入启动目标、工作目录和 `assets/wut_logo.ico` 图标路径，项目移动后重新运行一次即可。

程序入口定义在 `pyproject.toml`：

```toml
[project.scripts]
tucam-control = "tucam_control.main:main"
```

## 日志与排错

程序会常驻写入日志，便于长期排查相机、SDK、采集帧和界面问题。

日志位置：

- 主日志：`logs/tucam_control.log`
- 崩溃日志：`logs/tucam_fault.log`
- 旧版调试日志兼容路径会转向主日志

日志采用轮转策略：

- 单个主日志最大约 5 MB
- 最多保留 5 份历史日志

排查相机问题时，优先搜索这些关键词：

- `SDK diagnostics`
- `TUCAM_Api_Init`
- `TUCAM_Dev_Open`
- `Data format readback`
- `Bit depth readback`
- `TUCAM_Cap_Start`
- `Frame received`
- `Frame array stats`
- `Fan gear readback`
- `Unhandled exception`

### 常见判断

如果日志中出现：

```text
TUCAM_Api_Init returned TUCAMRET_SUCCESS
TUCAM_Dev_Open returned TUCAMRET_SUCCESS
```

说明 SDK 初始化和相机打开成功。

如果日志中出现：

```text
Frame array stats: min=0 max=0 mean=0
```

说明程序拿到的图像数组确实全为 0，需要继续检查曝光、光路、触发、快门、增益或相机输出格式。

如果日志中出现：

```text
Frame array stats: min=0 max=5 mean=0.5
```

说明不是完全无数据，而是信号非常低，画面肉眼看起来可能仍然接近纯黑。

如果日志中出现：

```text
format=18 channels=3 elem_bytes=1
```

说明当前帧可能不是科学相机的单通道 16 位数据。Dhyana 95 V2 不支持 `TUIDC_DATAFORMAT`，程序通过帧结构的 `ucFormatGet` 请求数据，并以实际帧头中的 `ucDepth`、`ucChannels` 和 `ucElemBytes` 为准。

## SDK 文件

SDK 文件位于：

```text
lib/x64/
```

当前程序会在启动时检查并记录这些 DLL 是否存在：

- `TUCam.dll`
- `clallserial.dll`
- `mfc120u.dll`
- `msvcp120.dll`
- `msvcr120.dll`
- `MultiCam.dll`
- `phxlx64.dll`
- `tuimgcv_core2410.dll`
- `tuimgcv_highgui2410.dll`
- `tuimgcv_imgproc2410.dll`

如果移植到其它电脑，优先确认 `lib/x64` 文件完整，并确认 Python、系统和 DLL 都是 64 位。

## 风扇与制冷说明

程序按照 Dhyana 95 V2 的 SDK 定义提供三个风扇速度：

- `0`：高速（默认）
- `1`：中速
- `2`：低速

SDK 值 `3` 表示水冷模式下关闭风扇，程序不会提供该选项。设置时会记录能力范围和读回值：

```text
Fan gear attr returned ...
Set fan gear ...
Fan gear readback after set ...
```

部分相机或 SDK 组合不支持读取风扇转速，日志中可能出现：

```text
TUIDI_FAN_SPEED returned TUCAMRET_NOT_SUPPORT
```

这表示程序无法读取真实转速，不一定表示风扇档位设置失败。

根据 Dhyana 95 V2 属性表，该型号不支持 `TUIDC_ENABLETEC`，程序不会调用这个能力。温度控制优先使用独立目标温度属性 `TUIDP_TEMPERATURE_TARGET`；不支持时才使用开发指南中的旧版温度编码。

实时温度始终通过 `TUIDP_TEMPERATURE` 读取，目标温度和实时温度不会再混为同一个显示值。

## 项目结构

```text
tucam/
├─ assets/                  # 图标资源
├─ lib/x64/                 # TUCam SDK DLL
├─ logs/                    # 运行日志，已被 .gitignore 忽略
├─ scripts/                 # 辅助脚本
├─ src/tucam_control/
│  ├─ main.py               # 程序入口
│  ├─ TUCam.py              # TUCam SDK ctypes 封装
│  ├─ camera.py             # 相机控制与采集
│  ├─ debug_log.py          # 常驻日志
│  ├─ resources.py          # 资源路径
│  ├─ data_processor.py     # 行组、列合并、基线校正
│  ├─ gas_analyzer.py       # 气体浓度分析
│  ├─ calibration.py        # Raman 校准
│  └─ ui/                   # PySide6 界面
├─ start_tucam.bat          # 快捷启动脚本
├─ pyproject.toml
├─ uv.lock
└─ README.md
```

## 采集性能说明

当前目标场景是：

- 曝光时间约 `1 s`
- 一次最多处理 16 个行组
- 界面不因浓度计算而堵塞

连续采集时，程序使用短轮询等待相机帧。采到一帧后立即更新图像，并把数据处理放到后台线程。后台处理来不及时，会丢弃旧的待处理帧，只保留最新帧，避免进程越跑越堵。

实际帧间隔仍会受这些因素影响：

- 相机曝光时间
- USB 传输速度
- 图像保存 I/O
- Raman 图和浓度趋势刷新
- 电脑性能

## 开发建议

- 修改 SDK 调用时优先改 `TUCam.py`
- 修改相机流程时优先改 `camera.py`
- 修改界面交互时优先改 `ui/main_window.py`
- 新增问题排查点时优先写入 `tucam_control` 日志
- 不要提交 `logs/`、`.venv/`、`.idea/`、相机自动生成的 `Dhyana*.xml`

## Git 忽略说明

当前应忽略：

- `.venv/`
- `.idea/`
- `__pycache__/`
- `logs/`
- `Dhyana*.xml`

`uv.lock` 应保留在版本库中，便于复现依赖环境。
