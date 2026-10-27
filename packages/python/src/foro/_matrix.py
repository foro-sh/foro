"""`foro matrix` easter egg, inspired by cmatrix (https://github.com/abishekvashok/cmatrix)."""

from __future__ import annotations

import curses
import random
import time

from foro import _BANNER

_GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜ0123456789foro"
_LOGO = _BANNER.strip("\n").splitlines()
_TAGLINE = "follow the white rabbit -> foro.sh"


def _put(scr, y: int, x: int, ch: str, attr: int = 0) -> None:
    try:
        scr.addstr(y, x, ch, attr)
    except curses.error:  # off-screen or bottom-right cell
        pass


def _rain(scr) -> None:
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    green, head = curses.color_pair(1), curses.A_BOLD
    scr.nodelay(True)

    while True:
        h, w = scr.getmaxyx()
        top, left = (h - len(_LOGO)) // 2, (w - max(map(len, _LOGO))) // 2
        logo = {
            (top + r, left + c): ch
            for r, line in enumerate(_LOGO)
            for c, ch in enumerate(line)
            if ch != " "
        }
        revealed: set[tuple[int, int]] = set()
        typed = 0.0
        drops = [random.randrange(-h, 0) for _ in range(w)]
        tails = [random.randrange(4, max(5, h // 2)) for _ in range(w)]
        scr.erase()

        while (key := scr.getch()) == -1:
            for x in range(w):
                y = drops[x]
                _put(scr, y, x, random.choice(_GLYPHS), head)
                _put(scr, y - 1, x, random.choice(_GLYPHS), green)
                _put(scr, y - tails[x], x, " ")
                if (y, x) in logo:
                    revealed.add((y, x))
                drops[x] = y + 1 if y - tails[x] < h else random.randrange(-h // 2, 0)

            for pos in revealed:
                _put(scr, *pos, logo[pos], green | curses.A_BOLD)
            if len(revealed) == len(logo):
                typed = min(typed + 0.5, len(_TAGLINE))
                line = _TAGLINE[: int(typed)].ljust(len(_TAGLINE))
                _put(scr, top + len(_LOGO) + 1, (w - len(_TAGLINE)) // 2, line, head)
            scr.refresh()
            time.sleep(0.05)

        if key != curses.KEY_RESIZE:  # any other key quits
            return


def run() -> None:
    curses.wrapper(_rain)
