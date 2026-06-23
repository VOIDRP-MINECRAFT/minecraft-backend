from __future__ import annotations

import logging
import socket
import struct

from apps.api.app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
_TYPE_AUTH = 3
_TYPE_CMD = 2
_TYPE_RESPONSE = 0


def _pack(req_id: int, ptype: int, payload: str) -> bytes:
    body = payload.encode("utf-8") + b"\x00\x00"
    header = struct.pack("<ii", req_id, ptype)
    data = header + body
    return struct.pack("<i", len(data)) + data


def _recv_packet(sock: socket.socket) -> tuple[int, int, str]:
    def recv_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise OSError("RCON connection closed")
            buf += chunk
        return buf

    length = struct.unpack("<i", recv_exact(4))[0]
    data = recv_exact(length)
    req_id, ptype = struct.unpack("<ii", data[:8])
    payload = data[8:-2].decode("utf-8", errors="replace")
    return req_id, ptype, payload


def send_rcon_command(command: str) -> str | None:
    """Send a command via RCON using raw sockets (thread-safe, no signal dependency)."""
    s = get_settings()
    if not s.rcon_password:
        logger.debug("RCON not configured, skipping: %s", command)
        return None
    try:
        with socket.create_connection((s.rcon_host, s.rcon_port), timeout=_TIMEOUT) as sock:
            sock.sendall(_pack(1, _TYPE_AUTH, s.rcon_password))
            req_id, _, _ = _recv_packet(sock)
            if req_id == -1:
                logger.warning("RCON auth failed (bad password)")
                return None

            sock.sendall(_pack(2, _TYPE_CMD, command))
            _, _, response = _recv_packet(sock)
            logger.info("RCON [%s] → %s", command, response)
            return response
    except Exception as e:
        logger.warning("RCON error [%s]: %s", command, e)
        return None
