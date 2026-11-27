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


@dataclass
class _Player:
    history: list[tuple[str, int]] = field(default_factory=list)
    finished: bool = False
    finish_time: float | None = None


class Race:
    def __init__(self, secret: str, player_ids: list[str]):
        self._secret = secret
        self._players = {pid: _Player() for pid in player_ids}

    def guess(self, player_id: str, word: str, t: float) -> GuessResult:
        player = self._players.get(player_id)
        if player is None:
            raise RaceError("unknown player")
        if player.finished:
            raise RaceError("player already finished")
        word = rules.normalize(word)
        reason = rules.check_guess(word, player.history, hard=False)
        if reason is not None:
            return GuessResult(False, None, len(player.history), False, False, reason)
        pattern = rules.feedback(word, self._secret)
        player.history.append((word, pattern))
        number = len(player.history)
        solved = pattern == rules.WIN
        finished = solved or number == rules.MAX_GUESSES
        if finished:
            player.finished = True
            player.finish_time = t
        return GuessResult(True, pattern, number, solved, finished)
