"""Websocket server for a multiplayer Wordle race."""

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
                 rule: str = "fewest_guesses", time_limit: float = 300, clock=time.monotonic,
                 feedback: str = "server"):
        if feedback not in ("server", "client"):
            raise ValueError("feedback must be 'server' or 'client'")
        # "client": every client gets the secret at start and colors its own guesses.
        # Kept only to compare against "server" with the leak scan.
        self.feedback = feedback
        self.secret = secret
        self.n_players = n_players
        self.hard = hard
        self.rule = rule
        self.time_limit = time_limit
        self.clock = clock
        self.done = asyncio.Event()
        self.wake = asyncio.Event()    # set when the deadline may have changed
        self.timer = None
        self.race = None
        self.start = None
        self.names = {}    # player_id -> name, in join order
        self.bots = []
        self.conns = {}    # player_id -> websocket
        self.next_id = 1   # never reused, even after a lobby leave

    async def _send(self, ws, msg):
        await ws.send(json.dumps(msg))

    async def _fail(self, ws, reason):
        await self._send(ws, {"type": "error", "reason": reason})
        await ws.close()

    async def _broadcast(self, msg, skip=None):
        for ws in list(self.conns.values()):  # copy: a disconnect can edit conns mid-loop
            if ws is skip:
                continue
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

        pid = f"p{self.next_id}"
        self.next_id += 1
        self.names[pid] = msg["name"]
        self.conns[pid] = ws
        if msg.get("bot", False):
            self.bots.append(pid)
        try:
            await self._send(ws, {"type": "joined", "player_id": pid,
                                  "max_guesses": rules.MAX_GUESSES, "hard": self.hard,
                                  "feedback": self.feedback})

            if len(self.names) == self.n_players:
                self.race = Race(self.secret, list(self.names), time_limit=self.time_limit,
                                 hard=self.hard, rule=self.rule,
                                 bots=self.bots)
                self.start = self.clock()
                self.timer = asyncio.create_task(self._watch_deadline())
                start_msg = {"type": "start", "players": list(self.names.values()),
                             "seconds_left": self.time_limit}
                if self.feedback == "client":
                    start_msg["secret"] = self.secret
                await self._broadcast(start_msg)

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
        finally:
            await self._leave(pid)

    async def _leave(self, pid):
        if self.done.is_set():
            return
        if self.race is None:
            del self.names[pid]
            del self.conns[pid]
            if pid in self.bots:
                self.bots.remove(pid)
            return
        self.race.drop(pid)
        del self.conns[pid]
        await self._broadcast({"type": "left", "name": self.names[pid]})
        if self.race.done(self.clock() - self.start):
            await self._finish()

    async def _guess(self, ws, pid, word):
        if self.race is None:
            return await self._send(ws, {"type": "invalid", "word": word,
                                         "reason": "race not started"})
        if self.done.is_set():
            return
        t = self.clock() - self.start
        old_deadline = self.race.deadline
        try:
            result = self.race.guess(pid, word, t)
        except RaceError as e:
            await self._send(ws, {"type": "invalid", "word": word, "reason": str(e)})
        else:
            if result.legal:
                reply = {"type": "feedback", "guess": rules.normalize(word),
                         "guess_number": result.guess_number}
                if self.feedback == "server":
                    reply["pattern"] = result.pattern
                await self._send(ws, reply)
                await self._broadcast({"type": "progress", "name": self.names[pid],
                                       "guesses": result.guess_number,
                                       "solved": result.solved}, skip=ws)
                if self.race.deadline != old_deadline:
                    await self._broadcast({"type": "deadline",
                                           "seconds_left": self.race.deadline - t})
                    self.wake.set()
            else:
                await self._send(ws, {"type": "invalid", "word": word,
                                      "reason": result.reason})
        if self.race.done(t):
            await self._finish()

    async def _watch_deadline(self):
        while not self.done.is_set():
            now = self.clock() - self.start
            try:
                await asyncio.wait_for(self.wake.wait(),
                                       max(0, self.race.deadline - now) + 0.01)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            if not self.done.is_set() and self.race.done(self.clock() - self.start):
                await self._finish()

    async def _finish(self):
        self.done.set()  # set first so results go out exactly once
        self.wake.set()  # lets the timer task exit
        ranking = [{"name": self.names[s.player_id], "guesses": s.guesses,
                    "solved": s.solved, "place": s.place, "dropped": s.dropped}
                   for s in self.race.ranking()]
        await self._broadcast({"type": "results", "secret": self.secret,
                               "ranking": ranking})
        for ws in list(self.conns.values()):  # copy: a disconnect can edit conns mid-loop
            await ws.close()


async def _serve(args):
    server = RaceServer(rules.pick_secret(args.seed), args.players, args.hard,
                        rule=args.rule, time_limit=args.time_limit,
                        feedback=args.feedback)
    async with serve(server.handler, args.host, args.port):
        await server.done.wait()
        if server.timer is not None:
            await server.timer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--players", type=int, default=2)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--hard", action="store_true")
    p.add_argument("--rule", choices=["fewest_guesses", "first_to_solve"],
                   default="fewest_guesses")
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--feedback", choices=["server", "client"], default="server")
    asyncio.run(_serve(p.parse_args()))


if __name__ == "__main__":
    main()
