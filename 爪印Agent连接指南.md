# 爪印 Agent 连接指南 v2

## 连接信息

| 项目 | 值 |
|------|-----|
| 协议 | TCP (JSON 行) |
| 地址 | `127.0.0.1` |
| 端口 | `9878` |
| 验证 | 连接后第一条消息发送密钥 |

密钥在浏览器面板 **🤖 Agent 连接** 区域查看/复制。

---

## 协议格式

**所有消息都是 JSON + 换行符 `\n`**

- Agent → 服务端：`{"cmd": "xxx", ...}\n`
- 服务端 → Agent：`{"type": "xxx", ...}\n`

连接后必须**先发 `auth`**，否则其他指令一律拒绝。

---

## 多设备支持

所有指令支持可选的 `device` 参数，不传则广播到全部设备：

```json
{"cmd": "led", "device": 0, "color": 2}
{"cmd": "d0_start", "device": 1, "color": 1}
```

D0 推送数据自动带 `device_id` 字段标识来源设备。

---

## 指令清单

### 验证

```json
{"cmd": "auth", "key": "你的密钥"}
```

返回：`{"type": "auth_ok", "message": "验证通过"}`

---

### 设备状态

```json
{"cmd": "status"}
```

返回：

```json
{
  "type": "ok",
  "data": {
    "connected": true,
    "battery": 85,
    "buffer_count": 243,
    "buffer_duration": 120,
    "subscriptions": 1,
    "agent_params": {
      "last_data_seconds": 10,
      "last_data_freq": 5,
      "last_data_time": 1719817201.5,
      "subscribe_freq": 0,
      "subscribe_time": 1719817205.2
    }
  }
}
```

---

### 查询历史数据

获取最近 N 秒数据，可选 `freq` 记录请求频率：

```json
{"cmd": "data", "seconds": 10, "freq": 5}
{"cmd": "data_since", "ts": 1719817200.5}
```

返回：

```json
{
  "type": "ok",
  "data": {
    "count": 100,
    "entries": [
      {
        "device_id": 0,
        "angle_x": 10, "angle_y": -5, "angle_z": 80,
        "acceleration": 12, "voltage": 0.0,
        "pressed": false, "voltage_raw": 0,
        "_ts": 1719817201.234
      }
    ]
  }
}
```

每条数据字段：
- `device_id` — 来源设备 ID
- `angle_x / angle_y / angle_z` — 三轴角度 -128~127
- `acceleration` — 加速度值 0~400
- `pressed` — 按钮是否按下
- `voltage` — 外部电压 (V)
- `_ts` — Unix 时间戳

---

### 查询请求参数

```json
{"cmd": "params"}
```

返回：`{"type": "ok", "data": {"last_data_seconds": 10, ...}}`

---

### 实时订阅

```json
{"cmd": "subscribe", "freq": 0}
```

订阅后持续推送：

```json
{"type": "d0", "data": {"device_id":0, "angle_x":10, "angle_y":-5, ...}}
```

取消订阅：

```json
{"cmd": "unsubscribe"}
```

---

### LED 控制

**主指示灯颜色（50 指令）：**

```json
{"cmd": "d0_start", "device": 0, "color": 1}
{"cmd": "d0_stop", "device": 0, "color": 1}
```

**肩灯常亮：**

```json
{"cmd": "led", "device": 0, "color": 4}
```

**肩灯闪烁：**

```json
{"cmd": "led_flash", "device": 0, "color1": 2, "color2": 4, "speed": 1}
```

| speed | 效果 |
|-------|------|
| 1 | 慢闪 |
| 2 | 快闪 |
| 3 | 停止 |

**颜色表：**

| 值 | 颜色 | 主灯 | 肩灯 |
|----|------|:--:|:--:|
| 0 | 熄灭 | - | ✅ |
| 1 | 黄 | ✅ | ✅ |
| 2 | 红 | ✅ | ✅ |
| 3 | 紫 | ✅ | ✅ |
| 4 | 蓝 | ✅ | ✅ |
| 5 | 青 | ✅ | ✅ |
| 6 | 绿 | ✅ | ✅ |
| 7 | 白 | ❌ | ✅ |

