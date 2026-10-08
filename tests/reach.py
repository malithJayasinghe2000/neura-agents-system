"""Helpers for tests about where NEURA's server connects (G47, G78).

A name lookup that answers from a table, and a computer on our own private
network that counts every connection made to it. Together they reproduce DNS
rebinding without the internet: a name that answers a public address when it is
checked, and ours when it is connected to.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest

#: A public address, never connected to: the guard refuses the private answer first.
PUBLIC = "93.184.216.34"


def answer_names(
    monkeypatch: pytest.MonkeyPatch, table: dict[str, list[list[str]]]
) -> dict[str, int]:
    """The running loop's name lookups, answered from ``table``.

    Each name gets its answers in turn, the last one repeated: ``[[PUBLIC],
    ["127.0.0.1"]]`` is public the first time and private ever after. A numeric
    host answers itself, as a real lookup does. Returns how often each name was
    looked up. Call it inside the test, so it patches the test's own loop.
    """
    loop = asyncio.get_running_loop()
    real = loop.getaddrinfo
    asked: dict[str, int] = defaultdict(int)

    async def lookup(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        name = host.decode() if isinstance(host, bytes) else str(host)
        try:
            ipaddress.ip_address(name)
        except ValueError:
            pass
        else:
            return await real(host, port, *args, **kwargs)
        answers = table[name]
        found = answers[min(asked[name], len(answers) - 1)]
        asked[name] += 1
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, int(port), 0, 0) if ":" in ip else (ip, int(port)),
            )
            for ip in found
        ]

    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    return asked


@dataclass
class Listener:
    """A computer on 127.0.0.1. ``hits`` grows by one for every connection made."""

    port: int
    hits: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)


@asynccontextmanager
async def private_listener(*, answer_http: bool = False) -> AsyncIterator[Listener]:
    """Counts connections; with ``answer_http`` it also answers one plain HTTP
    request with ``{}`` and records the ``Host`` header it was sent."""
    listener = Listener(port=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        listener.hits.append(str(writer.get_extra_info("peername")))
        if answer_http:
            head = await reader.readuntil(b"\r\n\r\n")
            for line in head.decode("latin-1").split("\r\n"):
                if line.lower().startswith("host:"):
                    listener.hosts.append(line.split(":", 1)[1].strip())
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Length: 2\r\nConnection: close\r\n\r\n{}"
            )
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    listener.port = server.sockets[0].getsockname()[1]
    try:
        yield listener
    finally:
        server.close()
        await server.wait_closed()
