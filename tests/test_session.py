import unittest

from game import rules
from game.rules import GRAY, YELLOW, GREEN
from game.session import Session, new_secret

SECRET = "crane"
MISSES = ["pious", "audio", "sound", "slate", "apple", "eerie"]


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class SessionTest(unittest.TestCase):
    def test_words_are_legal(self):
        for w in MISSES + [SECRET]:
            self.assertIn(w, rules.LEGAL)

    def test_legal_guess_appended(self):
        s = Session(SECRET)
        self.assertIsNone(s.submit("  SLATE "))
        self.assertEqual(s.history, [("slate", rules.feedback("slate", SECRET))])
        self.assertEqual(s.guesses_left, 5)

    def test_unknown_word_not_counted(self):
        s = Session(SECRET)
        self.assertEqual(s.submit("zzzzz"), "not in word list")
        self.assertEqual(s.history, [])
        self.assertEqual(s.guesses_left, 6)

    def test_hard_mode_violation_rejected(self):
        s = Session(SECRET, hard=True)
        self.assertIsNone(s.submit("slate"))  # A green at 3, E green at 5
        self.assertIsNotNone(s.submit("pious"))
        self.assertEqual(len(s.history), 1)
        self.assertIsNone(Session(SECRET, hard=False).submit("slate"))

    def test_solve(self):
        s = Session(SECRET)
        self.assertFalse(s.finished)
        self.assertIsNone(s.submit("crane"))
        self.assertTrue(s.solved)
        self.assertTrue(s.finished)

    def test_six_misses_finish_unsolved(self):
        s = Session(SECRET)
        for w in MISSES:
            self.assertIsNone(s.submit(w))
        self.assertTrue(s.finished)
        self.assertFalse(s.solved)
        self.assertEqual(s.guesses_left, 0)

    def test_submit_after_finish(self):
        s = Session(SECRET)
        s.submit("crane")
        self.assertEqual(s.submit("slate"), "race is over")
        self.assertEqual(len(s.history), 1)

    def test_letter_states_precedence(self):
        s = Session(SECRET)
        s.submit("audio")  # a yellow, u/d/i/o gray
        self.assertEqual(s.letter_states()["a"], YELLOW)
        s.submit("slate")  # a green, e green, s/l/t gray
        st = s.letter_states()
        self.assertEqual(st["a"], GREEN)
        self.assertEqual(st["s"], GRAY)
        self.assertNotIn("z", st)

    def test_letter_states_duplicate(self):
        s = Session(SECRET)
        s.submit("eerie")  # e gray, gray, green; r yellow
        st = s.letter_states()
        self.assertEqual(st["e"], GREEN)
        self.assertEqual(st["r"], YELLOW)
        self.assertEqual(st["i"], GRAY)

    def test_elapsed_freezes_at_finish(self):
        clock = FakeClock()
        s = Session(SECRET, clock=clock)
        clock.t = 105.0
        self.assertEqual(s.elapsed(), 5.0)
        s.submit("crane")
        clock.t = 200.0
        self.assertEqual(s.elapsed(), 5.0)


class NewSecretTest(unittest.TestCase):
    def test_seeded_deterministic(self):
        self.assertEqual(new_secret(1124), new_secret(1124))
        self.assertEqual(new_secret(1124)[1], 1124)

    def test_none_gives_valid_answer(self):
        secret, seed = new_secret(None)
        self.assertIn(secret, rules.ANSWERS)
        self.assertEqual(rules.pick_secret(seed), secret)


if __name__ == "__main__":
    unittest.main()
