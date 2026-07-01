"""
已连接设备记录
==============
存储到 backend/recent_devices.json，最多保留 10 条。
"""
import json
import os
from datetime import datetime

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recent_devices.json")


def load() -> list[dict]:
    if not os.path.exists(STORE_FILE):
        return []
    try:
        with open(STORE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save(devices: list[dict]):
    with open(STORE_FILE, "w") as f:
        json.dump(devices, f, ensure_ascii=False, indent=2)


def add_device(address: str, name: str):
    devices = load()
    # 移除同地址旧记录
    devices = [d for d in devices if d["address"] != address]
    # 插到最前面
    devices.insert(0, {
        "address": address,
        "name": name,
        "last_connected": datetime.now().isoformat(timespec="seconds"),
    })
    # 最多 10 条
    devices = devices[:10]
    save(devices)


def get_recent() -> list[dict]:
    return load()
