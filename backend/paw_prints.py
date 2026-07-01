"""
爪印无线按钮传感器 V1.1 — 蓝牙协议实现
==========================================
指令构建 + 响应解析

设备蓝牙名称: 47L120300
服务 UUID:      0x180C
写特性 UUID:    0x150A  (发送指令)
通知特性 UUID:  0x150B  (接收通知)
电量服务 UUID:  0x180A
电量特性 UUID:  0x1500  (读/通知)

基础 UUID: 0000xxxx-0000-1000-8000-00805f9b34fb
"""

import struct
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional, Tuple


def _to_signed(b: int) -> int:
    """将 unsigned byte 转为 signed (-128~127)"""
    return b if b <= 127 else b - 256


# ============================================================
# UUID 定义
# ============================================================
BASE_UUID = "0000{}-0000-1000-8000-00805f9b34fb"

SERVICE_UUID  = BASE_UUID.format("180C")   # 主服务
WRITE_CHAR    = BASE_UUID.format("150A")   # 写特性（发指令）
NOTIFY_CHAR   = BASE_UUID.format("150B")   # 通知特性（收数据）
BATTERY_SVC   = BASE_UUID.format("180A")   # 电量服务
BATTERY_CHAR  = BASE_UUID.format("1500")   # 电量特性

DEVICE_NAMES  = ["47L120300", "47L120100"]  # V1.1 / V1.0


# ============================================================
# 颜色枚举
# ============================================================
class LEDColor(IntEnum):
    OFF    = 0x00
    YELLOW = 0x01
    RED    = 0x02
    PURPLE = 0x03
    BLUE   = 0x04
    CYAN   = 0x05
    GREEN  = 0x06
    WHITE  = 0x07

    @classmethod
    def label(cls, c: int) -> str:
        labels = {0: "熄灭", 1: "黄", 2: "红", 3: "紫", 4: "蓝", 5: "青", 6: "绿", 7: "白"}
        return labels.get(c, f"未知({c})")


# ============================================================
# 指令构建
# ============================================================

def cmd_50_no_trigger(led_color: int) -> bytes:
    """50 指令 — 无任何触发模式（连接后先发这个，防止断开）"""
    return bytes([0x50, led_color & 0xFF, 0x00] + [0x00] * 14)


def cmd_50_d0_mode(led_color: int) -> bytes:
    """50 指令 — D0 直传模式，每 100ms 上报物理数据"""
    return bytes([0x50, led_color & 0xFF, 0xD0] + [0x00] * 14)


def cmd_50_random_reaction(
    led_color: int,
    event_id: int,
    green_min_sec: int,
    green_max_sec: int,
    reaction_sec: int,
    trigger_increase: int,
    trigger_speed: int,
    cancel_decrease: int,
    cancel_speed: int,
) -> bytes:
    """50 指令 — 随机反应触发模式"""
    return bytes([0x50, led_color & 0xFF, 0x03,
        event_id & 0xFF,
        (green_min_sec >> 8) & 0xFF, green_min_sec & 0xFF,
        (green_max_sec >> 8) & 0xFF, green_max_sec & 0xFF,
        (reaction_sec >> 8) & 0xFF, reaction_sec & 0xFF,
        trigger_increase & 0xFF,
        trigger_speed & 0xFF,
        cancel_decrease & 0xFF,
        cancel_speed & 0xFF,
        0x00, 0x00, 0x00])


def cmd_50_probability(
    led_color: int,
    events: list,        # [(event_id, probability), ...] 最多 6 对
    cooldown_sec: int,
) -> bytes:
    """50 指令 — 概率触发模式
    events: [(event_id, prob), ...]  最多 6 个, prob 0~200 映射 0%~100%
    """
    payload = [0x50, led_color & 0xFF, 0x04]
    for i in range(6):
        if i < len(events):
            payload.append(events[i][0] & 0xFF)
            payload.append(events[i][1] & 0xFF)
        else:
            payload.append(0x00)
            payload.append(0x00)
    payload.append((cooldown_sec >> 8) & 0xFF)
    payload.append(cooldown_sec & 0xFF)
    return bytes(payload)


