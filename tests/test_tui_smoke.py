import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path

from game import rules

ROOT = Path(__file__).resolve().parent.parent
ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-B]|\x1b[=>]")


class TuiSmoke(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        env = dict(os.environ, TERM="xterm-256color", LANG="en_US.UTF-8",
                   LC_ALL="en_US.UTF-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "game.tui", "--seed", "1124"],
            stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env,
            close_fds=True)
        os.close(slave)
        self.out = b""

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        os.close(self.master)

    def pump(self, secs=0.0, until=None):
        """Read output for up to secs; stop early once `until` is in it."""
        end = time.time() + secs
        while time.time() < end:
            if until and until in ANSI.sub(b"", self.out):
                return True
            r, _, _ = select.select([self.master], [], [], 0.05)
            if r:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.out += chunk
        return bool(until) and until in ANSI.sub(b"", self.out)

    def send(self, text):
        os.write(self.master, text.encode())
        self.pump(0.4)

    def test_full_race(self):
        secret = rules.pick_secret(1124)
        self.assertTrue(self.pump(5, b"Create a room"), "create screen never shown")
        self.send("\r")
        self.assertTrue(self.pump(3, b"YOUR BOARD"), "race screen never shown")
        self.send("xxxxx\r")
        self.assertTrue(self.pump(3, b"not in word list"), "no rejection shown")
        self.send("\x1b")  # clear the rejected word
        self.send(secret + "\r")
        self.assertTrue(self.pump(5, b"The word was"), "results screen never shown")
        letters = rb"\s+".join(re.escape(c.encode()) for c in secret.upper())
        self.assertRegex(ANSI.sub(b"", self.out), letters)
        self.send("q")
        deadline = time.time() + 10
        while self.proc.poll() is None and time.time() < deadline:
            self.pump(0.1)
        self.assertEqual(self.proc.poll(), 0)


if __name__ == "__main__":
    unittest.main()
