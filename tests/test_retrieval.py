from uuid import uuid4

from eka.retrieval.search import rrf


def test_rrf_rewards_agreement_and_caps_documents() -> None:
    d1, d2 = uuid4(), uuid4()
    a, b, c, d, e = (uuid4() for _ in range(5))
    dense = [(a, d1), (b, d1), (c, d1), (d, d1), (e, d2)]
    keyword = [(e, d2), (a, d1)]
    out = rrf([dense, keyword], k=60, per_document=3, limit=30)
    assert out[0] == a  # ranked high in both lists
    assert out[1] == e
    assert d not in out  # fourth chunk of d1 is capped
    assert len(out) == 4


def test_rrf_limit() -> None:
    ranked = [(uuid4(), uuid4()) for _ in range(50)]
    assert len(rrf([ranked], limit=30)) == 30
