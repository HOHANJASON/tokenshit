"""The security core: every cross-role attempt is denied at the data layer."""
import pytest

from nextoken_copilot import data_access as da
from nextoken_copilot.principal import Principal, Role

CLIENT = Principal(role=Role.CLIENT, customer_id=1)
SUPPORT = Principal(role=Role.SUPPORT)
ADMIN = Principal(role=Role.ADMIN)


def test_client_sees_only_own_and_no_money_internals():
    s = da.get_my_usage_summary(CLIENT)
    assert s["customer_id"] == 1
    assert "upstream_cost" not in str(s)
    assert "margin" not in str(s)


def test_client_blocked_from_admin_finance():
    with pytest.raises(da.AccessDenied):
        da.get_platform_revenue(CLIENT)


def test_client_blocked_from_other_customers():
    with pytest.raises(da.AccessDenied):
        da.get_customer_usage_summary(CLIENT, 2)


def test_support_blocked_from_finance():
    with pytest.raises(da.AccessDenied):
        da.get_margin_by_model(SUPPORT)


def test_support_can_read_cross_customer():
    assert da.get_customer_usage_summary(SUPPORT, 2)["customer_id"] == 2


def test_admin_margin_is_revenue_minus_cost():
    r = da.get_platform_revenue(ADMIN)
    assert r["gross_margin"] == round(r["revenue"] - r["upstream_cost"], 6)


def test_client_principal_requires_customer_id():
    with pytest.raises(ValueError):
        Principal(role=Role.CLIENT)
