"""End-to-end multi-agent behaviour via the offline suite."""
from eval.suite import run_functional, run_redteam


def test_functional_all_pass():
    failed = [r for r in run_functional() if not r["passed"]]
    assert not failed, failed


def test_redteam_never_leaks():
    leaked = [r for r in run_redteam() if not r["passed"]]
    assert not leaked, leaked
