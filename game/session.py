import random
import time

from game import rules


def new_secret(seed: int | None) -> tuple[str, int]:
    if seed is None:
        seed = random.randrange(10**6)
    return rules.pick_secret(seed), seed


class Session:
    def __init__(self, secret: str, hard: bool = False, clock=time.monotonic):
        self.secret = secret
        self.hard = hard
        self.history: list[tuple[str, int]] = []
        self._clock = clock
        self._start = clock()
        self._end: float | None = None

    def submit(self, word: str) -> str | None:
        if self.finished:
            return "race is over"
        word = rules.normalize(word)
        reason = rules.check_guess(word, self.history, self.hard)
        if reason is not None:
            return reason
        self.history.append((word, rules.feedback(word, self.secret)))
        if self.finished:
            self._end = self._clock()
        return None

    @property
    def solved(self) -> bool:
        return bool(self.history) and self.history[-1][1] == rules.WIN

    @property
    def finished(self) -> bool:
        return self.solved or len(self.history) == rules.MAX_GUESSES

    @property
    def guesses_left(self) -> int:
        return rules.MAX_GUESSES - len(self.history)

    def letter_states(self) -> dict[str, int]:
        best: dict[str, int] = {}
        for word, code in self.history:
            for letter, c in zip(word, rules.colors(code)):
                if c > best.get(letter, -1):
                    best[letter] = c
        return best

    def elapsed(self) -> float:
        end = self._end if self._end is not None else self._clock()
        return end - self._start
