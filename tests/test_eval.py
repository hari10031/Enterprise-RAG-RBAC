from eka.eval import Question, is_relevant, recall_at, reciprocal_rank, summarise, table


def test_ranking_metrics() -> None:
    assert recall_at([False, False, True], 5) == 1.0
    assert recall_at([False] * 5 + [True], 5) == 0.0
    assert reciprocal_rank([False, True], 10) == 0.5
    assert reciprocal_rank([False] * 3, 10) == 0.0


def test_relevance_is_substring_and_case_insensitive() -> None:
    assert is_relevant("Error ERR-4032 means quota", ["err-4032"])
    assert not is_relevant("unrelated", ["err-4032"])


def test_summary_splits_answerable_and_unanswerable() -> None:
    a = Question("1", "q", True, ["x"])
    b = Question("2", "q", True, ["x"])
    n = Question("3", "q", False, [])
    s = summarise([(a, [True], False), (b, [False, True], False), (n, [], True)])
    assert s == {"recall@5": 1.0, "mrr@10": 0.75, "not_found_precision": 1.0}
    assert "| hybrid + re-rank | 1.000 | 0.750 | 1.000 |" in table({"hybrid + re-rank": s})
