from dataclasses import dataclass

import pytest

from backend.app.core.liabilities import aggregate_schedule, monthly_payment


@dataclass
class Loan:
    balance: float
    annual_rate: float
    remaining_months: int


def test_monthly_payment_matches_annuity_formula():
    balance = 1_000_000.0
    annual_rate = 0.049
    months = 360
    r = annual_rate / 12.0
    expected = balance * r / (1.0 - (1.0 + r) ** -months)
    assert monthly_payment(balance, annual_rate, months) == pytest.approx(expected)


def test_zero_rate_loan_amortizes_linearly():
    schedule = aggregate_schedule([Loan(120_000.0, 0.0, 12)], 12)
    assert schedule.payments[0] == pytest.approx(10_000.0)
    assert schedule.balances[-1] == pytest.approx(0.0)
    assert schedule.total_interest == pytest.approx(0.0)


def test_loan_fully_amortizes():
    schedule = aggregate_schedule([Loan(1_000_000.0, 0.035, 300)], 300)
    assert schedule.balances[-1] == pytest.approx(0.0, abs=1e-6)
    assert schedule.total_interest > 0.0
    assert all(payment > 0.0 for payment in schedule.payments)


def test_balance_remains_when_horizon_is_shorter_than_loan():
    schedule = aggregate_schedule([Loan(1_000_000.0, 0.035, 300)], 12)
    assert schedule.payments[0] == pytest.approx(
        monthly_payment(1_000_000.0, 0.035, 300)
    )
    assert schedule.balances[-1] > 900_000.0
    assert schedule.balances[-1] < 1_000_000.0


def test_multiple_loans_aggregate():
    schedule = aggregate_schedule(
        [Loan(500_000.0, 0.03, 240), Loan(100_000.0, 0.0, 100)], 24
    )
    assert schedule.payments[0] == pytest.approx(
        monthly_payment(500_000.0, 0.03, 240) + 1_000.0
    )
    assert schedule.balances[-1] > 0.0
