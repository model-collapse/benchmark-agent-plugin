"""Dockerized single-node OpenSearch cluster for local benchmarking.

Starts a disposable container with security disabled, waits for the cluster to
report yellow/green, and tears it down on exit. Picks a free host port so
multiple runs don't collide.
"""

from __future__ import annotations

import socket
import subprocess
import time
import uuid

IMAGE = "opensearchproject/opensearch:2.17.0"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class OpenSearchCluster:
    def __init__(self, heap="4g", port: int | None = None, name: str | None = None,
                 image: str = IMAGE):
        self.port = port or _free_port()
        self.name = name or f"clusterbench-os-{uuid.uuid4().hex[:8]}"
        self.heap = heap
        self.image = image
        self.container_id: str | None = None

    @property
    def host_url(self) -> str:
        return f"http://localhost:{self.port}"

    def start(self, timeout_s: int = 180) -> "OpenSearchCluster":
        cmd = [
            "docker", "run", "-d", "--rm", "--name", self.name,
            "-p", f"{self.port}:9200",
            "-e", "discovery.type=single-node",
            "-e", "DISABLE_SECURITY_PLUGIN=true",
            "-e", "DISABLE_INSTALL_DEMO_CONFIG=true",
            "-e", "bootstrap.memory_lock=false",
            "-e", f"OPENSEARCH_JAVA_OPTS=-Xms{self.heap} -Xmx{self.heap}",
            "--ulimit", "nofile=65536:65536",
            self.image,
        ]
        self.container_id = subprocess.check_output(cmd, text=True).strip()
        self._wait_healthy(timeout_s)
        return self

    def _wait_healthy(self, timeout_s: int) -> None:
        import urllib.request

        deadline = time.time() + timeout_s
        last = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.host_url}/_cluster/health", timeout=3) as r:
                    body = r.read().decode()
                    if '"status"' in body and ('"yellow"' in body or '"green"' in body):
                        return
                    last = body
            except Exception as e:  # noqa: BLE001
                last = str(e)
            time.sleep(2)
        self.stop()
        raise TimeoutError(f"OpenSearch not healthy in {timeout_s}s. Last: {last[:200]}")

    def mem_usage_kb(self) -> int:
        """Container memory usage in KB (for the OOM guard / peak RSS)."""
        try:
            out = subprocess.check_output(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.name],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            used = out.split("/")[0].strip()  # e.g. "2.1GiB"
            return _parse_bytes(used) // 1024
        except Exception:  # noqa: BLE001
            return 0

    def client(self):
        from opensearchpy import OpenSearch

        return OpenSearch(hosts=[{"host": "localhost", "port": self.port}],
                          http_compress=True, use_ssl=False, timeout=60)

    def stop(self) -> None:
        if self.container_id:
            subprocess.run(["docker", "rm", "-f", self.name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.container_id = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def _parse_bytes(s: str) -> int:
    s = s.strip()
    units = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3,
             "KB": 1000, "MB": 1000**2, "GB": 1000**3}
    for u, mult in sorted(units.items(), key=lambda x: -len(x[0])):
        if s.upper().endswith(u):
            return int(float(s[: -len(u)].strip()) * mult)
    try:
        return int(float(s))
    except ValueError:
        return 0
