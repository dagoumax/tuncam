# Dhyana-95-V2 Camera Control

基于 TUCam SDK 的 **Dhyana-95-V2** 科学相机采集与数据处理软件。

## 功能概要

### 第一部分：数据采集

| 功能 | 说明 |
|------|------|
| 曝光时间调节 | 默认 1000 ms，单位 ms，范围受相机硬件限制 |
| 温度控制 | TEC 制冷目标温度，默认 -10 °C，自动开启 TEC |
| 风扇控制 | 四档可调 (1–4)，**不允许关闭**，默认二档 |
| 设备信息 | 显示型号、序列号、固件版本、传感器尺寸等完整信息 |
| 实时遥测 | FPGA / PCBA / 环境温度，风扇转速 |
| 单帧采集 | 抓取一帧并显示 |
| 连续采集 | 持续抓取帧，实时预览 |
| 停止采集 | 终止当前采集流程 |
| 保存图片 | 支持 TIFF / PNG / JPEG 格式 |

### 第二部分：数据处理

| 功能 | 说明 |
|------|------|
| 灰度值提取 | 将 16-bit RAW 图像转换为 2-D numpy uint16 数组 |
| 行分组 | 自定义多组行范围，每组取平均值（如 1-40, 91-130...） |
| 列合并 | 按因子 *n* 将相邻列取平均合并（n=1 不变，n=2 每两列合并） |
| 输出数组 | 最终得到 `组数 × (2048/n)` 的二维数组 |

### 第三部分：UI 界面

- **采集页面** — 图像实时预览 + 设备信息 + 遥测数据
- **设置页面** — 曝光时间 / 温度 / 风扇档位 / 行分组 / 列合并因子
- **数组页面** — 处理后的二维数组表格展示

## 环境要求

- **Windows 10/11 64-bit**
- **Python 3.10+**
- **TUCam SDK** 已安装（相机驱动）

## 安装与运行

```bash
# 1. 安装 uv（如尚未安装）
pip install uv

# 2. 克隆/进入项目目录
cd tucam

# 3. 同步依赖（自动创建虚拟环境）
uv sync

# 4. 运行程序
uv run tucam-control
```

或直接：

```bash
uv run python -m tucam_control.main
```

## 项目结构

```
tucam/
├── pyproject.toml          # 项目配置 (uv)
├── README.md
├── .python-version         # Python 版本锁定
├── lib/
│   └── x64/                # TUCam SDK DLL 文件
│       ├── TUCam.dll
│       └── ...
└── src/
    └── tucam_control/
        ├── __init__.py
        ├── main.py          # 程序入口
        ├── TUCam.py         # SDK ctypes 封装
        ├── camera.py        # 相机控制器
        ├── data_processor.py # 行拆分 / 列合并
        └── ui/
            ├── __init__.py
            ├── main_window.py    # 主窗口 (QTabWidget)
            ├── acquisition_tab.py # 采集页面
            ├── settings_tab.py   # 设置页面
            └── data_tab.py       # 数组展示页面
```

## 扩展指南

项目采用模块化设计，便于后续扩展：

- **新增相机功能** → 修改 `camera.py`，在 `CameraController` 中添加方法
- **新增数据处理算法** → 修改 `data_processor.py`，添加新的处理模式
- **新增 UI 页面** → 在 `ui/` 下创建新 Tab，在 `main_window.py` 中注册
- **新增 SDK 调用** → 在 `TUCam.py` 中添加对应的 ctypes 绑定

## 许可证

内部使用项目。
