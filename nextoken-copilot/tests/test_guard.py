"""Output guardrail: the final safety net catches leaked fields in prose."""
from nextoken_copilot.guard import enforce
from nextoken_copilot.principal import Principal, Role


def test_client_answer_with_margin_is_refused():
    ans = 'Here you go: {"gross_margin": 4.4, "upstream_cost": 2.0}'
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "gross_margin" in findings and "upstream_cost" in findings
    assert "gross_margin" not in safe and "can only share" in safe.lower()


def test_admin_answer_with_margin_is_allowed():
    ans = "Revenue 9.1, gross_margin 4.4, margin_pct 48"
    safe, findings = enforce(Principal(role=Role.ADMIN), ans)
    assert findings == [] and safe == ans


def test_raw_key_field_blocked_for_every_role():
    for p in (Principal(role=Role.CLIENT, customer_id=1), Principal(role=Role.SUPPORT), Principal(role=Role.ADMIN)):
        _, findings = enforce(p, "here is api_key_encrypted=secret")
        assert "api_key_encrypted" in findings
