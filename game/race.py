"""Multiplayer Wordle race core, stage 1: per-player guesses against one secret."""

from dataclasses import dataclass, field

from game import rules


class RaceError(Exception):
    pass


@dataclass(frozen=True)
class GuessResult:
    pattern: int
    guess_number: int
    solved: bool
    finished: bool


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
        player = self._players[player_id]
        if player.finished:
            raise RaceError("player already finished")
        pattern = rules.feedback(word, self._secret)
        player.history.append((word, pattern))
        number = len(player.history)
        solved = pattern == rules.WIN
        finished = solved or number == rules.MAX_GUESSES
        if finished:
            player.finished = True
            player.finish_time = t
        return GuessResult(pattern, number, solved, finished)
