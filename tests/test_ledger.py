import json

from research.ledger import ExperimentLedger


def test_ledger_appends_success_and_failure_experiments(tmp_path):
    ledger = ExperimentLedger(tmp_path / "experiments.jsonl")

    ledger.append(
        {
            "experiment_id": "e1",
            "hypothesis_id": "h1",
            "status": "FAIL",
            "metrics": {"total_return": -0.1},
            "critic_findings": ["low return"],
        }
    )
    ledger.append(
        {
            "experiment_id": "e2",
            "hypothesis_id": "h2",
            "status": "PASS",
            "metrics": {"total_return": 0.1},
            "critic_findings": [],
        }
    )

    rows = ledger.read_all()
    assert [row["experiment_id"] for row in rows] == ["e1", "e2"]

    raw_lines = (tmp_path / "experiments.jsonl").read_text().splitlines()
    assert json.loads(raw_lines[0])["status"] == "FAIL"
