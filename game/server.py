"""Websocket server for a multiplayer Wordle race (stage S1: bare race)."""

import argparse
import asyncio
import json
import time

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from game import rules
from game.race import Race, RaceError


class RaceServer:
    def __init__(self, secret: str, n_players: int, hard: bool = False,
                 time_limit: float = 300, clock=time.monotonic):
        self.secret = secret
        self.n_players = n_players
        self.hard = hard
        self.time_limit = time_limit
        self.clock = clock
        self.done = asyncio.Event()
        self.race = None
        self.start = None
        self.names = {}    # player_id -> name, in join order
        self.bots = []
        self.conns = {}    # player_id -> websocket

    async def _send(self, ws, msg):
        await ws.send(json.dumps(msg))

    async def _fail(self, ws, reason):
        await self._send(ws, {"type": "error", "reason": reason})
        await ws.close()

    async def _broadcast(self, msg):
        for ws in self.conns.values():
            try:
                await self._send(ws, msg)
            except ConnectionClosed:
                pass

    async def handler(self, ws):
        try:
            await self._run(ws)
        except ConnectionClosed:
            pass

    async def _run(self, ws):
        try:
            msg = json.loads(await ws.recv())
        except ValueError:
            msg = None
        if not (isinstance(msg, dict) and msg.get("type") == "join"
                and isinstance(msg.get("name"), str)):
            return await self._fail(ws, "expected join")
        if self.race is not None or len(self.names) >= self.n_players:
            return await self._fail(ws, "race full")
        if msg["name"] in self.names.values():
            return await self._fail(ws, "name taken")

        pid = f"p{len(self.names) + 1}"
        self.names[pid] = msg["name"]
        self.conns[pid] = ws
        if msg.get("bot", False):
            self.bots.append(pid)
        await self._send(ws, {"type": "joined", "player_id": pid,
                              "max_guesses": rules.MAX_GUESSES, "hard": self.hard})

        if len(self.names) == self.n_players:
            self.race = Race(self.secret, list(self.names), time_limit=self.time_limit,
                             bots=self.bots)
            self.start = self.clock()
            await self._broadcast({"type": "start", "players": list(self.names.values()),
                                   "seconds_left": self.time_limit})

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except ValueError:
                msg = None
            if isinstance(msg, dict) and msg.get("type") == "guess" \
                    and isinstance(msg.get("word"), str):
                await self._guess(ws, pid, msg["word"])
            else:
                await self._send(ws, {"type": "error", "reason": "unknown message type"})

    async def _guess(self, ws, pid, word):
        if self.race is None:
            return await self._send(ws, {"type": "invalid", "word": word,
                                         "reason": "race not started"})
        if self.done.is_set():
            return
        t = self.clock() - self.start
        try:
            result = self.race.guess(pid, word, t)
        except RaceError as e:
            await self._send(ws, {"type": "invalid", "word": word, "reason": str(e)})
        else:
            if result.legal:
                await self._send(ws, {"type": "feedback", "guess": rules.normalize(word),
                                      "pattern": result.pattern,
                                      "guess_number": result.guess_number})
            else:
                await self._send(ws, {"type": "invalid", "word": word,
                                      "reason": result.reason})
        if self.race.done(t):
            await self._finish()

    async def _finish(self):
        self.done.set()  # set first so results go out exactly once
        ranking = [{"name": self.names[s.player_id], "guesses": s.guesses,
                    "solved": s.solved, "place": s.place, "dropped": s.dropped}
                   for s in self.race.ranking()]
        await self._broadcast({"type": "results", "secret": self.secret,
                               "ranking": ranking})
        for ws in self.conns.values():
            await ws.close()


async def _serve(args):
    server = RaceServer(rules.pick_secret(args.seed), args.players, args.hard,
                        args.time_limit)
    async with serve(server.handler, args.host, args.port):
        await server.done.wait()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--players", type=int, default=2)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--hard", action="store_true")
    p.add_argument("--time-limit", type=float, default=300)
    asyncio.run(_serve(p.parse_args()))


if __name__ == "__main__":
    main()
