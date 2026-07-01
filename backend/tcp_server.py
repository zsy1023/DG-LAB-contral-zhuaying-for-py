"""
Agent TCP 服务端
================
端口 9878，JSON 行协议，密钥验证。

协议:
  Agent → Server: {"cmd": "...", ...}\n
  Server → Agent: {"type": "...", ...}\n

支持指令: auth, status, data, data_since, subscribe, unsubscribe,
          led, led_seq, led_stop, d0_start, d0_stop, cache_duration, cmd
"""

import asyncio
import json
import logging
import time
from typing import Optional

from auth_key import get_key
from data_buffer import DataBuffer
from paw_prints import (
    cmd_50_d0_mode,
    cmd_50_no_trigger,
    cmd_70_solid,
    cmd_70_flash,
    cmd_5f,
    cmd_60,
)

logger = logging.getLogger("tcp_server")

TCP_PORT = 9878


# ============================================================
# TCP 服务端
# ============================================================
class AgentTCPServer:
    """TCP 服务端，管理所有 Agent 连接"""

    def __init__(self, ble_manager, data_buffer: DataBuffer):
        self._ble = ble_manager
        self._buffer = data_buffer
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: list["AgentConnection"] = []
        self._subscriptions: set["AgentConnection"] = set()
        self._agent_params: dict = {}  # Agent 最近请求参数

    async def start(self):
        # 手动创建 socket 以设置 SO_REUSEADDR（Windows 端口复用）
        import socket as _socket
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", TCP_PORT))
        self._server = await asyncio.start_server(
            self._on_client_connected, sock=sock
        )
        logger.info(f"TCP Agent 服务端已启动: 127.0.0.1:{TCP_PORT}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for client in self._clients[:]:
            await client.close()
        logger.info("TCP Agent 服务端已关闭")

    async def _on_client_connected(self, reader, writer):
        conn = AgentConnection(reader, writer, self._ble, self._buffer, self)
        self._clients.append(conn)
        try:
            await conn.handle()
        except Exception as e:
            logger.warning(f"Agent 连接异常: {e}")
        finally:
            self._subscriptions.discard(conn)
            self._clients.remove(conn)

    def broadcast_d0(self, data: dict):
        """向所有订阅客户端推送 D0 数据"""
        msg = json.dumps({"type": "d0", "data": data}, ensure_ascii=False)
        dead = set()
        for conn in self._subscriptions:
            try:
                conn._send_raw(msg)
            except Exception:
                dead.add(conn)
        self._subscriptions -= dead

    async def next_handle(self):
        """简单写法"""
        pass


# ============================================================
# 单个 Agent 连接
# ============================================================
class AgentConnection:
    """处理单个 Agent TCP 连接"""

    def __init__(self, reader, writer, ble, buffer, server: AgentTCPServer):
        self._reader = reader
        self._writer = writer
        self._ble = ble
        self._buffer = buffer
        self._server = server
        self._authed = False
        self._addr = writer.get_extra_info("peername")
        self._led_task: Optional[asyncio.Task] = None  # 灯效序列任务

    async def close(self):
        self._stop_led_seq()
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    def _send(self, msg: dict):
        """发送 JSON 行"""
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self._send_raw(line)

    def _send_raw(self, line: str):
        try:
            self._writer.write(line.encode())
        except Exception:
            pass

    async def handle(self):
        """主循环：读取行 → 解析 → 处理"""
        buf = b""
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=300)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                await self._process(line.decode("utf-8", errors="replace").strip())

        self._stop_led_seq()
        logger.info(f"Agent 断开: {self._addr}")

    async def _process(self, text: str):
        if not text:
            return
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            self._send({"type": "error", "message": "JSON 解析失败"})
            return

        cmd = msg.get("cmd", "")
        logger.debug(f"Agent [{self._addr}] cmd={cmd}")

        try:
            await self._dispatch(cmd, msg)
        except Exception as e:
            logger.error(f"Agent 指令异常 [{cmd}]: {e}")
            self._send({"type": "error", "message": str(e)})

    async def _dispatch(self, cmd: str, msg: dict):
        # 提取设备 ID（可选）
        device_id = msg.get("device")  # 可以是 int 或 None
        if device_id is not None:
            device_id = int(device_id)

        # ---- auth（必须第一个指令） ----
        if cmd == "auth":
            if msg.get("key") == get_key():
                self._authed = True
                self._send({"type": "auth_ok", "message": "验证通过"})
                logger.info(f"Agent 验证通过: {self._addr}")
            else:
                self._send({"type": "error", "message": "密钥错误"})
                await asyncio.sleep(0.1)
                await self.close()
            return

        # 未验证
        if not self._authed:
            self._send({"type": "error", "message": "请先发送 auth 指令验证"})
            return

        # ---- 状态查询 ----
        if cmd == "status":
            self._send({
                "type": "ok",
                "data": {
                    "connected": self._ble.connected,
                    "battery": self._ble.battery,
                    "buffer_count": self._buffer.count,
                    "buffer_duration": self._buffer.duration,
                    "subscriptions": len(self._server._subscriptions),
                    "agent_params": self._server._agent_params,
                }
            })

        # ---- 数据查询 ----
        elif cmd == "data":
            seconds = msg.get("seconds")
            freq = msg.get("freq", 0)
            self._server._agent_params["last_data_seconds"] = seconds
            self._server._agent_params["last_data_freq"] = freq
            self._server._agent_params["last_data_time"] = time.time()
            entries = self._buffer.get_recent(seconds)
            self._send({
                "type": "ok",
                "data": {"count": len(entries), "entries": entries}
            })

        elif cmd == "data_since":
            ts = msg.get("ts", 0)
            entries = self._buffer.get_since(float(ts))
            self._send({
                "type": "ok",
                "data": {"count": len(entries), "entries": entries}
            })

        # ---- 实时订阅 ----
        elif cmd == "subscribe":
            freq = msg.get("freq", 0)
            self._server._agent_params["subscribe_freq"] = freq
            self._server._agent_params["subscribe_time"] = time.time()
            self._server._subscriptions.add(self)
            self._send({"type": "ok", "message": "已订阅实时 D0 推送"})

        elif cmd == "params":
            self._send({"type": "ok", "data": self._server._agent_params})

        elif cmd == "unsubscribe":
            self._server._subscriptions.discard(self)
            self._send({"type": "ok", "message": "已取消订阅"})

        # ---- LED 控制 ----
        elif cmd == "led":
            color = msg.get("color", 1)
            self._stop_led_seq()
            await self._ble.send_command(cmd_70_solid(color), device_id)
            self._send({"type": "ok", "data": {"color": color}})

        elif cmd == "led_seq":
            if not self._ble.connected:
                self._send({"type": "error", "message": "设备未连接"})
                return
            seq = msg.get("sequence", [])
            repeat = msg.get("repeat", False)
            self._start_led_seq(seq, repeat, device_id)
            self._send({"type": "ok", "message": f"灯效序列已启动 ({len(seq)} 步, 循环={repeat})"})

        elif cmd == "led_stop":
            self._stop_led_seq()
            self._send({"type": "ok", "message": "灯效已停止"})

        elif cmd == "led_flash":
            c1 = msg.get("color1", 2)
            c2 = msg.get("color2", 4)
            speed = msg.get("speed", 1)
            self._stop_led_seq()
            await self._ble.send_command(cmd_70_flash(c1, c2, speed), device_id)
            self._send({"type": "ok", "data": {"color1": c1, "color2": c2, "speed": speed}})

        # ---- D0 直传 ----
        elif cmd == "d0_start":
            color = msg.get("color", 1)
            await self._ble.send_command(cmd_50_d0_mode(color), device_id)
            self._send({"type": "ok", "message": "D0 直传已开启"})

        elif cmd == "d0_stop":
            color = msg.get("color", 1)
            await self._ble.send_command(cmd_50_no_trigger(color), device_id)
            self._send({"type": "ok", "message": "D0 直传已停止"})

        # ---- 缓存设置 ----
        elif cmd == "cache_duration":
            sec = msg.get("seconds", 120)
            self._buffer.set_duration(sec)
            self._send({"type": "ok", "data": {"cache_duration": self._buffer.duration}})

        # ---- 通用指令透传 ----
        elif cmd == "cmd":
            sub_cmd = msg.get("sub_cmd", "")
            if sub_cmd == "cmd_5f":
                await self._ble.send_command(cmd_5f(), device_id)
                self._send({"type": "ok", "message": "5F 已发送"})
            elif sub_cmd == "cmd_60":
                await self._ble.send_command(cmd_60(), device_id)
                self._send({"type": "ok", "message": "60 已发送"})
            else:
                self._send({"type": "error", "message": f"未知子指令: {sub_cmd}"})

        else:
            self._send({"type": "error", "message": f"未知指令: {cmd}"})

    # ---- 灯效序列引擎 ----

    def _start_led_seq(self, sequence: list, repeat: bool, device_id=None):
        """启动异步灯效序列任务"""
        self._stop_led_seq()
        if not sequence:
            return
        self._led_task = asyncio.create_task(self._run_led_seq(sequence, repeat, device_id))

    def _stop_led_seq(self):
        """停止灯效序列"""
        if self._led_task and not self._led_task.done():
            self._led_task.cancel()
        self._led_task = None

    async def _run_led_seq(self, sequence: list, repeat: bool, device_id=None):
        """执行灯效序列（异步循环）"""
        try:
            while True:
                for step in sequence:
                    color = step.get("color", 0)
                    ms = max(10, min(10000, step.get("ms", 500)))
                    if self._ble.connected:
                        await self._ble.send_command(cmd_70_solid(color), device_id)
                    await asyncio.sleep(ms / 1000.0)
                if not repeat:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"灯效序列异常: {e}")
