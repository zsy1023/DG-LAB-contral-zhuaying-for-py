"""
爪印 Web 蓝牙控制面板 — FastAPI + WebSocket 服务端
==================================================
"""

import json
import logging
import os
import time
import asyncio
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ble_manager import BLEManager
from data_buffer import DataBuffer
from tcp_server import AgentTCPServer
from auth_key import get_key, regenerate_key
from recent_devices import add_device, get_recent
from recorder import Recorder, list_recordings, load_recording
from paw_prints import (
    LEDColor,
    cmd_50_no_trigger,
    cmd_50_d0_mode,
    cmd_50_random_reaction,
    cmd_50_probability,
    cmd_50_external_voltage,
    cmd_50_press_accel,
    cmd_5f,
    cmd_60,
    cmd_70_solid,
    cmd_70_flash,
)

# ============================================================
# 日志
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("server")

# ============================================================
# 全局状态
# ============================================================
_buffer = DataBuffer(max_seconds=120)
ble = BLEManager(data_buffer=_buffer)
tcp_server = AgentTCPServer(ble, _buffer)
recorder = Recorder()
ws_clients: list[WebSocket] = []

# Webhook 配置
_webhook_url: str = ""
_webhook_events: list[str] = []  # 要推送的事件类型: d0, 5a, 5b, 5c

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


# ============================================================
# BLE 回调 → WebSocket 广播
# ============================================================
async def broadcast(msg: dict):
    """向所有连接的 WebSocket 客户端广播消息"""
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


async def on_ble_notify(data: dict):
    """BLE 收到通知 → 广播给前端 + 推送 TCP + 录制 + Webhook"""
    await broadcast(data)
    # D0 数据推送给订阅了实时推送的 TCP Agent
    if data.get("type") == "notify_d0":
        tcp_server.broadcast_d0(data["data"])
        recorder.push(data["data"])
    # Webhook 推送
    _maybe_webhook(data)


async def on_ble_status(status: str, data: dict):
    """BLE 状态变化 → 广播给前端"""
    if status == "connected":
        add_device(data.get("address", ""), data.get("name", ""))
    await broadcast({"type": status, "data": data})
    # 状态变化后同步设备列表
    await broadcast({"type": "devices_info", "data": {"devices": ble.all_devices_info()}})


def _maybe_webhook(data: dict):
    """异步触发 Webhook（fire-and-forget）"""
    if not _webhook_url or not _webhook_events:
        return
    event_type = data.get("type", "")
    # 映射: notify_d0 → d0, notify_5a → 5a
    short = event_type.replace("notify_", "")
    if short not in _webhook_events:
        return
    asyncio.ensure_future(_send_webhook(short, data.get("data", {})))


