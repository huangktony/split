"""Wordle rules: feedback, legal guesses, filtering, secret choice."""

import random
from collections import Counter
from pathlib import Path

GRAY, YELLOW, GREEN = 0, 1, 2
WIN = 242  # all five green: 2*(1+3+9+27+81)
MAX_GUESSES = 6

_DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> list[str]:
    return (_DATA / name).read_text().split()


ANSWERS = _load("answers.txt")  # 2,315, file order
LEGAL = sorted(set(ANSWERS) | set(_load("allowed.txt")))  # 12,972
_LEGAL_SET = set(LEGAL)


def feedback(guess: str, answer: str) -> int:
    """Pattern as base-3 number: position i contributes color * 3**i."""
    colors = [GRAY] * 5
    unmatched = Counter()
    # Greens first; answer letters not matched green are left for yellows.
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            colors[i] = GREEN
        else:
            unmatched[a] += 1
    # Yellows left to right, limited by unmatched copies in the answer.
    for i, g in enumerate(guess):
        if colors[i] != GREEN and unmatched[g] > 0:
            colors[i] = YELLOW
            unmatched[g] -= 1
    return sum(c * 3**i for i, c in enumerate(colors))


def colors(code: int) -> list[int]:
    """242 -> [2, 2, 2, 2, 2]."""
    out = []
    for _ in range(5):
        out.append(code % 3)
        code //= 3
    return out


def pattern_str(code: int) -> str:
    """242 -> 'GGGGG', 0 -> '-----', yellow is 'Y'."""
    return "".join("-YG"[c] for c in colors(code))


def normalize(word: str) -> str:
    return word.strip().lower()


def check_guess(word: str, history: list[tuple[str, int]], hard: bool) -> str | None:
    """None if legal, else a reason. Expects a normalized word.

    Hard mode follows NYT: greens stay in place, and each revealed letter
    appears at least as often as it was green/yellow in one earlier guess.
    Yellows may repeat their spot; gray letters may be reused.
    """
    if word not in _LEGAL_SET:
        return "not in word list"
    if not hard:
        return None
    for guess, code in history:
        cs = colors(code)
        for i, c in enumerate(cs):
            if c == GREEN and word[i] != guess[i]:
                return f"letter {i + 1} must be {guess[i].upper()}"
        needed = Counter(g for g, c in zip(guess, cs) if c != GRAY)
        for letter, n in needed.items():
            if word.count(letter) < n:
                times = "" if n == 1 else f" {n} times"
                return f"must contain {letter.upper()}{times}"
    return None


def filter_candidates(words: list[str], guess: str, pattern: int) -> list[str]:
    return [w for w in words if feedback(guess, w) == pattern]


def pick_secret(seed: int) -> str:
    return random.Random(seed).choice(ANSWERS)
