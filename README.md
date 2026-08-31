# Dhyana-95-V2 Camera Control

这是一个基于 TUCam SDK 的 Dhyana-95-V2 科学相机采集、Raman 光谱处理和气体浓度分析程序。程序支持真实相机采集，也支持加载 TIF 图片进行离线测试。

## 主要功能

### 相机采集

- 所有 TUCam SDK 调用运行在独立子进程，原生接口卡死时可超时终止并重建
- 自动初始化 TUCam SDK 并连接 Dhyana 相机
- 支持单帧采集和连续采集
- 支持曝光时间设置，默认 `1000 ms`
- 支持温度目标、风扇档位、工作模式设置
- 自动记录 SDK 返回码、相机数量、设备句柄、帧格式和图像统计值
- 支持自动保存采集图像
- 支持加载单张 TIF 图片进行测试
- 支持批量加载 TIF 文件夹，模拟连续采集流程

### 数据处理

- 支持最多 16 个行组，并可为每个行组设置唯一的自定义名称
- 行范围只在设置页的行组管理窗口显示；图例、筛选、诊断和导出使用自定义名称
- 行组内部支持求和或平均，默认使用求和
- 支持一次处理最多 16 个行组的使用场景
- 支持列合并，降低噪声或数据量
- 使用排除全部已配置气体峰窗口后的 MAD 稳健估计噪声，避免强峰抬高检出阈值
- 全局检出阈值系数可在设置页调整并保存，默认 `3.0`
- 每种气体可配置独立检出阈值倍数；留空时继承全局值
- 支持 arPLS 基线校正
- arPLS 开启且使用“校正后”模式时，寻峰直接使用校正后的正峰高，不再重复扣除窗口最小值
- 支持原始数据、校正后数据、仅基线等拉曼图输出模式；输出模式不再影响浓度计算
- arPLS 启用时，寻峰、拉曼信号诊断和浓度计算始终使用校正后光谱
- 设置页参数和气体表自动保存到 `config/user_settings.json`
- 软件启动时会立即把已保存的浓度平滑档位同步到运行算法和导出模式，无需再次点击“应用设置”
- 采集后的数据处理在后台线程执行，避免界面卡死
- 后台任务忙时只保留最新待处理帧，避免任务队列无限堆积

### 浓度分析

- 支持多气体配置
- 支持峰位、搜索窗口、浓度系数、Raman 位移和报警浓度配置
- 支持按行组计算气体浓度
- 支持浓度历史趋势显示
- 支持 CSV 导出
- Halon 浓度在归一化后、平滑前应用实测分段线性校正：`3→2`、`5.4→5`、`6.5→6`、`10→10`、`20→20`（单位 `%`）
- Halon 校正后，其余气体按原比例补偿，确保总浓度保持 `100%`
- 超过气体报警浓度时在浓度页统计并高亮提示，不弹窗、不自动停止采集
- 浓度页提供手动“急停”按钮，可直接停止连续采集或批量测试

### 局域网远程控制

- 现场电脑继续负责连接相机和运行 TUCam SDK，控制室电脑不需要安装 SDK
- 无需互联网，两台电脑通过交换机或一根网线组成独立局域网即可
- 控制室浏览器可查看连接状态、采集状态、平滑浓度、浓度趋势和诊断摘要
- 浏览器每秒增量获取一次数据，并以约 `30 FPS` 播放真实测量点之间的平滑过渡；不会遗漏两次请求之间的测量点
- 可选择 `1 / 3 / 5 / 10 秒` 显示延迟，默认 `3 秒`；延迟只作用于浓度表和曲线，设备与采集状态保持实时
- 支持远程启动连续采集、停止和急停；相机命令始终回到 Qt 主线程执行
- 使用访问密钥认证，并可限制只允许指定的控制室 IP
- 远程功能默认关闭，启用后随程序启动，不影响本机操作和离线 TIF 测试
- 现场程序必须保持运行；网页负责远程开启采集，不会从关机状态启动现场电脑

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

## 直连网线远程使用

