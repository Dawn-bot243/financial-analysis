from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


class LiabilityLike(Protocol):
    balance: float
    annual_rate: float
    remaining_months: int


@dataclass(frozen=True)
class LiabilityAggregate:
    payments: list[float]
    balances: list[float]
    total_interest: float
    total_paid: float


def monthly_payment(balance: float, annual_rate: float, months: int) -> float:
    """Equal-payment (annuity) monthly payment for a fully amortizing loan."""
    if balance <= 0.0 or months <= 0:
        return 0.0
    monthly_rate = annual_rate / 12.0
    if abs(monthly_rate) < 1e-12:
        return balance / months
    return balance * monthly_rate / (1.0 - (1.0 + monthly_rate) ** (-months))


def aggregate_schedule(
    liabilities: Sequence[LiabilityLike], horizon_months: int
) -> LiabilityAggregate:
    """Aggregate monthly payments and end-of-month balances across liabilities.

    The schedule is capped at ``horizon_months``. If a loan extends past the
    horizon, its remaining balance stays in the final balance and is subtracted
    from net worth.
    """
    payments = [0.0] * horizon_months
    balances = [0.0] * horizon_months
    total_interest = 0.0
    total_paid = 0.0

    for liability in liabilities:
        balance = float(liability.balance)
        monthly_rate = float(liability.annual_rate) / 12.0
        months = int(liability.remaining_months)
        if balance <= 0.0 or months <= 0:
            continue

        payment = monthly_payment(balance, liability.annual_rate, months)
        for month_index in range(horizon_months):
            if month_index < months and balance > 1e-9:
                interest = balance * monthly_rate
                if month_index == months - 1:
                    # Final payment absorbs rounding so the balance lands on zero.
                    pay = balance + interest
                    principal = balance
                else:
                    pay = payment
                    principal = pay - interest
                if principal > balance:
                    principal = balance
                    pay = balance + interest
                if principal < 0.0:
                    principal = 0.0
                balance = max(0.0, balance - principal)
                payments[month_index] += pay
                total_interest += interest
                total_paid += pay
            balances[month_index] += balance

    return LiabilityAggregate(
        payments=payments,
        balances=balances,
        total_interest=total_interest,
        total_paid=total_paid,
    )


@dataclass(frozen=True)
class LoanSchedule:
    payments: np.ndarray
    balances_end: np.ndarray
    balances_start: np.ndarray
    interest: np.ndarray
    total_interest: float


def amortization_schedule(
    principal: float,
    annual_rate: float,
    months: int,
    horizon: int,
    origination_month: int,
    first_payment_month: int | None = None,
) -> LoanSchedule:
    """Amortize a loan over the simulation horizon.

    ``origination_month`` and ``first_payment_month`` are 1-based. A purchase
    loan is originated when the asset is bought and its first payment is the
    following month. The engine repays ``balances_start`` when an asset is sold
    and skips that month's scheduled payment.
    """
    payments = np.zeros(horizon, dtype=float)
    balances_end = np.zeros(horizon, dtype=float)
    balances_start = np.zeros(horizon, dtype=float)
    interest = np.zeros(horizon, dtype=float)

    if principal <= 0.0 or months <= 0 or origination_month > horizon:
        return LoanSchedule(payments, balances_end, balances_start, interest, 0.0)

    first_payment = first_payment_month or origination_month
    first_payment = max(first_payment, origination_month)
    monthly_rate = annual_rate / 12.0
    payment = monthly_payment(principal, annual_rate, months)

    # Before the first payment the loan is outstanding at its original principal.
    balances_end[origination_month - 1 : max(origination_month, first_payment) - 1] = principal
    balance = principal
    total_interest = 0.0
    last_payment_month = origination_month - 1

    for index in range(months):
        month = first_payment + index
        if month > horizon:
            break
        interest_paid = balance * monthly_rate
        if index == months - 1:
            pay = balance + interest_paid
            principal_paid = balance
        else:
            pay = payment
            principal_paid = pay - interest_paid
        if principal_paid > balance:
            principal_paid = balance
            pay = balance + interest_paid
        if principal_paid < 0.0:
            principal_paid = 0.0
        balance = max(0.0, balance - principal_paid)
        payments[month - 1] += pay
        interest[month - 1] += interest_paid
        balances_end[month - 1] = balance
        total_interest += interest_paid
        last_payment_month = month

    # If the loan extends past the horizon, carry the remaining balance forward.
    if last_payment_month >= 1 and last_payment_month < horizon and balance > 0.0:
        balances_end[last_payment_month:] = balance

    # Start-of-month balances: what a sale would need to repay.
    balances_start[origination_month - 1] = principal
    for month in range(origination_month + 1, horizon + 1):
        balances_start[month - 1] = balances_end[month - 2]

    return LoanSchedule(
        payments=payments,
        balances_end=balances_end,
        balances_start=balances_start,
        interest=interest,
        total_interest=total_interest,
    )
