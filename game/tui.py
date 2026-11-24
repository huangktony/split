"""Terminal frontend for the Wordle race (stdlib curses only).

Run:  python3 -m game.tui [--seed N] [--hard]
Three screens: create -> race -> results (then back to create).
"""

import argparse
import curses
import locale
import os
import textwrap

from game import rules, session

DEFAULT_SEED = 1124

# --- palettes ---------------------------------------------------------------

BASE = {
    "bg": "#121214", "panel": "#1B1B1F", "border": "#2A2A2E", "border2": "#3A3A3E",
    "text": "#E6E6E8", "muted": "#9A9AA2", "empty": "#2E2E33",
    "err": "#F2A35E", "ok": "#7CC487",
    "key": "#3E3E44", "keydark": "#232326", "keydim": "#6A6A72",
    "dark": "#121214",
}
PALETTES = {
    "classic": {**BASE, "green": "#538D4E", "yellow": "#B59F3B", "gray": "#3A3A3C",
                "yellow_text": "#FFFFFF"},
    "high contrast": {**BASE, "green": "#F5793A", "yellow": "#85C0F9", "gray": "#3A3A3C",
                      "yellow_text": "#121214"},
}
PALETTE_NAMES = list(PALETTES)

# state codes for board tiles beyond rules.GRAY/YELLOW/GREEN
TYPED, EMPTY = 3, 4


# --- pure helpers -----------------------------------------------------------

