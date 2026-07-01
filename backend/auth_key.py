"""
Agent TCP 连接密钥管理
======================
密钥存储在 backend/auth_key.txt，不存在则自动生成 32 位随机 hex。
写入使用原子 rename 防止崩溃损坏。
"""

import os
import secrets
import tempfile

KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_key.txt")


def _atomic_write(content: str):
    """原子写入：先写临时文件，再 rename"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(KEY_FILE))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, KEY_FILE)
    except Exception:
        os.unlink(tmp)
        raise


def get_key() -> str:
    """读取密钥，不存在则生成"""
    if not os.path.exists(KEY_FILE):
        _atomic_write(secrets.token_hex(16))
    with open(KEY_FILE) as f:
        return f.read().strip()


def regenerate_key() -> str:
    """重新生成密钥"""
    key = secrets.token_hex(16)
    _atomic_write(key)
    return key
