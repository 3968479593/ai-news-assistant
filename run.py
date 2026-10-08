"""AI 新闻助手 —— 一键启动（幂等、自检、健康就绪判定、日志落盘）。

用法：
    python run.py            启动服务（已运行时只开页面）；等 /api/health 就绪后自动开浏览器
    python run.py --stop     停止服务（等价 stop.bat）
    python run.py --check    只做环境自检（依赖/模型/端口），不启动

特性：
    - 幂等：先探测 /api/health，确认是本项目服务才复用；端口被其他程序占用时明确报错
    - 就绪判定用健康检查而非端口监听（模型加载约 30-40s，端口通 ≠ 可用）
    - 日志落盘 backend/data/server8000.out.log / .err.log（与 start.bat 一致）
    - Ctrl+C 优雅停止（terminate → 超时 kill），不留残留进程
"""

import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
PORT = 8000
URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{URL}/api/health"
LOG_OUT = os.path.join(BACKEND, "data", "server8000.out.log")
LOG_ERR = os.path.join(BACKEND, "data", "server8000.err.log")
MODEL_DIR = os.path.join(BACKEND, "models", "BAAI")

# 控制台若为 GBK 编码，中文 print 报错时用替换符而不是崩溃
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------- 端口 / 进程 ----------

def port_busy(port: int) -> bool:
    """检测 127.0.0.1:port 是否已有监听。"""
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_pid(port: int) -> str | None:
    """定位监听 127.0.0.1:port 的进程 PID（仅精确匹配本机监听，避免远程连接误配）。"""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                parts = line.split()
                return parts[-1] if parts else None
    except Exception:
        pass
    return None


def describe_pid(pid: str) -> str:
    """返回 PID 对应的进程名/命令行（用于端口被占时的诊断信息）。"""
    if platform.system() != "Windows":
        return ""
    try:
        info = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10,
        ).stdout
        for line in info.splitlines():
            if pid in line:
                return line.strip()
    except Exception:
        pass
    return ""


# ---------- 健康检查 ----------

def health_ok() -> bool:
    """本项目服务健康检查：status==ok 且响应带本项目独有字段（chroma_chunks）。"""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("status") == "ok" and "chroma_chunks" in data
    except Exception:
        return False


# ---------- 环境自检 ----------

