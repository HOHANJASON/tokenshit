"""Planner worker: deterministic plan math + offline pipeline + RBAC scoping."""
import asyncio
import json
import warnings

warnings.filterwarnings("ignore")

from nextoken_copilot.agents import ask  # noqa: E402
from nextoken_copilot.planner import compute_plan, load_planner_tools  # noqa: E402
from nextoken_copilot.principal import Principal, Role  # noqa: E402

CLIENT = Principal(role=Role.CLIENT, customer_id=1, email="t@local")


def _rows(n=10, model="nxt-a", charge=0.01, day_span=5):
    return [{"model": model, "charge": charge, "input_tokens": 100, "output_tokens": 50,
             "time": f"2026-07-{10 + i % day_span:02d}T12:00:00"} for i in range(n)]


def test_compute_plan_math():
    plan = compute_plan(_rows(n=10, charge=0.01, day_span=5), balance=1.0,
                        horizon_days=30, monthly_budget=0.5)
    assert plan["calls"] == 10
    assert plan["total_spend_usd"] == 0.1
    assert plan["window_days_observed"] == 4.0        # 07-10 .. 07-14
    assert plan["daily_burn_usd"] == 0.025            # 0.1 / 4
    assert plan["projected_spend_usd"] == 0.75        # 0.025 * 30
    assert plan["runway_days_at_current_burn"] == 40.0
    assert plan["projected_monthly_vs_budget_pct"] == 150.0
    assert any("EXCEEDS" in r for r in plan["recommendations"])
    m = plan["per_model"]["nxt-a"]
    assert m["tokens"] == 1500 and m["eff_cost_per_1k_tokens"] == round(0.1 / 1.5, 6)


def test_compute_plan_cheaper_alternative_and_empty():
    pricing = [{"model_name": "nxt-a", "endpoint_type": "chat", "model_ratio": 1.0},
               {"model_name": "nxt-cheap", "endpoint_type": "chat", "model_ratio": 0.25}]
    plan = compute_plan(_rows(), pricing=pricing)
    assert plan["cheapest_alternative"] == {"model": "nxt-cheap", "approx_savings_pct": 75}
    assert "note" in compute_plan([])


def test_planner_tool_is_client_only():
    assert load_planner_tools(CLIENT)[0].name == "build_usage_plan"
    for role in (Role.SUPPORT, Role.ADMIN):
        assert load_planner_tools(Principal(role=role, customer_id=None, email="t@local")) == []


def test_local_plan_tool_grounded_in_seeded_data():
    tool = load_planner_tools(CLIENT)[0]
    plan = json.loads(asyncio.run(tool.coroutine(horizon_days=30, monthly_budget=50.0)))
    assert plan["calls"] > 0 and plan["total_spend_usd"] > 0
    assert plan["balance_usd"] > 0 and plan["recommendations"]


def test_pipeline_routes_plan_question_to_planner():
    res = ask(CLIENT, "suggest an api usage plan for a $50 monthly budget")
    assert "planner" in res["metrics"]["workers"]
    assert "build_usage_plan" in res["metrics"]["tools_called"]


def test_pipeline_planner_absent_for_support():
    res = ask(Principal(role=Role.SUPPORT, customer_id=None, email="t@local"),
              "suggest a usage plan")
    assert "planner" not in res["workers_available"]
