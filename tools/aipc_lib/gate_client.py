"""Thin client for aipc-agent-gate's UNIX-socket RPC (phase-4-agent#5.2).

Wire protocol: newline-delimited JSON, one request line in, one response
line out, over /run/aipc-agent-gate.sock. See
modules/agent-gate/files/usr/lib/aipc-agent/aipc_agent_gate/server.py for
the full contract (grant/revoke/check/status).
"""

import json
import socket

DEFAULT_SOCKET_PATH = "/run/aipc-agent-gate.sock"


def send(request: dict, sock_path: str = DEFAULT_SOCKET_PATH, timeout: float = 5.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall((json.dumps(request) + "\n").encode())
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
        return json.loads(b"".join(chunks))
