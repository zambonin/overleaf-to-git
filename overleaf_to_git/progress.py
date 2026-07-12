# -*- coding: utf-8 -*-
# pylint: disable=C0209
from __future__ import annotations

import shutil
import sys

_CLEAR = "\033[2K"
_UP = "\033[{}A"
_BAR_FULL = "█"
_BAR_EMPTY = "░"
_LABEL = 9


def bar(done: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return _BAR_EMPTY * width
    filled = min(width, int(width * done / total))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


class Status:
    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._drawn = 0

    @property
    def interactive(self) -> bool:
        return bool(getattr(self._stream, "isatty", bool)())

    def render(self, lines: list[str]) -> None:
        if not self.interactive:
            return
        width = shutil.get_terminal_size().columns - 1
        out = [_UP.format(self._drawn)] if self._drawn else []
        out += ["\r" + _CLEAR + line[:width] + "\n" for line in lines]
        stale = max(self._drawn - len(lines), 0)
        if stale:
            out += ["\r" + _CLEAR + "\n"] * stale + [_UP.format(stale)]
        self._stream.write("".join(out))
        self._stream.flush()
        self._drawn = len(lines)

    def update(self, text: str) -> None:
        self.render([text])

    def clear(self) -> None:
        if self._drawn and self.interactive:
            self._stream.write(
                _UP.format(self._drawn)
                + ("\r" + _CLEAR + "\n") * self._drawn
                + _UP.format(self._drawn)
            )
            self._stream.flush()
        self._drawn = 0

    def note(self, text: str) -> None:
        self.clear()
        print(text, file=self._stream, flush=True)

    def result(self, text: str) -> None:
        self.clear()
        print(text, flush=True)


class Progress:
    def __init__(self, total: int, status: Status | None = None) -> None:
        self._status = status if status is not None else STATUS
        self._total = total
        self._index = 0
        self._name = ""
        self._phase = ""
        self._done = 0
        self._units = 0

    def project(self, index: int, name: str) -> None:
        self._index, self._name = index, name
        self._phase, self._done, self._units = "", 0, 0
        self._draw()

    def step(self, phase: str, done: int = 0, units: int = 0) -> None:
        self._phase, self._done, self._units = phase, done, units
        self._draw()

    def _count(self, done: int, total: int, width: int) -> str:
        return "{:>{w}}/{:<{w}}".format(done, total, w=width)

    def _draw(self) -> None:
        width = max(len(str(self._total)), len(str(self._units)))
        lines = [
            "{:<{p}} {}".format("current:", self._name, p=_LABEL),
            "{:<{p}} {} {}".format(
                "projects",
                bar(max(self._index - 1, 0), self._total),
                self._count(self._index, self._total, width),
                p=_LABEL,
            ),
        ]
        if self._phase:
            lines.append(
                "{:<{p}} {} {}".format(
                    self._phase[:_LABEL],
                    bar(self._done, self._units),
                    self._count(self._done, self._units, width) if self._units else "",
                    p=_LABEL,
                )
            )
        self._status.render(lines)

    def done(self) -> None:
        self._status.clear()


STATUS = Status()
