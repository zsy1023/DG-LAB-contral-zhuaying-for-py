"""
D0 数据录制器 — 实时写入 CSV 文件
==================================
"""

import csv
import os
import time
from datetime import datetime
from typing import Optional

RECORD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")

# 确保录制目录存在
os.makedirs(RECORD_DIR, exist_ok=True)

CSV_HEADER = [
    "timestamp", "angle_x", "angle_y", "angle_z",
    "acceleration", "voltage", "pressed"
]


class Recorder:
    """CSV 录制器"""

    def __init__(self):
        self._file = None
        self._writer = None
        self._filename: str = ""
        self._start_time: float = 0
        self._count: int = 0

    @property
    def recording(self) -> bool:
        return self._file is not None

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def count(self) -> int:
        return self._count

    @property
    def elapsed(self) -> float:
        if not self.recording:
            return 0
        return time.time() - self._start_time

    def start(self) -> str:
        """开始录制"""
        if self.recording:
            self.stop()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"recording_{ts}.csv"
        path = os.path.join(RECORD_DIR, self._filename)
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_HEADER)
        self._start_time = time.time()
        self._count = 0
        return self._filename

    def push(self, data: dict):
        """写入一条 D0 数据"""
        if not self.recording or not self._writer:
            return
        self._writer.writerow([
            f"{data.get('_ts', time.time()):.3f}",
            data.get("angle_x", 0),
            data.get("angle_y", 0),
            data.get("angle_z", 0),
            data.get("acceleration", 0),
            data.get("voltage", 0),
            "1" if data.get("pressed") else "0",
        ])
        self._file.flush()
        self._count += 1

    def stop(self) -> dict:
        """停止录制"""
        info = {
            "filename": self._filename,
            "count": self._count,
            "elapsed": round(self.elapsed, 1),
        }
        if self._file:
            self._file.close()
        self._file = None
        self._writer = None
        self._filename = ""
        self._count = 0
        self._start_time = 0
        return info


# ============================================================
# 文件管理
# ============================================================
def list_recordings() -> list[dict]:
    """列出所有录制文件"""
    files = []
    if not os.path.exists(RECORD_DIR):
        return files
    for fname in sorted(os.listdir(RECORD_DIR), reverse=True):
        if fname.endswith(".csv"):
            path = os.path.join(RECORD_DIR, fname)
            stat = os.stat(path)
            # 统计行数
            with open(path, encoding="utf-8") as f:
                lines = sum(1 for _ in f) - 1  # 减表头
            files.append({
                "filename": fname,
                "size_kb": round(stat.st_size / 1024, 1),
                "rows": lines,
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
    return files


def load_recording(filename: str) -> list[dict]:
    """加载录制文件，返回数据列表"""
    path = os.path.join(RECORD_DIR, filename)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "_ts": float(row["timestamp"]),
                "angle_x": int(row["angle_x"]),
                "angle_y": int(row["angle_y"]),
                "angle_z": int(row["angle_z"]),
                "acceleration": int(row["acceleration"]),
                "voltage": float(row["voltage"]),
                "pressed": row["pressed"] == "1",
            })
    return rows
