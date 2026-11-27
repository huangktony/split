"""Scripted-client harness: a real RaceServer on a free port plus named clients.

Usage (inside an async test):

    async with race_server(players=2, time_limit=5) as url:
        alice = await Client.join(url, "alice")
        ...
"""

import asyncio
import json
from contextlib import asynccontextmanager

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from game.server import RaceServer

TIMEOUT = 2.0  # seconds; any wait longer than this fails the test instead of hanging


@asynccontextmanager
async def race_server(secret="crane", players=2, **kwargs):
    """Yield the ws:// URL of a fresh server. The RaceServer is at url.server."""
    srv = RaceServer(secret, players, **kwargs)
    async with serve(srv.handler, "localhost", 0) as server:
        url = Url(f"ws://localhost:{server.sockets[0].getsockname()[1]}")
        url.server = srv
        yield url
        if srv.timer is not None:
            srv.timer.cancel()


class Url(str):
    server: RaceServer


class Client:
    """One scripted player. Every message received is kept in .log, in order."""

    def __init__(self, name, ws):
        self.name = name
        self.ws = ws
        self.log: list[dict] = []
        self.closed = asyncio.Event()
        self._unread: list[dict] = []
        self._arrived = asyncio.Event()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def join(cls, url, name, bot=False):
        """Connect and join; returns once the 'joined' reply arrives."""
        client = cls(name, await connect(url))
        await client.send({"type": "join", "name": name, "bot": bot})
        await client.wait_for("joined", "error")
        return client

    async def _read(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                self.log.append(msg)
                self._unread.append(msg)
                self._arrived.set()
        except ConnectionClosed:
            pass
        finally:
            self.closed.set()
            self._arrived.set()

    async def send(self, msg):
        await self.ws.send(json.dumps(msg))

    async def guess(self, word):
        """Send a guess and return its reply (feedback or invalid)."""
        await self.send({"type": "guess", "word": word})
        return await self.wait_for("feedback", "invalid")

    async def wait_for(self, *types, timeout=TIMEOUT):
        """Return the oldest unread message of one of these types.

        Unread messages of other types stay unread for later calls.
        Raises TimeoutError if none arrives in time.
        """
        async def find():
            while True:
                for i, msg in enumerate(self._unread):
                    if msg["type"] in types:
                        return self._unread.pop(i)
                if self.closed.is_set():
                    raise ConnectionError(f"{self.name}: closed before {types}")
                self._arrived.clear()
                await self._arrived.wait()
        return await asyncio.wait_for(find(), timeout)

    async def expect_none(self, *types, wait=0.3):
        """Fail if a message of one of these types arrives within `wait` seconds."""
        try:
            msg = await self.wait_for(*types, timeout=wait)
        except (TimeoutError, ConnectionError):
            return
        raise AssertionError(f"{self.name} got unexpected {msg}")

    def count(self, type_):
        return sum(1 for m in self.log if m["type"] == type_)

    async def close(self):
        """Polite disconnect (close frame)."""
        await self.ws.close()

    def cut_network(self):
        """Abrupt disconnect with no close frame, like Wi-Fi dropping."""
        self.ws.transport.abort()
