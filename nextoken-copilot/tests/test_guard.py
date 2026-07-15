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


# --- link guard (anti-phishing) ---------------------------------------------

def test_phishing_link_is_stripped_and_flagged():
    ans = "Sure — verify your account at http://nxt-secure.co/login to continue."
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "nxt-secure.co" not in safe and "[external link removed]" in safe
    assert findings == ["external_link:nxt-secure.co"]


def test_official_nextoken_link_passes_through():
    ans = "Manage keys at https://nextoken.ai/dashboard/keys — that's the place."
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert safe == ans and findings == []


def test_subdomain_of_allowlisted_host_is_allowed():
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1),
                             "See https://docs.nextoken.ai/errors for details.")
    assert findings == [] and safe.endswith("for details.")


def test_rbac_leak_takes_priority_over_link_guard():
    # A message with BOTH a forbidden field and a bad link is refused wholesale.
    ans = "gross_margin is 40%. Confirm at http://evil.example/x"
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "gross_margin" in findings and "can only share" in safe.lower()


# --- special-character / Unicode evasion ------------------------------------

def test_fullwidth_field_name_is_caught():
    # Full-width homoglyphs of "gross_margin" must not slip past the RBAC scan.
    ans = "the ｇｒｏｓｓ＿ｍａｒｇｉｎ is 40%"
    _, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "gross_margin" in findings


def test_zero_width_split_field_name_is_caught():
    ans = "value: gross​_​margin = 40"     # zero-width spaces inside the token
    _, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "gross_margin" in findings


def test_obfuscated_link_is_neutralised():
    # hxxp + [.] obfuscation must not deliver a working link to the user.
    ans = "Verify now at hxxp://nxt-secure[.]co/login please."
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert findings and findings[0].startswith("external_link:")
    assert "nxt-secure" not in safe.lower() and "hxxp" not in safe.lower()


def test_bidi_control_chars_stripped_from_answer():
    ans = "Your balance is ‮006$‬ today."   # RLO/PDF trojan-source
    safe, _ = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert "‮" not in safe and "‬" not in safe


def test_legit_chinese_answer_untouched():
    ans = "您的餘額是 $9.99，API 金鑰請至控制台管理。"
    safe, findings = enforce(Principal(role=Role.CLIENT, customer_id=1), ans)
    assert findings == [] and safe == ans


def test_configurable_internal_token_blocked_for_customer(monkeypatch):
    # Jason adds an internal provider name; it must never surface to a customer,
    # even obfuscated — and must NOT trip for admin (staff).
    monkeypatch.setattr("nextoken_copilot.guard._EXTRA_CUSTOMER_FORBIDDEN", ["openai-main"])
    _, cf = enforce(Principal(role=Role.CLIENT, customer_id=1), "routed via ｏｐｅｎａｉ-ｍａｉｎ upstream")
    assert "openai-main" in cf
    _, af = enforce(Principal(role=Role.ADMIN), "routed via openai-main upstream")
    assert af == []