def fmt_time(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_time_precise(sec: float) -> str:
    tenths = int(sec * 10)
    return f"{tenths // 600}:{tenths // 10 % 60:02d}.{tenths % 10}"


def board_rows(s, buf: str) -> list[list[tuple[str, int]]]:
    """Six rows of five (letter, state) pairs: history, then typed, then empty."""
    rows = []
    for word, code in s.history:
        rows.append(list(zip(word.upper(), rules.colors(code))))
    if len(rows) < rules.MAX_GUESSES:
        rows.append([(buf[i].upper(), TYPED) if i < len(buf) else (" ", EMPTY)
                     for i in range(5)])
    while len(rows) < rules.MAX_GUESSES:
        rows.append([(" ", EMPTY)] * 5)
    return rows


def pips(used: int) -> str:
    return "■" * used + "□" * (rules.MAX_GUESSES - used)


# --- color handling ---------------------------------------------------------

def _hex_rgb(h):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _xterm_candidates():
    levels = [0, 95, 135, 175, 215, 255]
    out = [(16 + 36 * r + 6 * g + b, (levels[r], levels[g], levels[b]))
           for r in range(6) for g in range(6) for b in range(6)]
    out += [(232 + i, (8 + 10 * i,) * 3) for i in range(24)]
    return out


_BASIC8 = [(0, (0, 0, 0)), (1, (205, 0, 0)), (2, (0, 205, 0)), (3, (205, 205, 0)),
           (4, (0, 0, 238)), (5, (205, 0, 205)), (6, (0, 205, 205)), (7, (229, 229, 229))]


class Colors:
    def __init__(self):
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        self.can_change = curses.can_change_color() and curses.COLORS >= 256
        if self.can_change:
            self.cands = None
        elif curses.COLORS >= 256:
            self.cands = _xterm_candidates()
        else:
            self.cands = _BASIC8
        self.idx = {}      # hex -> color index
        self.pairs = {}    # (fg hex, bg hex) -> pair number
        self.next_color = 16
        self.palette = PALETTES[PALETTE_NAMES[0]]

    def toggle(self):
        i = (PALETTE_NAMES.index(self.name) + 1) % len(PALETTE_NAMES)
        self.palette = PALETTES[PALETTE_NAMES[i]]

    @property
    def name(self):
        return next(n for n, p in PALETTES.items() if p is self.palette)

    def _color(self, h):
        if h in self.idx:
            return self.idx[h]
        if self.can_change:
            n = self.next_color
            self.next_color += 1
            r, g, b = (v * 1000 // 255 for v in _hex_rgb(h))
            curses.init_color(n, r, g, b)
        else:
            rgb = _hex_rgb(h)
            n = min(self.cands,
                    key=lambda c: sum((a - b) ** 2 for a, b in zip(c[1], rgb)))[0]
        self.idx[h] = n
        return n

    def attr(self, fg="text", bg="bg", bold=False):
        p = self.palette
        f = p.get(fg, fg)
        b = p.get(bg, bg)
        key = (f, b)
        if key not in self.pairs:
            n = len(self.pairs) + 1
            try:
                curses.init_pair(n, self._color(f), self._color(b))
            except curses.error:
                return curses.A_BOLD if bold else 0
            self.pairs[key] = n
        a = curses.color_pair(self.pairs[key])
        return a | curses.A_BOLD if bold else a


# --- drawing primitives -----------------------------------------------------

def put(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def fill(win, y, x, w, h, attr):
    for r in range(h):
        put(win, y + r, x, " " * w, attr)


def box(win, y, x, w, h, title, C):
    a = C.attr("border2", "bg")
    put(win, y, x, "┌" + "─" * (w - 2) + "┐", a)
    for r in range(1, h - 1):
        put(win, y + r, x, "│", a)
        put(win, y + r, x + w - 1, "│", a)
    put(win, y + h - 1, x, "└" + "─" * (w - 2) + "┘", a)
    put(win, y, x + 2, f" {title} ", C.attr("muted", "bg", bold=True))


def top_bar(win, C, left, right):
    h, w = win.getmaxyx()
    put(win, 0, 1, left, C.attr("muted"))
    put(win, 0, max(1, w - len(right) - 1), right, C.attr("muted"))
    put(win, 1, 0, "─" * w, C.attr("border"))


def footer(win, C, left, right=""):
    h, w = win.getmaxyx()
    put(win, h - 1, 1, left, C.attr("muted"))
    if right:
        put(win, h - 1, max(1, w - len(right) - 1), right, C.attr("muted"))


def tile_colors(C, state):
    """(fg, bg) role names for a tile state."""
    if state == rules.GREEN:
        return "text", "green"
    if state == rules.YELLOW:
        return "yellow_text", "yellow"
    if state == rules.GRAY:
        return "text", "gray"
    return "text", "bg"


def draw_tile(win, C, y, x, letter, state, big):
    if state in (TYPED, EMPTY):
        bd = "muted" if state == TYPED else "empty"
        a = C.attr(bd, "bg")
        la = C.attr("text", "bg", bold=True)
        if big:
            put(win, y, x, "┌───┐", a)
            put(win, y + 1, x, "│", a)
            put(win, y + 1, x + 1, f" {letter} ", la)
            put(win, y + 1, x + 4, "│", a)
            put(win, y + 2, x, "└───┘", a)
        else:
            put(win, y, x, f" {letter if letter != ' ' else '·'} ",
                la if state == TYPED else a)
        return
    fg, bg = tile_colors(C, state)
    a = C.attr(fg, bg, bold=True)
    if big:
        put(win, y, x, " " * 5, a)
        put(win, y + 1, x, f"  {letter}  ", a)
        put(win, y + 2, x, " " * 5, a)
    else:
        put(win, y, x, f" {letter} ", a)


def draw_board(win, C, y, x, rows, big):
    tw, th = (5, 3) if big else (3, 1)
    for r, row in enumerate(rows):
        for c, (letter, state) in enumerate(row):
            draw_tile(win, C, y + r * th, x + c * (tw + 1), letter, state, big)
    return 5 * (tw + 1) - 1, 6 * th  # width, height


def draw_keyboard(win, C, y, x, letter_states):
    for r, row in enumerate(("qwertyuiop", "asdfghjkl", "zxcvbnm")):
        for i, ch in enumerate(row):
            st = letter_states.get(ch)
            if st is None:
                a = C.attr("text", "key")
            elif st == rules.GRAY:
                a = C.attr("keydim", "keydark")
            else:
                fg, bg = tile_colors(C, st)
                a = C.attr(fg, bg, bold=True)
            put(win, y + r, x + r * 2 + i * 4, f" {ch.upper()} ", a)


# --- screens ----------------------------------------------------------------

class App:
    def __init__(self, win, seed, hard):
        self.win = win
        self.C = Colors()
        self.seed = seed
        self.fixed = True
        self.hard = hard
        self.race_no = 1
        self.screen = "create"
        self.sel = 0
        self.s = None
        self.used_seed = seed
        self.buf = ""
        self.error = ""
        win.keypad(True)
        win.bkgd(" ", self.C.attr("text", "bg"))
        curses.curs_set(0)

    def too_small(self):
        h, w = self.win.getmaxyx()
        if h < 16 or w < 64:
            put(self.win, 0, 0, "terminal too small"[: max(w - 1, 0)])
            return True
        return False

    # -- create --
    def draw_create(self):
        C, win = self.C, self.win
        top_bar(win, C, "split · local", "solo, no server")
        put(win, 3, 4, "Create a room", C.attr("text", "bg", bold=True))
        opts = [
            ("Word", "fixed" if self.fixed else "random", ("fixed", "random"),
             f"seed {self.seed}, same word every run" if self.fixed else "new word each race"),
            ("Hard mode", "on" if self.hard else "off", ("off", "on"), ""),
        ]
        for i, (label, val, choices, note) in enumerate(opts):
            y = 6 + i * 2
            cur = i == self.sel
            put(win, y, 4, "›" if cur else " ", C.attr("ok"))
            put(win, y, 6, f"{label:<12}", C.attr("text" if cur else "muted"))
            x = 20
            for ch in choices:
                on = ch == val
                put(win, y, x, f" {ch} ",
                    C.attr("text", "border2", bold=True) if on else C.attr("muted"))
                x += len(ch) + 3
            if note:
                put(win, y, x + 2, note, C.attr("muted"))
        footer(win, C, "[enter] start race   [↑↓] move   [←→/space] change", "[q] quit")

    def key_create(self, k):
        if k in (curses.KEY_UP, curses.KEY_DOWN):
            self.sel = 1 - self.sel
        elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
            if self.sel == 0:
                self.fixed = not self.fixed
            else:
                self.hard = not self.hard
        elif k in (10, 13, curses.KEY_ENTER):
            self.start_race()
        elif k in (ord("q"), ord("Q")):
            return False
        return True

    def start_race(self):
        secret, used = session.new_secret(self.seed if self.fixed else None)
        self.used_seed = used
        self.s = session.Session(secret, hard=self.hard)
        self.secret = secret
        self.buf = ""
        self.error = ""
        self.screen = "race"

    # -- race --
    def draw_race(self):
        C, win, s = self.C, self.win, self.s
        h, w = win.getmaxyx()
        top_bar(win, C, f"split · seed {self.used_seed} · race #{self.race_no}",
                f"{fmt_time(s.elapsed())} elapsed")
        big = h >= 27 and w >= 80
        put(win, 3, 2, f"YOUR BOARD · guess {min(len(s.history) + 1, 6)} of 6",
            C.attr("muted", "bg", bold=True))
        bw, bh = draw_board(win, C, 5, 2, board_rows(s, self.buf), big)
        py = 5 + bh + 1
        put(win, py, 2, "> ", C.attr("muted"))
        put(win, py, 4, self.buf.upper(), C.attr("text", "bg", bold=True))
        put(win, py, 4 + len(self.buf), "█", C.attr("text"))
        if self.error:
            put(win, py + 1, 2, "! " + self.error, C.attr("err"))

        px = 2 + bw + 4
        pw = min(42, w - px - 1)
        # RACE box
        box(win, 4, px, pw, 7, "RACE", C)
        if s.solved:
            status = f"✓ solved in {len(s.history)}"
            sa = C.attr("ok")
        elif s.finished:
            status, sa = "✗ out of guesses", C.attr("err")
        else:
            status, sa = "playing", C.attr("muted")
        put(win, 6, px + 2, "you", C.attr("text", "bg", bold=True))
        put(win, 6, px + 8, pips(len(s.history)), C.attr("text"))
        put(win, 6, px + 16, status, sa)
        for i, line in enumerate(textwrap.wrap(
                "Guess counts only. Nobody sees anyone else's letters.", pw - 4)[:2]):
            put(win, 8 + i, px + 2, line, C.attr("muted"))
        # LETTERS
        box(win, 12, px, pw, 6, "LETTERS", C)
        draw_keyboard(win, C, 14, px + 2, s.letter_states())
        pal = " | ".join(f"[{n}]" if n == C.name else n for n in PALETTE_NAMES)
        footer(win, C, f"[enter] guess   [esc] clear   [tab] colors: {pal}")

    def key_race(self, k):
        s = self.s
        if k in (curses.KEY_BACKSPACE, 127, 8):
            self.buf = self.buf[:-1]
            self.error = ""
        elif k == 27:
            self.buf = ""
            self.error = ""
        elif k in (10, 13, curses.KEY_ENTER):
            if len(self.buf) < 5:
                self.error = "need 5 letters"
            else:
                reason = s.submit(self.buf)
                if reason is None:
                    self.buf = ""
                    self.error = ""
                    if s.finished:
                        self.screen = "results"
                else:
                    self.error = f'"{self.buf.upper()}": {reason}'
        elif k == 9:  # Tab, so letters (incl. C) always type
            self.C.toggle()
        elif 0 <= k < 256 and chr(k).isalpha() and chr(k).isascii():
            if len(self.buf) < 5:
                self.buf += chr(k).lower()
                self.error = ""
        return True

    # -- results --
    def draw_results(self):
        C, win, s = self.C, self.win, self.s
        top_bar(win, C, f"split · seed {self.used_seed} · race #{self.race_no}", "finished")
        put(win, 3, 4, "The word was", C.attr("muted"))
        for i, ch in enumerate(self.secret.upper()):
            draw_tile(win, C, 5, 4 + i * 6, ch, rules.GREEN, True)
        y = 10
        put(win, y, 4, f"{'RANK':<6}{'PLAYER':<10}{'GUESSES':<10}{'FINISHED':<11}NOTE",
            C.attr("muted", "bg", bold=True))
        put(win, y + 1, 4, "─" * 50, C.attr("border"))
        if s.solved:
            row = f"{'1':<6}{'you':<10}{len(s.history):<10}{fmt_time_precise(s.elapsed()):<11}"
            note, na = "", C.attr("ok")
        else:
            row = f"{'✗':<6}{'you':<10}{'X':<10}{fmt_time_precise(s.elapsed()):<11}"
            note, na = "didn't solve in 6", C.attr("err")
        put(win, y + 2, 4, row, C.attr("text"))
        put(win, y + 2, 4 + len(row), note, na)
        put(win, y + 4, 4, "Ranked by fewest guesses. Same count: earlier finish ranks higher.",
            C.attr("muted"))
        footer(win, C, "[enter] play again", "[q] quit")

    def key_results(self, k):
        if k in (10, 13, curses.KEY_ENTER):
            self.race_no += 1
            self.screen = "create"
        elif k in (ord("q"), ord("Q")):
            return False
        return True

    # -- loop --
    def run(self):
        self.win.timeout(200)
        while True:
            self.win.erase()
            if not self.too_small():
                getattr(self, f"draw_{self.screen}")()
            self.win.refresh()
            k = self.win.getch()
            if k == -1:
                continue
            if k == curses.KEY_RESIZE:
                continue
            if not getattr(self, f"key_{self.screen}")(k):
                return


def main(stdscr, seed, hard):
    App(stdscr, seed, hard).run()


def cli():
    ap = argparse.ArgumentParser(prog="python3 -m game.tui")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--hard", action="store_true")
    args = ap.parse_args()
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main, args.seed, args.hard)


if __name__ == "__main__":
    cli()
