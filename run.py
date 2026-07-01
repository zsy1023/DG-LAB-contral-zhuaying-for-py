"""爪印 Web 蓝牙控制面板 - 一键启动"""
import subprocess
import sys
import os
import time
import urllib.request
import webbrowser

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
URL = "http://127.0.0.1:9879"


def check_deps():
    req_path = os.path.join(BACKEND_DIR, "requirements.txt")
    print("📦 检查依赖...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", req_path, "-q"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_server(timeout_sec: float = 10) -> bool:
    """轮询等待服务端就绪"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = urllib.request.urlopen(URL, timeout=1)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main():
    check_deps()

    print("🚀 启动服务端...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", "9879"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 等待服务端就绪
    print("⏳ 等待服务端就绪...", end="", flush=True)
    if wait_for_server():
        print(" OK")
    else:
        print("\n❌ 服务端启动超时，请检查是否有端口冲突")
        proc.terminate()
        # 打印子进程输出
        out, _ = proc.communicate(timeout=1)
        print(out)
        sys.exit(1)

    webbrowser.open(URL)

    print("=" * 50)
    print(f"🟢 爪印控制面板已启动: {URL}")
    print("   按 Ctrl+C 退出")
    print("=" * 50)

    try:
        # 持续打印服务端日志
        for line in proc.stdout:
            print(line, end="")
    except KeyboardInterrupt:
        print("\n👋 已退出")
        proc.terminate()


if __name__ == "__main__":
    main()
