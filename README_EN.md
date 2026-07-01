# 🐾 Paw Prints Controller

Web Bluetooth control panel for DG-LAB Paw Prints wireless button sensor. Supports multi-device connections, real-time visualization, and Agent TCP API.

Based on DG-LAB open BLE protocol V1.1.

## Features

- 🔍 BLE scan & connect (supports multiple devices simultaneously)
- 📊 Real-time sensor dashboard (XYZ angles, acceleration, voltage, button state)
- 📈 Real-time chart with adjustable Y-axis range
- 🔀 **Fusion mode** — overlay two devices' data on the same chart
- 📊 **Difference analysis** — real-time ΔX/ΔY/ΔZ + Euclidean distance
- 💡 Main indicator + shoulder LED control (color, flash, custom sequence)
- 🎨 Auto-assign unique LED color per device
- 📼 CSV recording & playback (adjustable speed)
- 📤 Webhook event push
- 🤖 Agent TCP API (port 9878, JSON-line protocol)
- 📱 Responsive layout (mobile/tablet)
- 📌 Recent device list

## Quick Start

### Requirements

- Python 3.10+
- Windows / macOS / Linux
- Bluetooth adapter (BLE 4.0+)

### Install & Run

```bash
pip install -r backend/requirements.txt
python run.py
```

Browser opens `http://127.0.0.1:9879` automatically.

### Connect Device

1. Power on Paw Prints → **hold button** until shoulder LEDs flash white-blue → pairing mode
2. Click 🔍 Scan → click device to connect
3. Repeat to connect additional devices

## Project Structure

```
paw-prints-controller/
├── backend/
│   ├── server.py           # FastAPI + WebSocket server
│   ├── ble_manager.py      # BLE multi-device manager
│   ├── paw_prints.py       # Paw Prints V1.1 BLE protocol
│   ├── tcp_server.py       # Agent TCP server
│   ├── data_buffer.py      # Ring buffer
│   ├── recorder.py         # CSV recorder
│   ├── auth_key.py         # Agent key management
│   ├── recent_devices.py   # Recent device storage
│   └── requirements.txt
├── frontend/
│   └── index.html          # Web control panel
├── run.py                  # One-click launcher
├── LICENSE                 # MIT
└── README.md
```

## Agent TCP API

Connect via TCP to `127.0.0.1:9878`, JSON-line protocol.

### Example

```python
import json, socket

sock = socket.socket()
sock.connect(("127.0.0.1", 9878))

def send(cmd):
    sock.sendall((json.dumps(cmd) + "\n").encode())
    return json.loads(sock.recv(4096).split(b"\n")[0])

# Authenticate (key shown in web panel)
print(send({"cmd": "auth", "key": "your-key"}))

# Query status
print(send({"cmd": "status"}))

# Query last 10 seconds of data
print(send({"cmd": "data", "seconds": 10}))

# Control device 0 shoulder LED
send({"cmd": "led", "device": 0, "color": 2})

# Play LED sequence
send({"cmd": "led_seq", "sequence": [
    {"color": 2, "ms": 300}, {"color": 4, "ms": 300}
], "repeat": True})
```

Full documentation: [Agent Guide (Chinese)](爪印Agent连接指南.md).

## Command Reference

| Command | Description |
|---------|-------------|
| `auth` | Key authentication |
| `status` | Device status + request params |
| `data` | Query historical data |
| `subscribe` | Subscribe to real-time D0 push |
| `led` | Shoulder LED color |
| `led_seq` | LED sequence |
| `d0_start/stop` | D0 stream on/off |
| `cache_duration` | Buffer duration setting |
| `params` | Query saved request params |
| `cmd` | Generic command (cmd_5f/cmd_60) |

All commands support optional `device` parameter to target a specific device.

## Protocol Reference

- [DG-LAB Paw Prints V1.1 BLE Protocol](https://github.com/dg-lab/dglab)

## License

MIT
