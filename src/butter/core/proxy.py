"""Proxy plane.

Two modes are supported:

``direct``  — an explicit proxy URL taken from settings (or none).
``mihomo``  — a generated Clash/mihomo profile: HK nodes are pooled into a
              round-robin load balancer, and the dialer hop (``dialer-proxy``)
              chains into that pool, with ``MATCH,FINAL`` routing.

The generator here is pure: it renders YAML text from settings so it can be
unit-tested without spawning a process. ``ProxyController`` adds the runtime
side (spawn / health probe / teardown) used by the API layer.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .store import Settings, data_dir

LOGGER = logging.getLogger("butter.proxy")

PROBE_URL = "http://www.gstatic.com/generate_204"
MIXED_PORT = 7890


def _scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    return str(value)


def build_profile(settings: Settings, socks_port: int = MIXED_PORT) -> dict[str, Any]:
    """Render a Clash/mihomo profile.

    Two shapes are produced:

    * **plain**  — no ``hk_nodes``: the upstream proxy becomes the only egress.
                   This is the "fixed IP / one hop" case.
    * **chain**  — with ``hk_nodes``: the upstream (ISP) is dialed *through* a
                   round-robin pool of HK nodes, so Apple sees the pool's exit IP.
    """
    nodes: list[dict[str, Any]] = []
    names: list[str] = []
    for index, node in enumerate(settings.hk_nodes, start=1):
        name = f"HK-{index}"
        names.append(name)
        nodes.append(
            {
                "name": name,
                "type": node.get("type", "ss"),
                "server": _scalar(node.get("server")),
                "port": int(node.get("port", 0)),
                "cipher": node.get("cipher", "aes-128-gcm"),
                "password": _scalar(node.get("password")),
                **({"plugin": node["plugin"]} if node.get("plugin") else {}),
                **({"plugin-opts": node["plugin-opts"]} if node.get("plugin-opts") else {}),
                "udp": bool(node.get("udp", True)),
            }
        )

    if not settings.proxy_host or not settings.proxy_port:
        raise ValueError("mihomo 模式需要填写上游代理服务器与端口")

    dialer = "HK-LB"
    upstream: dict[str, Any] = {
        "name": "ISP",
        "type": settings.proxy_type or "socks5",
        "server": _scalar(settings.proxy_host),
        "port": int(settings.proxy_port),
        **({"username": settings.proxy_user} if settings.proxy_user else {}),
        **({"password": settings.proxy_pass} if settings.proxy_pass else {}),
    }
    if names:
        upstream["dialer-proxy"] = dialer
    nodes.append(upstream)

    groups: list[dict[str, Any]] = []
    if names:
        groups.append(
            {
                "name": dialer,
                "type": "load-balance",
                "strategy": "round-robin",
                "proxies": names,
                "url": PROBE_URL,
                "interval": 60,
                "lazy": False,
            }
        )
    groups.append({"name": "FINAL", "type": "select", "proxies": ["ISP"]})

    return {
        "mixed-port": socks_port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "proxies": nodes,
        "proxy-groups": groups,
        "rules": ["MATCH,FINAL"],
    }


def render_profile(settings: Settings, socks_port: int = MIXED_PORT) -> str:
    return yaml.safe_dump(build_profile(settings, socks_port), sort_keys=False, allow_unicode=True)


def find_free_port(start: int = 17890, end: int = 17990) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in {start}-{end}")


def port_alive(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class ProxyStatus:
    mode: str
    running: bool
    port: int = 0
    pid: int | None = None
    config: str = ""
    log: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "running": self.running,
            "port": self.port,
            "pid": self.pid,
            "config": self.config,
            "log": self.log,
            "error": self.error,
        }


class ProxyController:
    """Owns the mihomo child process, if any."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.workdir = data_dir() / "mihomo"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.workdir / "config.yaml"
        self.log_path = self.workdir / "mihomo.log"
        self.port = 0
        self._proc: subprocess.Popen | None = None

    # --- lifecycle --------------------------------------------------------
    def write_config(self, port: int) -> Path:
        self.config_path.write_text(render_profile(self.settings, port), encoding="utf-8")
        return self.config_path

    def _binary(self) -> Path | None:
        exe = "mihomo.exe" if os.name == "nt" else "mihomo"
        for candidate in (shutil.which("mihomo"), shutil.which("clash-meta"), shutil.which("clash-verge-mihomo")):
            if candidate:
                return Path(candidate)
        # Desktop proxies bundle the core next to their app payloads.
        for hint in (
            "/Applications/Clash Verge.app/Contents/Resources/mihomo",
            "/Applications/ClashX Meta.app/Contents/Resources/mihomo",
            "/Applications/ClashX Pro.app/Contents/Resources/mihomo",
        ):
            if Path(hint).exists():
                return Path(hint)
        local = self.workdir / exe
        return local if local.exists() else None

    def start(self) -> ProxyStatus:
        if self.settings.proxy_mode != "mihomo":
            return ProxyStatus(mode=self.settings.proxy_mode, running=True, error="")
        binary = self._binary()
        if binary is None:
            return ProxyStatus(
                mode="mihomo",
                running=False,
                config=str(self.config_path),
                error="未找到 mihomo 可执行文件（放到数据目录 mihomo/ 下或加入 PATH）",
            )
        self.port = find_free_port()
        self.write_config(self.port)
        log_handle = open(self.log_path, "w", encoding="utf-8")  # noqa: SIM115 - kept for child lifetime
        self._proc = subprocess.Popen(  # noqa: S603 - explicit local binary
            [str(binary), "-d", str(self.workdir), "-f", str(self.config_path)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(self.workdir),
        )
        deadline = time.time() + 12
        while time.time() < deadline:
            if port_alive(self.port):
                LOGGER.info("[mihomo] ready on %s (pid=%s)", self.port, self._proc.pid)
                return ProxyStatus(
                    mode="mihomo",
                    running=True,
                    port=self.port,
                    pid=self._proc.pid,
                    config=str(self.config_path),
                    log=str(self.log_path),
                )
            if self._proc.poll() is not None:
                return ProxyStatus(
                    mode="mihomo",
                    running=False,
                    port=self.port,
                    config=str(self.config_path),
                    log=str(self.log_path),
                    error="mihomo 启动失败，请查看 mihomo.log",
                )
            time.sleep(0.2)
        return ProxyStatus(
            mode="mihomo",
            running=port_alive(self.port),
            port=self.port,
            pid=self._proc.pid if self._proc else None,
            config=str(self.config_path),
            log=str(self.log_path),
            error="mihomo 启动超时",
        )

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def status(self) -> ProxyStatus:
        running = bool(self._proc and self._proc.poll() is None) or (self.port and port_alive(self.port))
        return ProxyStatus(
            mode=self.settings.proxy_mode,
            running=running,
            port=self.port,
            pid=self._proc.pid if self._proc else None,
            config=str(self.config_path) if self.config_path.exists() else "",
            log=str(self.log_path),
        )

    def socks_url(self) -> str | None:
        if self.settings.proxy_mode == "mihomo":
            return f"socks5h://127.0.0.1:{self.port or MIXED_PORT}" if self.status().running else None
        return self.settings.proxy_url_for()
