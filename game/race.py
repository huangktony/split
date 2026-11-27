"""Multiplayer Wordle race core: per-player guesses with legality checks."""

from dataclasses import dataclass, field

from game import rules


class RaceError(Exception):
    pass


@dataclass(frozen=True)
class GuessResult:
    legal: bool
    pattern: int | None      # None when not legal
    guess_number: int        # counted guesses so far for this player (unchanged by a rejected word)
    solved: bool
    finished: bool
    reason: str | None = None  # why the word was rejected; None when legal


@dataclass(frozen=True)
class Standing:
    player_id: str
    solved: bool
    guesses: int               # counted (legal) guesses used
    finish_time: float | None  # None if the player has not finished
    place: int                 # 1 = best


@dataclass
class _Player:
    history: list[tuple[str, int]] = field(default_factory=list)
    finished: bool = False
    finish_time: float | None = None
    solved: bool = False


class Race:
    def __init__(self, secret: str, player_ids: list[str], time_limit: float = 300,
                 bots: list[str] = ()):
        if not player_ids:
            raise RaceError("need at least one player")
        if len(set(player_ids)) != len(player_ids):
            raise RaceError("duplicate player id")
        if time_limit <= 0:
            raise RaceError("time limit must be positive")
        if not set(bots) <= set(player_ids):
            raise RaceError("unknown bot")
        self._secret = secret
        self._deadline = time_limit
        self._bots = set(bots)
        self._players = {pid: _Player() for pid in player_ids}

    @property
    def deadline(self) -> float:
        return self._deadline

    def done(self, t: float | None = None) -> bool:
        if t is not None and t > self._deadline:
            return True
        return all(p.finished for p in self._players.values())

    def guess(self, player_id: str, word: str, t: float) -> GuessResult:
        player = self._players.get(player_id)
        if player is None:
            raise RaceError("unknown player")
        if player.finished:
            raise RaceError("player already finished")
        if t > self._deadline:
            raise RaceError("race over")
        word = rules.normalize(word)
        reason = rules.check_guess(word, player.history, hard=False)
        if reason is not None:
            return GuessResult(False, None, len(player.history), False, False, reason)
        pattern = rules.feedback(word, self._secret)
        player.history.append((word, pattern))
        number = len(player.history)
        solved = pattern == rules.WIN
        finished = solved or number == rules.MAX_GUESSES
        player.solved = solved
        if finished:
            player.finished = True
            player.finish_time = t
        # A human solve halves the time left; the bot is excluded because it
        # solves in milliseconds and would halve every race.
        if solved and player_id not in self._bots:
            self._deadline = t + (self._deadline - t) / 2
        return GuessResult(True, pattern, number, solved, finished)

    def ranking(self) -> list[Standing]:
        items = [(pid, p) for pid, p in self._players.items()]
        solvers = sorted((i for i in items if i[1].solved),
                         key=lambda i: len(i[1].history))  # stable: keeps join order
        out = []
        place = 0
        for n, (pid, p) in enumerate(solvers):
            if n == 0 or len(p.history) != len(solvers[n - 1][1].history):
                place = n + 1  # competition ranking: 1, 1, 3
            out.append(Standing(pid, True, len(p.history), p.finish_time, place))
        unsolved_place = len(solvers) + 1
        for pid, p in items:
            if not p.solved:
                out.append(Standing(pid, False, len(p.history), p.finish_time,
                                    unsolved_place))
        return out