> 主指示灯只支持 0x01~0x06

**灯效序列：**

```json
{
  "cmd": "led_seq",
  "device": 0,
  "sequence": [
    {"color": 2, "ms": 300},
    {"color": 0, "ms": 200},
    {"color": 4, "ms": 300},
    {"color": 0, "ms": 200}
  ],
  "repeat": true
}
```

- `color` — 肩灯颜色值
- `ms` — 持续时间 10~10000 毫秒
- `repeat` — `true` 循环，`false` 播放一遍

停止：`{"cmd": "led_stop"}`

---

### 缓存时长

```json
{"cmd": "cache_duration", "seconds": 300}
```

范围 1~3600 秒。

---

### 通用指令

```json
{"cmd": "cmd", "sub_cmd": "cmd_5f", "device": 0}
{"cmd": "cmd", "sub_cmd": "cmd_60", "device": 0}
```

- `cmd_5f` — 重置参数
- `cmd_60` — 自动角度校准

---

## Python 完整示例

```python
import json, socket, time

HOST, PORT = "127.0.0.1", 9878
KEY = "你的密钥"

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect((HOST, PORT))

def send(cmd):
    sock.sendall((json.dumps(cmd) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(4096)
    return json.loads(buf.split(b"\n")[0])

# 1. 验证
print(send({"cmd": "auth", "key": KEY})["message"])

# 2. 状态（含请求参数）
r = send({"cmd": "status"})
print(f"设备: {r['data']['connected']}, 缓存: {r['data']['buffer_count']}条")
print(f"上次请求: {r['data']['agent_params']}")

# 3. 查数据（带频率记录）
r = send({"cmd": "data", "seconds": 10, "freq": 5})
print(f"返回 {r['data']['count']} 条")

# 4. 开 D0（设备 0）
send({"cmd": "d0_start", "device": 0, "color": 1})

# 5. 灯效（设备 1 肩灯红蓝交替）
send({"cmd": "led_seq", "device": 1, "sequence": [
    {"color": 2, "ms": 300}, {"color": 0, "ms": 200},
    {"color": 4, "ms": 300}, {"color": 0, "ms": 200},
], "repeat": True})
time.sleep(3)
send({"cmd": "led_stop"})

# 6. 查保存的请求参数
print(send({"cmd": "params"}))

sock.close()
```

---

## 常见灯效

### 呼吸
```json
{"cmd": "led_seq", "sequence": [{"color": 2, "ms": 500}, {"color": 0, "ms": 500}], "repeat": true}
```

### 警灯
```json
{"cmd": "led_seq", "sequence": [{"color": 2, "ms": 200}, {"color": 4, "ms": 200}], "repeat": true}
```

### 彩虹
```json
{"cmd": "led_seq", "sequence": [
  {"color": 1, "ms": 300}, {"color": 3, "ms": 300}, {"color": 4, "ms": 300},
  {"color": 5, "ms": 300}, {"color": 6, "ms": 300}, {"color": 2, "ms": 300}
], "repeat": true}
```

### SOS
```json
{"cmd": "led_seq", "sequence": [
  {"color": 2, "ms": 150}, {"color": 0, "ms": 150}, {"color": 2, "ms": 150},
  {"color": 0, "ms": 150}, {"color": 2, "ms": 150}, {"color": 0, "ms": 500},
  {"color": 2, "ms": 500}, {"color": 0, "ms": 150}, {"color": 2, "ms": 500},
  {"color": 0, "ms": 150}, {"color": 2, "ms": 500}, {"color": 0, "ms": 500},
  {"color": 2, "ms": 150}, {"color": 0, "ms": 150}, {"color": 2, "ms": 150},
  {"color": 0, "ms": 150}, {"color": 2, "ms": 150}, {"color": 0, "ms": 2000}
], "repeat": false}
```