1. 用网线连接现场电脑和控制室电脑。若网卡不支持自动翻转，可通过普通交换机连接。
2. 给现场电脑网卡设置静态地址 `192.168.50.10`，子网掩码 `255.255.255.0`。
3. 给控制室电脑网卡设置静态地址 `192.168.50.20`，子网掩码相同；独立网络无需填写网关和 DNS。
4. 在现场软件“设置”页启用“局域网远程控制”，端口保持 `8765`。
5. “控制室 IP”填写 `192.168.50.20`，保存访问密钥并点击“应用设置”。
6. Windows 防火墙首次询问时仅允许“专用网络”；也可以手动放行现场电脑的 TCP `8765` 端口。
7. 在控制室电脑浏览器打开 `http://192.168.50.10:8765`，输入现场软件显示的访问密钥。

无人值守时，建议让现场电脑在 Windows 登录后自动运行本程序，并在 BIOS 中启用“来电自动开机”。
这样现场恢复供电后，程序和远程页面会自动恢复；直接网线本身无法唤醒一台关机且未配置
Wake-on-LAN 的电脑。

源码版或便携版可运行下面的脚本，为当前 Windows 用户创建登录后自动启动项：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure_field_autostart.ps1
```

需要取消自动启动时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure_field_autostart.ps1 -Remove
```

设置页“运行状态”会显示现场电脑当前可访问的网址。网页每 `1 秒` 获取一次增量数据，
现场程序保留最近约 `120 秒` 的远程数据供断线追赶。浏览器在所选延迟下以约 `30 FPS`
绘制平滑过渡，但不会生成或导出虚假测量点；浓度数据仍以相机实际曝光和处理完成时间为准。
远程端显示的是与本机浓度图一致的平滑浓度和同一个电脑本地测量时间。停止、重启采集或
切换批量测试时会插入曲线断点，不会把停机间隔错误连接成连续变化。

本机浓度动画使用 `33 ms` 精确定时器，理论上限约 `30.3 FPS`。已有性能日志中空闲时通常
达到约 `29–30 FPS`；窗口拖动、系统图形负载或主线程繁忙时，Windows 可能暂时降低实际帧率。

如果网页打不开，依次检查：两台电脑能否互相 `ping`、远程功能是否显示“运行中”、
访问地址和端口是否正确，以及 Windows 防火墙是否允许该端口。独立网线网络不需要连接互联网。

## 自定义行组名称

在“设置 / Settings”页点击“管理行组”，可以添加、删除、排序和重命名行组。
每个行组需要设置唯一名称、起始行和结束行，最多支持 16 个行组。

自定义名称会用于：

- 拉曼图和浓度图图例
- 行组筛选下拉框
- 拉曼信号异常提示
- 拉曼校准窗口
- 阈值统计和 CSV 导出

起始行和结束行只在行组管理窗口中显示，不会附加在名称后，也不会作为独立字段导出。
只修改名称不会改变实际处理范围、历史浓度、平滑状态或阈值统计。
旧配置未保存名称时会依次显示为 `行组1`、`行组2` 等。

## 日志与排错

程序会常驻写入日志，便于长期排查相机、SDK、采集帧和界面问题。

日志位置：

- 主日志：`logs/tucam_control.log`
- SDK 子进程日志：`logs/tucam_sdk_process.log`
- 崩溃日志：`logs/tucam_fault.log`
- 旧版调试日志兼容路径会转向主日志

日志采用轮转策略：

- 单个主日志最大约 5 MB
- 最多保留 5 份历史日志
- SDK 子进程日志使用相同的轮转策略
- 可通过环境变量 `TUCAM_LOG_MAX_MB` 和 `TUCAM_LOG_BACKUP_COUNT` 调整

运行期间每约 10 秒会记录一次 `Runtime performance`，其中包含界面事件循环
平均、95% 和最大延迟，以及图像处理子进程的 CPU 和内存占用。采集页诊断面板
也会显示最新的处理进程资源数据。

设置页可启用 PyQtGraph OpenGL 绘图加速。该选项默认关闭，因为短曲线和多图例
场景不一定能从 GPU 获益；启用后程序会验证 OpenGL 上下文，失败时自动切回软件
绘制并记录 `OpenGL runtime fallback`。

需要对比绘图后端时，可同时启用“显示实时绘图帧率”，拉曼图和浓度图左上角会
显示最近一秒的实际 FPS；关闭后不会保留浮层。

`Dev_Open`、`Cap_Stop` 等原生接口超时后，主程序会终止整个 SDK 子进程，避免旧 DLL 状态和相机句柄继续拖住界面；再次连接时会创建全新的 SDK 进程。

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
