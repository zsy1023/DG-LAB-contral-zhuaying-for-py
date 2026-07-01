"""
数据缓冲区 — 环形缓冲区存储 D0 传感器数据
=========================================
支持动态配置缓存时长，按秒/时间戳查询。
"""

import time
import bisect
from collections import deque
from typing import Optional


class DataBuffer:
    """环形缓冲区，自动淘汰过期数据"""

    def __init__(self, max_seconds: float = 120.0):
        self._max_seconds = max_seconds
        self._buffer: deque[dict] = deque()
        self._timestamps: deque[float] = deque()  # 平行时间戳用于二分

    @property
    def duration(self) -> float:
        """当前缓存时长（秒）"""
        return self._max_seconds

    def set_duration(self, seconds: float):
        """动态调整缓存时长（1 ~ 3600 秒）"""
        self._max_seconds = max(1.0, min(3600.0, seconds))
        self._evict()

    def push(self, entry: dict):
        """写入一条数据，自动附加时间戳"""
        ts = time.time()
        entry["_ts"] = ts
        self._buffer.append(entry)
        self._timestamps.append(ts)
        self._evict()

    def _evict(self):
        """淘汰过期数据"""
        cutoff = time.time() - self._max_seconds
        while self._buffer and self._buffer[0]["_ts"] < cutoff:
            self._buffer.popleft()
            self._timestamps.popleft()

    def _start_index(self, cutoff: float) -> int:
        """二分查找 >= cutoff 的第一个索引"""
        # deque 不支持随机访问，转为 list 做 bisect（仅在查询时）
        ts_list = list(self._timestamps)
        idx = bisect.bisect_left(ts_list, cutoff)
        return idx

    def get_recent(self, seconds: Optional[float] = None) -> list[dict]:
        """获取最近 N 秒的数据（默认全部缓存）"""
        self._evict()
        if seconds is None:
            return list(self._buffer)
        cutoff = time.time() - seconds
        idx = self._start_index(cutoff)
        return list(self._buffer)[idx:]

    def get_since(self, timestamp: float) -> list[dict]:
        """获取指定时间戳之后的数据"""
        self._evict()
        idx = self._start_index(timestamp)
        return list(self._buffer)[idx:]

    @property
    def count(self) -> int:
        """当前缓存条数"""
        self._evict()
        return len(self._buffer)

    @property
    def latest(self) -> Optional[dict]:
        """最新一条数据"""
        self._evict()
        return self._buffer[-1] if self._buffer else None

    def clear(self):
        """清空缓冲区"""
        self._buffer.clear()
        self._timestamps.clear()
