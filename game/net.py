"""Network side of the terminal client.

Connection runs the websocket on a background thread and drops every server
message into a queue, so the curses loop never waits on the network.
NetRace is one player's view of the race, built only from server messages.
"""

import json
import queue
import threading
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from game import rules


class Connection:
    def __init__(self, url: str, name: str, bot: bool = False):
        self.ws = connect(url, open_timeout=5, legacy=True)  # long-lived, not a with block
        self.inbox: queue.Queue = queue.Queue()
        self.ws.send(json.dumps({"type": "join", "name": name, "bot": bot}))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for raw in self.ws:
                self.inbox.put(json.loads(raw))
        except ConnectionClosed:
            pass
        finally:
            self.inbox.put({"type": "_closed"})

    def guess(self, word: str):
        try:
            self.ws.send(json.dumps({"type": "guess", "word": word}))
        except ConnectionClosed:
            pass

    def messages(self) -> list[dict]:
        """Every message received since the last call, without waiting."""
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self.ws.close()


class NetRace:
    def __init__(self, name: str, clock=time.monotonic):
        self.name = name
        self.clock = clock
        self.phase = "lobby"       # lobby, race, results, error
        self.hard = False
        self.mode = "server"       # where feedback is computed
        self.secret = None         # known at start only in client mode
        self.players: list[str] = []
        self.opponents: dict[str, dict] = {}   # name -> guesses, solved, left
        self.history: list[tuple[str, int]] = []
        self.end_at = None         # local clock time the race ends
        self.pending = False       # a guess is waiting for its reply
        self.error = ""
        self.results = None

    def apply(self, msg: dict):
        t = msg["type"]
        if t == "joined":
            self.hard = msg.get("hard", False)
            self.mode = msg.get("feedback", "server")
        elif t == "start":
            self.phase = "race"
            self.players = msg["players"]
            self.opponents = {p: {"guesses": 0, "solved": False, "left": False}
                              for p in self.players if p != self.name}
            self.end_at = self.clock() + msg["seconds_left"]
            self.secret = msg.get("secret")
        elif t == "feedback":
            code = msg.get("pattern")
            if code is None:  # client mode: color it ourselves
                code = rules.feedback(msg["guess"], self.secret)
            self.history.append((msg["guess"], code))
            self.pending = False
            self.error = ""
        elif t == "invalid":
            self.pending = False
            self.error = f'"{msg["word"].strip().upper()}": {msg["reason"]}'
        elif t == "progress":
            self.opponents[msg["name"]].update(guesses=msg["guesses"], solved=msg["solved"])
        elif t == "left":
            self.opponents[msg["name"]]["left"] = True
        elif t == "deadline":
            self.end_at = self.clock() + msg["seconds_left"]
        elif t == "results":
            self.phase = "results"
            self.results = msg["ranking"]
            self.secret = msg["secret"]
        elif t == "error":
            self.phase = "error"
            self.error = msg["reason"]
        elif t == "_closed" and self.phase not in ("results", "error"):
            self.phase = "error"
            self.error = "connection to the server was lost"

    @property
    def solved(self) -> bool:
        return bool(self.history) and self.history[-1][1] == rules.WIN

    @property
    def finished(self) -> bool:
        return self.solved or len(self.history) == rules.MAX_GUESSES

    def seconds_left(self) -> float:
        return 0.0 if self.end_at is None else max(0.0, self.end_at - self.clock())

    def letter_states(self) -> dict[str, int]:
        best: dict[str, int] = {}
        for word, code in self.history:
            for letter, c in zip(word, rules.colors(code)):
                if c > best.get(letter, -1):
                    best[letter] = c
        return best
