# 🐾 Paw Prints Controller

DG-LAB 爪印无线按钮传感器的 Web 蓝牙控制面板。支持多设备同时连接、实时数据可视化、Agent TCP 接口。

基于 DG-LAB 开源蓝牙协议 V1.1 实现。
###本作品代码99%由ai生成，甚至连这个简介也是，相信你们也看出来了，后续开发基于esp32的版本
  
## 功能

- 🔍 BLE 扫描与连接（支持多台爪印同时连接）
- 📊 实时传感器数据仪表盘（XYZ 角度、加速度、外部电压、按钮状态）
- 📈 实时角度/加速度曲线图（可调坐标轴）
- 🔀 **融合模式** — 两台爪印数据叠加对比
- 📊 **差值分析** — ΔX/ΔY/ΔZ 实时差值 + 欧氏距离
- 💡 主指示灯 + 肩灯控制（颜色/闪烁/自定义序列）
- 🎨 每台设备自动分配独立主灯颜色
- 📼 CSV 数据录制与回放（可调速）
- 📤 Webhook 事件推送
- 🤖 Agent TCP 接口（端口 9878，JSON 行协议）
- 📱 响应式布局（手机/平板适配）
- 📌 最近连接设备列表
- 提供最近连接库快捷的连接设备

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux
- 蓝牙适配器（BLE 4.0+）

### 安装运行

```bash
git clone https://github.com/zsy1023/DG-LAB-contral-zhuaying-for-py.git
cd DG-LAB-contral-zhuaying-for-py\backend
pip install -r requirements.txt
cd ..
python run.py
```

浏览器自动打开 `http://127.0.0.1:9879`。

### 连接设备

1. 爪印设备开机 → **按住按钮不放** → 肩灯白蓝交替闪烁 → 进入配对模式
2. 面板点击 🔍 扫描 → 点击设备连接
3. 可重复操作连接第二台设备

## 项目结构

```
paw-prints-controller/
├── backend/
│   ├── server.py           # FastAPI + WebSocket 服务端
│   ├── ble_manager.py      # BLE 多设备管理器
│   ├── paw_prints.py       # 爪印 V1.1 蓝牙协议
│   ├── tcp_server.py       # Agent TCP 服务端
│   ├── data_buffer.py      # 环形数据缓冲区
│   ├── recorder.py         # CSV 录制器
│   ├── auth_key.py         # Agent 密钥管理
│   ├── recent_devices.py   # 最近设备存储
│   └── requirements.txt
├── frontend/
│   └── index.html          # Web 控制面板
├── run.py                  # 一键启动
├── LICENSE                 # MIT
└── README.md
```

## Agent TCP 接口

Agent 通过 TCP 连接 `127.0.0.1:9878`，JSON 行协议。

### 连接示例

```python
import json, socket

sock = socket.socket()
sock.connect(("127.0.0.1", 9878))

def send(cmd):
    sock.sendall((json.dumps(cmd) + "\n").encode())
    return json.loads(sock.recv(4096).split(b"\n")[0])

# 验证（密钥在面板查看）
print(send({"cmd": "auth", "key": "你的密钥"}))

# 查询状态
print(send({"cmd": "status"}))

# 查询最近 10 秒数据
print(send({"cmd": "data", "seconds": 10}))

# 控制指定设备的肩灯
send({"cmd": "led", "device": 0, "color": 2})

# 播放灯效序列
send({"cmd": "led_seq", "sequence": [
    {"color": 2, "ms": 300}, {"color": 4, "ms": 300}
], "repeat": True})
```

完整文档见 [Agent 连接指南](爪印Agent连接指南.md)。

## 指令参考

| 指令 | 说明 |
|------|------|
| `auth` | 密钥验证 |
| `status` | 设备状态 + 请求参数 |
| `data` | 查询历史数据 |
| `subscribe` | 实时订阅 D0 推送 |
| `led` | 肩灯颜色 |
| `led_seq` | 灯效序列 |
| `d0_start/stop` | D0 直传开关 |
| `cache_duration` | 缓存时长设置 |
| `params` | 查询保存的请求参数 |
| `cmd` | 通用指令 (cmd_5f/cmd_60) |

所有指令支持 `device` 参数指定目标设备，不传则广播全部。

## 协议参考

- [DG-LAB 爪印 V1.1 蓝牙协议]([https://github.com/dg-lab/dglab](https://github.com/dungeonlab-open/dglab-bluetooth-protocol/blob/main/paw-prints/README.md))

## License

MIT
