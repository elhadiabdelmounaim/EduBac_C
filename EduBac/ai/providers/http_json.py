"""HTTP POST with one wall-clock budget for DNS, connect, and the body read."""
from __future__ import annotations

import http.client
import socket
import ssl
import time
from urllib.parse import urlsplit


def address_order(infos):
    """Try IPv4 before IPv6. A blackholed IPv6 route must not spend its own full timeout."""
    return sorted(infos, key=lambda item: 0 if item[0] == socket.AF_INET else 1)


def post_json(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, str]:
    """POST `body` and return `(status, text)`. Raises TimeoutError when `timeout` elapses."""
    deadline = time.monotonic() + max(0.1, float(timeout))
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OSError(f"URL non supportée : {url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("timed out")
        return left

    infos = address_order(socket.getaddrinfo(
        parts.hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM,
    ))
    sock = None
    last_error: OSError | None = None
    for family, socktype, proto, _canon, address in infos:
        try:
            left = remaining()
        except TimeoutError:
            break
        candidate = socket.socket(family, socktype, proto)
        candidate.settimeout(left)
        try:
            candidate.connect(address)
        except TimeoutError as exc:
            last_error = exc
            candidate.close()
            continue
        except OSError as exc:
            last_error = exc
            candidate.close()
            continue
        sock = candidate
        break
    if sock is None:
        if isinstance(last_error, TimeoutError) or last_error is None:
            raise TimeoutError("timed out")
        raise last_error

    conn = None
    try:
        left = remaining()
        sock.settimeout(left)
        if parts.scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=parts.hostname)
            conn = http.client.HTTPSConnection(parts.hostname, port, timeout=left, context=context)
        else:
            conn = http.client.HTTPConnection(parts.hostname, port, timeout=left)
        conn.sock = sock
        request_headers = dict(headers)
        request_headers.setdefault("Connection", "close")
        conn.request("POST", path, body=body, headers=request_headers)
        sock.settimeout(remaining())
        response = conn.getresponse()
        chunks = []
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("timed out")
            sock.settimeout(min(5.0, left))
            try:
                chunk = response.read(8192)
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out") from None
                continue
            if not chunk or response.isclosed():
                if chunk:
                    chunks.append(chunk)
                break
            chunks.append(chunk)
        return response.status, b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        if conn is not None:
            conn.close()
        else:
            sock.close()
