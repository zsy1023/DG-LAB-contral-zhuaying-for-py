"""
BLE 管理器 — 多设备支持
========================
同时管理多台爪印设备的连接/收发。
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable

from bleak import BleakScanner, BleakClient

from paw_prints import (
    DEVICE_NAMES,
    SERVICE_UUID, WRITE_CHAR, NOTIFY_CHAR,
    BATTERY_SVC, BATTERY_CHAR,
    parse_notify, cmd_50_no_trigger,
)

logger = logging.getLogger(__name__)

NotifyCallback = Callable[[dict], Awaitable[None]]
StatusCallback = Callable[[str, dict], Awaitable[None]]


class DeviceConnection:
    """单个爪印设备的连接状态"""
    __slots__ = ('device_id', 'address', 'name', 'client', 'battery', 'connected')
    
    def __init__(self, device_id: int, address: str, name: str = ""):
        self.device_id = device_id
        self.address = address
        self.name = name or address
        self.client: Optional[BleakClient] = None
        self.battery = -1
        self.connected = False


class BLEManager:
    """管理多台爪印 BLE 连接"""

    def __init__(self, data_buffer=None):
        self._devices: dict[int, DeviceConnection] = {}  # device_id → DeviceConnection
        self._notify_cb: Optional[NotifyCallback] = None
        self._status_cb: Optional[StatusCallback] = None
        self._next_id = 0
        self._buffer = data_buffer

    def on_notify(self, cb: NotifyCallback):
        self._notify_cb = cb

    def on_status(self, cb: StatusCallback):
        self._status_cb = cb

    async def _emit_status(self, status: str, data: dict = None):
        if self._status_cb:
            await self._status_cb(status, data or {})

    async def _emit_notify(self, data: dict):
        if self._notify_cb:
            await self._notify_cb(data)

    # ---- 属性 ----
    @property
    def device_count(self) -> int:
        return len(self._devices)

    @property
    def device_ids(self) -> list[int]:
        return list(self._devices.keys())

    def get_device(self, device_id: int) -> Optional[DeviceConnection]:
        return self._devices.get(device_id)

    def get_name(self, device_id: int) -> str:
        dev = self._devices.get(device_id)
        return dev.name if dev else ""

    @property
    def connected(self) -> bool:
        """至少有一台连接"""
        return any(d.connected for d in self._devices.values())

    @property
    def battery(self) -> int:
        """返回第一台设备的电量（兼容旧接口）"""
        for d in self._devices.values():
            if d.connected and d.battery >= 0:
                return d.battery
        return -1

    def connected_ids(self) -> list[int]:
        return [did for did, d in self._devices.items() if d.connected]

    def all_devices_info(self) -> list[dict]:
        return [{
            "device_id": d.device_id, "address": d.address,
            "name": d.name, "battery": d.battery,
            "connected": d.connected,
        } for d in self._devices.values()]

    # ---- 扫描 ----
    @staticmethod
    def _rssi_to_distance(rssi: int, tx_power: int = -59) -> float:
        """RSSI 转粗略距离 (米)，仅供参考"""
        if rssi >= tx_power:
            return 0.5
        # 对数路径损耗模型，n=2.5 (室内)
        ratio = (tx_power - rssi) / (10 * 2.5)
        return round(pow(10, ratio), 1)

    async def scan_progressive(self, timeout_sec=5.0, on_found=None) -> list[dict]:
        """渐进扫描：边扫边推结果"""
        all_devices: dict[str, dict] = {}
        _found_set = set()

        def _on_device(device, advertisement_data):
            name = device.name or (advertisement_data.local_name if advertisement_data else "") or ""
            addr = device.address
            rssi = advertisement_data.rssi if advertisement_data else 0
            if any(n in name for n in DEVICE_NAMES) and addr not in _found_set:
                _found_set.add(addr)
                dist = BLEManager._rssi_to_distance(rssi)
                info = {"name": name, "address": addr, "rssi": rssi, "distance": dist}
                all_devices[addr] = info
                if on_found:
                    asyncio.ensure_future(on_found(info))
                logger.info(f"  ✓ 发现: {name} [{addr}] RSSI={rssi}")

        logger.info(f"开始扫描 ({timeout_sec}s)...")
        scanner = BleakScanner(detection_callback=_on_device)
        await scanner.start()
        await asyncio.sleep(timeout_sec)
        await scanner.stop()
        logger.info(f"扫描完成: {len(all_devices)} 台爪印")
        return list(all_devices.values())

    async def scan(self, timeout_sec: float = 5.0) -> list[dict]:
        """扫描（委托给 scan_progressive）"""
        return await self.scan_progressive(timeout_sec)

    # ---- 连接 ----
    async def connect(self, address: str, name: str = "") -> int:
        """连接设备，返回 device_id"""
        # 检查是否已连接
        for did, dev in self._devices.items():
            if dev.address == address and dev.connected:
                return did

        device_id = self._next_id
        self._next_id += 1
        dev = DeviceConnection(device_id, address, name)
        self._devices[device_id] = dev

        try:
            logger.info(f"[{device_id}] 正在连接 {address}...")
            dev.client = BleakClient(address, timeout=15.0)
            await dev.client.connect()
            dev.connected = True

            # 订阅通知
            await dev.client.start_notify(
                NOTIFY_CHAR,
                lambda s, d: asyncio.ensure_future(self._on_notification(device_id, d))
            )
            logger.info(f"[{device_id}] 已订阅 NOTIFY")

            # 读取电量
            try:
                battery_data = await dev.client.read_gatt_char(BATTERY_CHAR)
                dev.battery = battery_data[0] if battery_data else -1
            except Exception:
                dev.battery = -1

            # 初始 50 指令
            await dev.client.write_gatt_char(WRITE_CHAR, cmd_50_no_trigger(0x01), response=False)

            await self._emit_status("connected", {
                "device_id": device_id,
                "address": address,
                "name": dev.name,
                "battery": dev.battery,
            })
            logger.info(f"[{device_id}] 连接成功: {address}")
            return device_id

        except Exception as e:
            logger.error(f"[{device_id}] 连接失败: {e}")
            dev.connected = False
            dev.client = None
            await self._emit_status("error", {"message": f"连接失败: {e}"})
            return -1

    # ---- 断开 ----
    async def disconnect(self, device_id: int = None):
        """断开指定设备（None=全部）"""
        ids = [device_id] if device_id is not None else list(self._devices.keys())
        for did in ids:
            dev = self._devices.get(did)
            if not dev or not dev.client:
                continue
            try:
                if dev.client.is_connected:
                    await dev.client.disconnect()
            except Exception:
                pass
            dev.connected = False
            dev.client = None
            await self._emit_status("disconnected", {"device_id": did})

        # 清理
        if device_id is not None:
            self._devices.pop(device_id, None)

    # ---- 发送指令 ----
    async def send_command(self, data: bytes, device_id: int = None):
        """发送指令（device_id=None 发全部）"""
        ids = [device_id] if device_id is not None else self.connected_ids()
        for did in ids:
            dev = self._devices.get(did)
            if not dev or not dev.client or not dev.client.is_connected:
                if device_id is not None:
                    raise ConnectionError(f"设备 {did} 未连接")
                continue
            await dev.client.write_gatt_char(WRITE_CHAR, data, response=False)

    # ---- 通知处理 ----
    async def _on_notification(self, device_id: int, data: bytearray):
        parsed = parse_notify(bytes(data))
        if not parsed:
            return
        # 加上 device_id
        parsed["device_id"] = device_id
        if "data" in parsed and isinstance(parsed["data"], dict):
            parsed["data"]["device_id"] = device_id

        # 更新电量
        if parsed["type"] == "notify_51":
            dev = self._devices.get(device_id)
            if dev:
                dev.battery = parsed["data"].get("battery", -1)

        # 写入缓冲区
        if parsed["type"] == "notify_d0" and self._buffer is not None:
            self._buffer.push(parsed["data"])

        await self._emit_notify(parsed)
