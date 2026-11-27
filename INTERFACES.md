# Shared interfaces (DRAFT for day 1, not yet agreed)

Three seams between Game (A) and Bot (B). Everything else is private to each folder.

## 1. Words and feedback (`game/rules.py`)

Word lists live in `data/`:

- `data/answers.txt`: 2,315 possible answers
- `data/allowed.txt`: 10,657 extra legal guesses (does NOT include the answers)
- Legal guesses = answers + allowed = 12,972 words. Feedback table shape = 12,972 x 2,315 = 30,030,180 pairs.

```python
GRAY, YELLOW, GREEN = 0, 1, 2

def feedback(guess: str, answer: str) -> int:
    """Pattern as a base-3 number: position i contributes color * 3**i.
    0 = all gray, 242 = all green. Repeated letters follow NYT rules:
    greens first, then yellows left to right, limited by how many of
    that letter remain unmatched in the answer."""

def pattern_str(code: int) -> str:
    """242 -> 'GGGGG', 0 -> '-----', yellow is 'Y'."""

def normalize(word: str) -> str:
    """Strip whitespace, lowercase."""

def check_guess(word: str, history: list[tuple[str, int]], hard: bool) -> str | None:
    """None if legal, else a reason string. Normal mode: word must be one of
    the 12,972 legal guesses. Hard mode (NYT rule): also every green letter
    stays in its spot, and every revealed letter appears at least as many
    times as it was shown green or yellow in a single earlier guess. Yellows
    may repeat their spot and gray letters may be reused."""

def filter_candidates(words: list[str], guess: str, pattern: int) -> list[str]:
    """Words w with feedback(guess, w) == pattern."""

def pick_secret(seed: int) -> str:
    """random.Random(seed).choice(answers)."""

WIN = 242
MAX_GUESSES = 6
```

Rejected guesses (unknown word or hard-mode violation) do not count toward the 6.

Why an int: it fits in one byte, so the precomputed table is a 30 MB `uint8` NumPy array (`table[guess_index, answer_index]`), and the bot can bucket the remaining answers with `np.bincount` instead of a Python loop.

Precomputed table: `scripts/build_table.py` writes `data/table.npy` (gitignored). Row order = sorted legal guesses, column order = `answers.txt` order.

## 2. Player interface (what the bot implements)

```python
class Player:
    name: str
    def next_guess(self, history: list[tuple[str, int]]) -> str:
        """history = [(guess, pattern_code), ...] for this player only."""
```

The bot never sees the secret. It joins a race through the same websocket client a human uses, so the server cannot tell it apart from a person.

## 3. Race server

Pure core, no networking, so tests can drive it with fake players and fake clocks:

```python
class Race:
    def __init__(self, secret: str, player_ids: list[str], rule: str = "fewest_guesses", hard: bool = False, time_limit: float = 300): ...
    def drop(self, player_id: str) -> None: ...
    def guess(self, player_id: str, word: str, t: float) -> GuessResult: ...
    def ranking(self) -> list[Standing]: ...
    def done(self) -> bool: ...

GuessResult: legal: bool, pattern: int | None, guess_number: int, solved: bool, finished: bool
Standing:    player_id, solved: bool, guesses: int, finish_time: float | None, place: int
```

- `t` is the server's arrival time, never a client clock.
- `rule="fewest_guesses"`: solved first, then fewer guesses. Equal guesses share a place (1, 1, 3); time is not a tiebreak, because the bot answers in milliseconds and would win every tie.
- `rule="first_to_solve"`: solved first, then earlier `finish_time`. Kept runnable for the winner-rule comparison.
- `time_limit` (seconds, default 300, clock starts at t=0): guesses after it are refused with "race over", and the race is done once every player is finished or time is up.
- Unsolved players (6 misses, dropped connection, or out of time) rank last, tied with each other.
- Illegal guesses do not count as a guess.

### Websocket messages (JSON, one object per message)

Client to server:

```json
{"type": "join",  "name": "tony"}
{"type": "guess", "word": "salet"}
```

Server to client:

```json
{"type": "joined",   "player_id": "p2", "max_guesses": 6, "hard": false}
{"type": "start",    "players": ["tony", "mahitha", "bot"]}
{"type": "feedback", "guess": "salet", "pattern": 34, "guess_number": 1}
{"type": "invalid",  "word": "xxxxx", "reason": "not in word list"}
{"type": "progress", "name": "bot", "guesses": 3, "solved": false}
{"type": "results",  "secret": "crane", "ranking": [{"name": "bot", "guesses": 3, "solved": true, "place": 1}]}
```

Leak rule: the secret appears only in `results`, sent after `Race.done()`. `progress` shows opponents' guess counts, never their letters or patterns (patterns would leak information about the shared word).
