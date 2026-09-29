from eka.indexing.chunker import Chunker
from eka.ingestion.parsers import Block


def words(text: str) -> int:
    return len(text.split())


def make(target: int = 40, maximum: int = 50, overlap: int = 8) -> Chunker:
    return Chunker(words, target, maximum, overlap)


def sentence(i: int) -> str:
    return f"Sentence number {i} has exactly eight words total."


def test_heading_path_and_limits() -> None:
    blocks = [
        Block("heading", "Leave Policy", level=1),
        Block("heading", "Sick leave", level=2),
        Block("heading", "Eligibility", level=3),
        Block("paragraph", " ".join(sentence(i) for i in range(30)), page=2),
    ]
    chunks = make().chunk(blocks)
    assert len(chunks) > 3
    for c in chunks:
        assert c.heading_path == "Leave Policy > Sick leave > Eligibility"
        assert c.token_count <= 50
        assert "Leave Policy" not in c.text  # the path is embedded, not shown
        assert c.page == 2


def test_overlap_carries_tail_sentence() -> None:
    chunks = make().chunk([Block("paragraph", " ".join(sentence(i) for i in range(12)))])
    first_tail = chunks[0].text.split(". ")[-1]
    assert first_tail.rstrip(".") in chunks[1].text


def test_heading_resets_deeper_levels() -> None:
    blocks = [
        Block("heading", "A", level=1),
        Block("heading", "B", level=2),
        Block("paragraph", "one"),
        Block("heading", "C", level=2),
        Block("paragraph", "two"),
    ]
    assert [c.heading_path for c in make().chunk(blocks)] == ["A > B", "A > C"]


def test_table_header_repeats() -> None:
    rows = [["Code", "Meaning"]] + [[f"ERR-{i}", f"error number {i} happened here"] for i in range(40)]
    chunks = make().chunk([Block("table", rows=rows)])
    assert len(chunks) > 1
    assert all(c.text.startswith("Code | Meaning\n") for c in chunks)
    body = "\n".join(c.text for c in chunks)
    assert all(f"ERR-{i} |" in body for i in range(40))


def test_giant_sentence_is_hard_split() -> None:
    chunks = make().chunk([Block("paragraph", "word " * 300)])
    assert all(c.token_count <= 50 for c in chunks)
    assert sum(c.text.count("word") for c in chunks) >= 300


def test_no_chunk_of_pure_overlap_before_heading() -> None:
    blocks = [
        Block("paragraph", " ".join(sentence(i) for i in range(10))),
        Block("heading", "Next", level=1),
        Block("paragraph", "fresh text"),
    ]
    chunks = make().chunk(blocks)
    assert chunks[-1].text == "fresh text"
    assert len({c.text for c in chunks}) == len(chunks)
