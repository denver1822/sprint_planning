import pytest

from app.services.voting import calculate_metrics


def test_metrics_exclude_special_cards_from_numeric_calculations() -> None:
    metrics = calculate_metrics(
        [
            {"card_value": "3", "is_numeric": True},
            {"card_value": "5", "is_numeric": True},
            {"card_value": "?", "is_numeric": False},
        ]
    )

    assert metrics["vote_count"] == 3
    assert metrics["numeric_vote_count"] == 2
    assert metrics["special_vote_count"] == 1
    assert metrics["mean"] == 4
    assert metrics["median"] == 4
    assert metrics["min"] == 3
    assert metrics["max"] == 5
    assert metrics["range"] == 2
    assert metrics["stddev"] == 1
    assert metrics["agreement_index"] == 0.5
    assert metrics["distribution"] == {"3": 1, "5": 1}
    assert metrics["special_cards"] == {"?": 1}


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        (
            [{"card_value": "8", "is_numeric": True}, {"card_value": "8", "is_numeric": True}],
            {"exact_consensus": True, "agreement_index": 1.0, "stddev": 0.0},
        ),
        (
            [{"card_value": "13", "is_numeric": True}],
            {"exact_consensus": False, "agreement_index": None, "stddev": 0.0},
        ),
        (
            [{"card_value": "coffee", "is_numeric": False}],
            {"mean": None, "median": None, "agreement_index": None},
        ),
    ],
)
def test_metric_edge_cases(votes: list[dict[str, object]], expected: dict[str, object]) -> None:
    metrics = calculate_metrics(votes)

    assert {key: metrics[key] for key in expected} == expected