def resolve_python() -> tuple[list[str], str]:
    """选择解释器：优先 py -3.11（项目锁定），否则当前解释器；校验关键依赖。"""
    candidates: list[list[str]] = []
    if sys.version_info >= (3, 10):
        candidates.append([sys.executable])  # 当前解释器（python run.py 场景）
    candidates.append(["py", "-3.11"])       # py launcher（3.11 优先，不在此列说明 3.11 缺失则跳过）

    for cmd in candidates:
        try:
            r = subprocess.run(
                cmd + ["-c", "import sys; print(sys.version.split()[0])"],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode != 0:
                continue
            ver = r.stdout.strip()
            major, minor = (int(x) for x in ver.split(".")[:2])
            if not (3, 10) <= (major, minor) <= (3, 12):
                log(f"  ⚠️ 解释器 {ver} 不在 3.10-3.12 范围（3.13+ 缺依赖），跳过")
                continue
            subprocess.run(
                cmd + ["-c", "import fastapi, uvicorn, langgraph, chromadb"],
                check=True, capture_output=True, timeout=30,
            )
            return cmd, ver
        except Exception:
            continue
    return [sys.executable], f"{sys.version_info.major}.{sys.version_info.minor}"


def check_env() -> tuple[bool, list[str], str]:
    """自检：返回 (是否通过, 问题列表, 解释器版本)。"""
    issues: list[str] = []
    py_cmd, ver = resolve_python()

    for name in ("fastapi", "uvicorn", "langgraph", "chromadb", "sqlalchemy", "httpx", "sentence_transformers"):
        try:
            subprocess.run(
                py_cmd + ["-c", f"import {name}"],
                check=True, capture_output=True, timeout=30,
            )
        except Exception:
            issues.append(f"缺少依赖 {name}（pip install -r backend/requirements.txt）")

    if not os.path.isdir(os.path.join(MODEL_DIR, "bge-m3")) or not os.path.isdir(os.path.join(MODEL_DIR, "bge-reranker-v2-m3")):
        issues.append("本地模型缺失（backend/models/BAAI/），服务仍可启动但嵌入/精排不可用，请运行 backend/scripts/download_models.py")

    return (not issues), issues, ver


# ---------- 停止 ----------

def stop_service() -> None:
    if not port_busy(PORT):
        log("没有检测到运行中的服务。")
        return
    pid = find_pid(PORT)
    if pid:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
        log(f"已停止 PID {pid}（端口 {PORT}）。")
    else:
        log("端口有监听但未能定位进程，请手动停止（任务管理器 → 详细信息）。")


# ---------- 主流程 ----------

def main() -> None:
    args = sys.argv[1:]

    if "--stop" in args:
        stop_service()
        return

    if "--check" in args:
        log("检查运行环境（Python 版本 + 依赖 + 模型）...")
        ok, issues, ver = check_env()
        if ok:
            log(f"✅ 环境正常（Python {ver}，依赖与模型齐全）")
        else:
            log(f"⚠️ 发现 {len(issues)} 个问题（Python {ver}）：")
            for i in issues:
                log(f"  - {i}")
        return

    # 1) 幂等：健康检查确认是本项目服务 → 直接开页面
    if health_ok():
        log(f"✅ 服务已在运行（健康检查通过）：{URL}")
        webbrowser.open(URL)
        return

    # 2) 端口被其他程序占用 → 明确报错，不误开浏览器
    if port_busy(PORT):
        pid = find_pid(PORT)
        desc = describe_pid(pid) if pid else ""
        log(f"❌ 端口 {PORT} 已被其他程序占用" + (f"（{desc}）" if desc else ""))
        log("   该端口不是本项目服务。请先停止占用程序，或改 .env / 端口再启动。")
        return

    # 3) 环境自检
    log("检查运行环境（Python 版本 + 依赖 + 模型）...")
    ok, issues, ver = check_env()
    if not ok:
        for i in issues:
            log(f"  ⚠️ {i}")
        if input("存在上述问题，仍要尝试启动吗？[y/N] ").strip().lower() != "y":
            log("已取消。")
            return

    log(f"启动 AI 新闻助手后端（Python {ver}）...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # 日志落盘（追加），与 start.bat 一致；不用 --reload（多进程树难清理）
    with open(LOG_OUT, "ab") as fo, open(LOG_ERR, "ab") as fe:
        proc = subprocess.Popen(
            py_cmd + ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=BACKEND,
            env=env,
            stdout=fo,
            stderr=fe,
        )

    # 4) 健康就绪轮询（最长 90s；模型加载约 30-40s）
    log("等待服务就绪（模型加载约 30-40 秒，最长 90 秒）...")
    deadline = time.time() + 90
    while time.time() < deadline:
        if health_ok():
            log(f"✅ 服务已就绪：{URL}")
            webbrowser.open(URL)
            log(f"接口文档: {URL}/docs")
            log("按 Ctrl+C 关闭服务")
            break
        time.sleep(1.5)
    else:
        log("⚠️ 90 秒内服务未就绪。错误日志尾部：")
        try:
            with open(LOG_ERR, "r", encoding="utf-8", errors="replace") as f:
                tail = "".join(f.readlines()[-10:])
            log(tail if tail.strip() else "(错误日志为空，请确认依赖与模型已就绪)")
        except Exception:
            log("(无法读取错误日志)")

    # 5) 前台等待；Ctrl+C 优雅停止
    try:
        proc.wait()
    except KeyboardInterrupt:
        log("\n正在停止服务...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log("进程未在 5 秒内退出，强制结束")
            proc.kill()
        log("已关闭。重新启动请再次运行 python run.py")


if __name__ == "__main__":
    main()
