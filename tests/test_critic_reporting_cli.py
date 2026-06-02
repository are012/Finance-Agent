import json
import subprocess
import sys


def test_research_and_final_report_commands_generate_outputs(tmp_path):
    output_dir = tmp_path / "outputs"

    research_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.run_research",
            "--config",
            "configs/example.yaml",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert research_run.returncode == 0, research_run.stderr

    ledger_path = output_dir / "ledger" / "experiments.jsonl"
    assert ledger_path.exists()
    assert ledger_path.read_text().strip()

    report_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.final_report",
            "--ledger",
            str(ledger_path),
            "--output-dir",
            str(output_dir / "reports"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert report_run.returncode == 0, report_run.stderr

    summary = json.loads((output_dir / "reports" / "final_report.json").read_text())
    assert summary["decision"] in {"PASS", "FAIL", "NEEDS_MORE_RESEARCH"}
    assert "selected_experiment" in summary
    assert (output_dir / "reports" / "final_report.md").exists()
