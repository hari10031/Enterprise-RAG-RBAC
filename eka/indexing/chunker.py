"""Structure-aware chunking (D7): block boundaries first, then sentences; table headers repeat in every table chunk."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from eka.ingestion.parsers import Block

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass
class Chunk:
    text: str  # shown to users
    heading_path: str
    page: int | None
    token_count: int  # of embed_text

    @property
    def embed_text(self) -> str:
        return f"{self.heading_path}\n{self.text}" if self.heading_path else self.text


@dataclass
class _Unit:
    text: str
    tokens: int
    page: int | None
    carried: bool = False  # overlap copied from the previous chunk


class Chunker:
    def __init__(self, count_tokens: Callable[[str], int], target: int = 400, maximum: int = 480, overlap: int = 60):
        self.count = count_tokens
        self.target, self.maximum, self.overlap = target, maximum, overlap

    def chunk(self, blocks: list[Block]) -> list[Chunk]:
        self.out: list[Chunk] = []
        self.buf: list[_Unit] = []
        self.headings: list[tuple[int, str]] = []
        for b in blocks:
            if b.kind == "heading":
                self._flush()
                self.headings = [h for h in self.headings if h[0] < b.level] + [(b.level, b.text)]
            elif b.kind == "table":
                self._flush()
                self._table(b)
            elif b.kind == "code":
                self._flush()
                self._code(b)
            else:
                self._prose(b)
        self._flush()
        return self.out

    # Budgets exclude the heading prefix, which counts toward the model's hard maximum.
    @property
    def _path(self) -> str:
        return " > ".join(h[1] for h in self.headings)

    def _budgets(self) -> tuple[int, int]:
        prefix = self.count(self._path) + 1 if self._path else 0
        room = max(self.maximum - prefix, 32)
        return min(self.target, room), room

    def _emit(self, text: str, page: int | None) -> None:
        path = self._path
        c = Chunk(text=text, heading_path=path, page=page, token_count=0)
        c.token_count = self.count(c.embed_text)
        self.out.append(c)

    def _prose(self, b: Block) -> None:
        target, room = self._budgets()
        for piece in self._pieces(b.text, room):
            u = _Unit(piece, self.count(piece), b.page)
            if self.buf and sum(x.tokens for x in self.buf) + u.tokens > target:
                self._flush(keep_overlap=True)
                if sum(x.tokens for x in self.buf) + u.tokens > room:
                    self.buf = []  # overlap would push this chunk past the hard maximum
            self.buf.append(u)

    def _pieces(self, text: str, room: int) -> list[str]:
        """Whole paragraph if it fits, else sentences; a sentence over the room is split by words."""
        if self.count(text) <= room:
            return [text]
        out: list[str] = []
        for s in _SENTENCE_END.split(text):
            out += [s] if self.count(s) <= room else self._hard_split(s, room)
        return out

    def _hard_split(self, text: str, room: int, sep: str = " ") -> list[str]:
        parts: list[str] = []
        cur: list[str] = []
        cur_tokens = 0
        for w in text.split(sep):
            t = self.count(w) + 1
            if cur and cur_tokens + t > room:
                parts.append(sep.join(cur))
                cur, cur_tokens = [], 0
            cur.append(w)
            cur_tokens += t
        if cur:
            parts.append(sep.join(cur))
        return parts

    def _flush(self, keep_overlap: bool = False) -> None:
        if all(u.carried for u in self.buf):
            self.buf = []  # nothing new since the last chunk
            return
        self._emit(" ".join(u.text for u in self.buf), self.buf[0].page)
        tail: list[_Unit] = []
        if keep_overlap:
            for u in reversed(self.buf[1:]):  # never carry the whole buffer over
                if sum(x.tokens for x in tail) + u.tokens > self.overlap:
                    break
                tail.insert(0, _Unit(u.text, u.tokens, u.page, carried=True))
        self.buf = tail

    def _table(self, b: Block) -> None:
        target, room = self._budgets()
        render = [" | ".join(r) for r in b.rows]
        header, body = render[0], render[1:] or [""]
        head_tokens = self.count(header) + 1
        rows_budget = max(target - head_tokens, 16)
        group: list[str] = []
        used = 0
        for row in body:
            for part in [row] if self.count(row) <= rows_budget else self._hard_split(row, rows_budget):
                t = self.count(part) + 1
                if group and used + t > rows_budget:
                    self._emit("\n".join([header, *group]), b.page)
                    group, used = [], 0
                group.append(part)
                used += t
        self._emit("\n".join([header, *group]).rstrip(), b.page)

    def _code(self, b: Block) -> None:
        _, room = self._budgets()
        for part in [b.text] if self.count(b.text) <= room else self._hard_split(b.text, room, sep="\n"):
            self._emit(part, b.page)