async def _send_webhook(event_type: str, event_data: dict):
    """发送 HTTP POST 到 Webhook URL"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"event": event_type, "data": event_data, "ts": time.time()}
            async with session.post(_webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                logger.debug(f"Webhook → {_webhook_url} [{event_type}] → {resp.status}")
    except Exception as e:
        logger.warning(f"Webhook 发送失败: {e}")


# ============================================================
# FastAPI 应用
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    ble.on_notify(on_ble_notify)
    ble.on_status(on_ble_status)
    await tcp_server.start()
    logger.info("🟢 服务端启动完成")
    yield
    # 关闭时清理
    await tcp_server.stop()
    if ble.connected:
        await ble.disconnect()
    logger.info("🔴 服务端已关闭")


app = FastAPI(title="爪印控制面板", lifespan=lifespan)


# ============================================================
# 静态文件 & 首页
# ============================================================
@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ============================================================
# WebSocket — 指令处理
# ============================================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    logger.info("WebSocket 客户端已连接")

    # 发送当前连接状态
    if ble.connected:
        await ws.send_text(json.dumps({
            "type": "devices_info",
            "data": {"devices": ble.all_devices_info()}
        }, ensure_ascii=False))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({
                    "type": "error", "data": {"message": "JSON 解析失败"}
                }, ensure_ascii=False))
                continue

            cmd = msg.get("cmd", "")
            data = msg.get("data", {})

            try:
                await handle_command(ws, cmd, data)
            except Exception as e:
                logger.error(f"指令处理失败 [{cmd}]: {e}")
                await ws.send_text(json.dumps({
                    "type": "error", "data": {"message": str(e)}
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端已断开")
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


# ============================================================
# 指令分发
# ============================================================
async def handle_command(ws: WebSocket, cmd: str, data: dict):
    """根据 cmd 分发到对应的处理函数"""

    # ---- 扫描（渐进式） ----
    if cmd == "scan":
        async def _on_found(device_info: dict):
            await ws.send_text(json.dumps({
                "type": "scan_result", "data": device_info
            }, ensure_ascii=False))
        devices = await ble.scan_progressive(
            timeout_sec=data.get("timeout", 5), on_found=_on_found)
        await ws.send_text(json.dumps({
            "type": "scan_done", "data": {"total": len(devices)}
        }, ensure_ascii=False))

    # ---- 连接 ----
    elif cmd == "connect":
        address = data.get("address", "")
        name = data.get("name", "")
        if not address:
            await ws.send_text(json.dumps({
                "type": "error", "data": {"message": "请提供设备地址"}
            }, ensure_ascii=False))
            return
        did = await ble.connect(address, name)
        if did < 0:
            await ws.send_text(json.dumps({
                "type": "error", "data": {"message": "连接失败"}
            }, ensure_ascii=False))

    # ---- 断开 ----
    elif cmd == "disconnect":
        did = data.get("device_id")
        await ble.disconnect(did)

    # ---- 50 指令 ----
    elif cmd == "cmd_50_no_trigger":
        led = data.get("led_color", 0x01)
        await ble.send_command(cmd_50_no_trigger(led), data.get("device_id"))

    elif cmd == "cmd_50_d0":
        led = data.get("led_color", 0x01)
        await ble.send_command(cmd_50_d0_mode(led), data.get("device_id"))

    elif cmd == "cmd_50_random":
        await ble.send_command(cmd_50_random_reaction(
            led_color=data.get("led_color", 0x01),
            event_id=data.get("event_id", 1),
            green_min_sec=data.get("green_min_sec", 10),
            green_max_sec=data.get("green_max_sec", 60),
            reaction_sec=data.get("reaction_sec", 10),
            trigger_increase=data.get("trigger_increase", 20),
            trigger_speed=data.get("trigger_speed", 20),
            cancel_decrease=data.get("cancel_decrease", 50),
            cancel_speed=data.get("cancel_speed", 20),
        ))

    elif cmd == "cmd_50_probability":
        events_raw = data.get("events", [])
        events = [(e["id"], e["prob"]) for e in events_raw]
        await ble.send_command(cmd_50_probability(
            led_color=data.get("led_color", 0x01),
            events=events,
            cooldown_sec=data.get("cooldown_sec", 60),
        ))

    elif cmd == "cmd_50_voltage":
        await ble.send_command(cmd_50_external_voltage(
            led_color=data.get("led_color", 0x01),
            event_id=data.get("event_id", 1),
            use_pullup=data.get("use_pullup", True),
            voltage_min=data.get("voltage_min", 50),
            voltage_max=data.get("voltage_max", 150),
            param_map_range=data.get("param_map_range", 50),
        ))

    elif cmd == "cmd_50_press_accel":
        await ble.send_command(cmd_50_press_accel(
            led_color=data.get("led_color", 0x01),
            press_event_id=data.get("press_event_id", 0),
            press_mode=data.get("press_mode", 0),
            press_trigger_increase=data.get("press_trigger_increase", 20),
            press_trigger_speed=data.get("press_trigger_speed", 20),
            press_cancel_decrease=data.get("press_cancel_decrease", 50),
            press_cancel_speed=data.get("press_cancel_speed", 20),
            accel_event_id=data.get("accel_event_id", 0),
            accel_mode=data.get("accel_mode", 0),
            accel_trigger_debounce=data.get("accel_trigger_debounce", 3),
            accel_cancel_debounce=data.get("accel_cancel_debounce", 6),
            accel_detect_mode=data.get("accel_detect_mode", 1),
            accel_threshold=data.get("accel_threshold", 100),
            x_min=data.get("x_min", -128), x_max=data.get("x_max", 127),
            y_min=data.get("y_min", -128), y_max=data.get("y_max", 127),
            z_min=data.get("z_min", -128), z_max=data.get("z_max", 127),
            param_map_range=data.get("param_map_range", 100),
        ))

    # ---- 5F 参数重置 ----
    elif cmd == "cmd_5f":
        await ble.send_command(cmd_5f(), data.get("device_id"))

    # ---- 60 自动角度校准 ----
    elif cmd == "cmd_60":
        await ble.send_command(cmd_60(), data.get("device_id"))

    # ---- 70 LED 控制 ----
    elif cmd == "cmd_70_solid":
        await ble.send_command(cmd_70_solid(data.get("color", 0x01)), data.get("device_id"))

    elif cmd == "cmd_70_flash":
        await ble.send_command(cmd_70_flash(
            data.get("color1", 0x02),
            data.get("color2", 0x04),
            data.get("speed", 0x01),
        ), data.get("device_id"))

    else:
        await ws.send_text(json.dumps({
            "type": "error", "data": {"message": f"未知指令: {cmd}"}
        }, ensure_ascii=False))


# ============================================================
# REST API — Agent 密钥管理 + 缓存控制
# ============================================================

@app.get("/api/key")
async def api_get_key():
    """获取当前 Agent TCP 密钥（前端用）"""
    return {
        "key": get_key(),
        "tcp_port": 9878,
        "tcp_host": "127.0.0.1",
    }


@app.post("/api/key/regenerate")
async def api_regenerate_key():
    """重新生成 Agent TCP 密钥"""
    new_key = regenerate_key()
    return {"key": new_key}


@app.get("/api/buffer/info")
async def api_buffer_info():
    """获取缓冲区信息"""
    return {
        "count": _buffer.count,
        "duration": _buffer.duration,
    }


@app.post("/api/buffer/duration")
async def api_buffer_duration(data: dict = Body(...)):
    """设置缓冲区时长"""
    sec = data.get("seconds", 120)
    _buffer.set_duration(sec)
    return {"duration": _buffer.duration}


@app.get("/api/devices/recent")
async def api_devices_recent():
    """获取最近连接过的设备列表"""
    return {"devices": get_recent()}


# ============================================================
# REST API — 录制
# ============================================================

@app.post("/api/record/start")
async def api_record_start():
    filename = recorder.start()
    return {"recording": True, "filename": filename}


@app.post("/api/record/stop")
async def api_record_stop():
    info = recorder.stop()
    return {"recording": False, **info}


@app.get("/api/record/status")
async def api_record_status():
    return {
        "recording": recorder.recording,
        "filename": recorder.filename,
        "count": recorder.count,
        "elapsed": round(recorder.elapsed, 1),
    }


@app.get("/api/record/list")
async def api_record_list():
    return {"files": list_recordings()}


@app.get("/api/record/load")
async def api_record_load(file: str = ""):
    data = load_recording(file)
    return {"filename": file, "count": len(data), "data": data}


@app.get("/api/record/download")
async def api_record_download(file: str = ""):
    """下载录制文件"""
    from recorder import RECORD_DIR
    from fastapi.responses import FileResponse
    path = os.path.join(RECORD_DIR, file)
    if not os.path.exists(path):
        return {"error": "文件不存在"}
    return FileResponse(path, media_type="text/csv", filename=file)


# ============================================================
# REST API — Webhook
# ============================================================

@app.get("/api/webhook/config")
async def api_webhook_get():
    return {"url": _webhook_url, "events": _webhook_events}


@app.post("/api/webhook/config")
async def api_webhook_set(data: dict = Body(...)):
    global _webhook_url, _webhook_events
    _webhook_url = data.get("url", "")
    _webhook_events = data.get("events", [])
    logger.info(f"Webhook 配置更新: {_webhook_url} 事件={_webhook_events}")
    return {"url": _webhook_url, "events": _webhook_events}


# ============================================================
# 直接启动
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=9879)