def cmd_50_external_voltage(
    led_color: int,
    event_id: int,
    use_pullup: bool,          # True=高电平(内置上拉), False=高阻态
    voltage_min: int,          # 0~210 映射 0.00V~2.10V
    voltage_max: int,          # 0~210
    param_map_range: int,      # 0~210
) -> bytes:
    """50 指令 — 外部电压检测触发"""
    return bytes([0x50, led_color & 0xFF, 0x0F,
        event_id & 0xFF,
        0x01 if use_pullup else 0x00,
        voltage_min & 0xFF,
        voltage_max & 0xFF,
        param_map_range & 0xFF,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def cmd_50_press_accel(
    led_color: int,
    # 按下/抬起部分
    press_event_id: int,        # 1~24, 设 0 则禁用
    press_mode: int,            # 0=按下触发, 1=抬起触发
    press_trigger_increase: int,
    press_trigger_speed: int,   # 0~120
    press_cancel_decrease: int,
    press_cancel_speed: int,    # 0~120
    # 加速度/角度部分
    accel_event_id: int,        # 1~24, 设 0 则禁用
    accel_mode: int,            # 0=加速度, 1=角度
    accel_trigger_debounce: int,  # 0~7, 0~0.7秒
    accel_cancel_debounce: int,   # 0~7
    # 加速度子模式参数
    accel_detect_mode: int,     # 0=低于阈值触发, 1=高于阈值触发
    accel_threshold: int,       # 0~400
    # 角度子模式参数
    x_min: int, x_max: int,     # -128~127
    y_min: int, y_max: int,
    z_min: int, z_max: int,
    # 参数映射
    param_map_range: int,       # 0~255
) -> bytes:
    """50 指令 — 按下/抬起 + 加速度/角度触发"""
    settings_byte = (
        (press_mode & 0x01) << 7 |
        (accel_mode & 0x01) << 6 |
        (accel_trigger_debounce & 0x07) << 3 |
        (accel_cancel_debounce & 0x07)
    )

    if accel_mode == 0:  # 加速度模式
        accel_bytes = [
            accel_detect_mode & 0x01,
            (accel_threshold >> 8) & 0xFF, accel_threshold & 0xFF,
            0x00, 0x00, 0x00]
    else:  # 角度模式
        accel_bytes = [
            x_min & 0xFF, x_max & 0xFF,
            y_min & 0xFF, y_max & 0xFF,
            z_min & 0xFF, z_max & 0xFF]

    return bytes([0x50, led_color & 0xFF, 0x05,
        press_event_id & 0xFF,
        settings_byte,
        press_trigger_speed & 0xFF,
        press_cancel_decrease & 0xFF,
        press_cancel_speed & 0xFF,
        press_trigger_increase & 0xFF,
        accel_event_id & 0xFF,
        *accel_bytes,
        param_map_range & 0xFF])


def cmd_5f() -> bytes:
    """5F 指令 — 重置参数值"""
    return bytes([0x5F])


def cmd_60() -> bytes:
    """60 指令 — 自动检测 XYZ 角度阈值"""
    return bytes([0x60])


def cmd_70_solid(led_color: int) -> bytes:
    """70 指令 — 点亮肩灯为指定颜色"""
    return bytes([0x70, led_color & 0xFF])


def cmd_70_flash(color1: int, color2: int, speed: int) -> bytes:
    """70 指令 — 肩灯闪烁
    speed: 0x01=慢速, 0x02=快速, 0x03=停止
    """
    return bytes([0x70, color1 & 0xFF, color2 & 0xFF, speed & 0xFF])


# ============================================================
# 响应解析
# ============================================================

@dataclass
class Notify51:
    """51 消息 — 设备信息"""
    led_color: int
    device_type: int   # 0x03 = 爪印 V1.1
    battery: int       # 0~100

    @classmethod
    def parse(cls, data: bytes) -> Optional["Notify51"]:
        if len(data) < 4 or data[0] != 0x51:
            return None
        return cls(led_color=data[1], device_type=data[2], battery=data[3])

    def to_dict(self) -> dict:
        return {"type": "notify_51", "data": {
            "led_color": self.led_color,
            "led_color_label": LEDColor.label(self.led_color),
            "device_type": self.device_type,
            "battery": self.battery}}


@dataclass
class Notify5A:
    """5A 消息 — 事件触发"""
    led_color: int
    event_id: int
    param_value: int

    @classmethod
    def parse(cls, data: bytes) -> Optional["Notify5A"]:
        if len(data) < 4 or data[0] != 0x5A:
            return None
        return cls(led_color=data[1], event_id=data[2], param_value=data[3])

    def to_dict(self) -> dict:
        return {"type": "notify_5a", "data": {
            "led_color": self.led_color,
            "event_id": self.event_id,
            "param_value": self.param_value}}


@dataclass
class Notify5B:
    """5B 消息 — 取消触发"""
    led_color: int
    event_id: int

    @classmethod
    def parse(cls, data: bytes) -> Optional["Notify5B"]:
        if len(data) < 3 or data[0] != 0x5B:
            return None
        return cls(led_color=data[1], event_id=data[2])

    def to_dict(self) -> dict:
        return {"type": "notify_5b", "data": {
            "led_color": self.led_color,
            "event_id": self.event_id}}


@dataclass
class Notify5C:
    """5C 消息 — 参数值变化"""
    led_color: int
    event_id: int
    param_value: int

    @classmethod
    def parse(cls, data: bytes) -> Optional["Notify5C"]:
        if len(data) < 4 or data[0] != 0x5C:
            return None
        return cls(led_color=data[1], event_id=data[2], param_value=data[3])

    def to_dict(self) -> dict:
        return {"type": "notify_5c", "data": {
            "led_color": self.led_color,
            "event_id": self.event_id,
            "param_value": self.param_value}}


@dataclass
class NotifyD0:
    """D0 消息 — 物理数据流 (每 100ms)"""
    led_color: int
    seq: int
    pressed: bool           # True=按下, False=抬起
    acceleration: int       # 加速度值
    angle_x: int            # X 轴角度 -128~127
    angle_y: int            # Y 轴角度 -128~127
    angle_z: int            # Z 轴角度 -128~127
    voltage_raw: int        # 外部电压原始值

    @classmethod
    def parse(cls, data: bytes) -> Optional["NotifyD0"]:
        if len(data) < 9 or data[0] != 0xD0:
            return None
        return cls(
            led_color=data[1],
            seq=data[2],
            pressed=data[3] != 0x00,
            acceleration=data[4],
            angle_x=_to_signed(data[5]),
            angle_y=_to_signed(data[6]),
            angle_z=_to_signed(data[7]),
            voltage_raw=data[8])

    def voltage(self) -> float:
        """电压值 (V), 粗略换算"""
        return self.voltage_raw * 0.01

    def to_dict(self) -> dict:
        return {"type": "notify_d0", "data": {
            "led_color": self.led_color,
            "seq": self.seq,
            "pressed": self.pressed,
            "acceleration": self.acceleration,
            "angle_x": self.angle_x,
            "angle_y": self.angle_y,
            "angle_z": self.angle_z,
            "voltage_raw": self.voltage_raw,
            "voltage": round(self.voltage(), 2)}}


@dataclass
class NotifyF1:
    """F1 消息 — 自动角度阈值检测结果"""
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    z_min: int
    z_max: int

    @classmethod
    def parse(cls, data: bytes) -> Optional["NotifyF1"]:
        if len(data) < 8 or data[0] != 0xF1:
            return None
        return cls(
            _to_signed(data[2]), _to_signed(data[3]),
            _to_signed(data[4]), _to_signed(data[5]),
            _to_signed(data[6]), _to_signed(data[7]))

    def to_dict(self) -> dict:
        return {"type": "notify_f1", "data": {
            "x_range": [self.x_min, self.x_max],
            "y_range": [self.y_min, self.y_max],
            "z_range": [self.z_min, self.z_max]}}


# ============================================================
# 通用解析入口
# ============================================================

def parse_notify(data: bytes) -> Optional[dict]:
    """解析蓝牙通知数据，返回可 JSON 化的 dict"""
    if not data:
        return None
    head = data[0]
    parsers = {
        0x51: Notify51,
        0x5A: Notify5A,
        0x5B: Notify5B,
        0x5C: Notify5C,
        0xD0: NotifyD0,
        0xF1: NotifyF1,
    }
    parser = parsers.get(head)
    if parser is None:
        return None
    result = parser.parse(data)
    if result is None:
        return None
    return result.to_dict()
