"""Agent-native observability: the metrics block exposes per-stage timing and
health counters that a generic APM (which sees one opaque LLM call) cannot."""
import warnings

warnings.filterwarnings("ignore")

from nextoken_copilot.agents import ask  # noqa: E402
from nextoken_copilot.principal import Principal, Role  # noqa: E402

CLIENT = Principal(role=Role.CLIENT, customer_id=1, email="t@local")


def _metrics(question: str) -> dict:
    return ask(CLIENT, question)["metrics"]


def test_stage_timings_present_and_cover_the_graph():
    m = _metrics("what is my balance")
    stage = m["stage_ms"]
    # every request runs orchestrator -> supervisor -> worker -> aggregator
    for node in ("orchestrator", "supervisor", "worker", "aggregator"):
        assert node in stage, (node, stage)
        assert stage[node] >= 0
    # per-stage times are a decomposition of the whole, not larger than it
    assert sum(stage.values()) <= m["latency_ms"] + 50


def test_health_counters_are_sane_on_a_clean_run():
    m = _metrics("what is my balance")
    assert m["plan_len"] >= 1
    assert m["route_fallbacks"] == 0          # sandbox router always resolves
    assert m["empty_worker_steps"] == 0       # the bug this counter watches for
    assert m["tool_calls"] >= 1               # a data question must hit a tool
    assert m["evidence_chars"] > 0
    assert "router_model" in m


def test_multistep_question_reports_more_than_one_step():
    m = _metrics("how much did I spend this month and on which models")
    assert m["plan_len"] >= 2
    assert m["steps"] == m["plan_len"]
    assert len(m["workers"]) == m["steps"]


def test_context_chars_tracks_conversation_size():
    # no context on a fresh call
    assert _metrics("what is my balance")["context_chars"] == 0
