"""Historical cash-flow normalisation and monthly aggregation.

The raw transaction rows are never rewritten. Imported rows are normalised
once, then keyword rules assign a direction/category/investment bucket; the
user can override any row. Summary values are in today's purchasing power
(deflated with the same 2% inflation assumption used elsewhere).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np

from ..models import (
    CashflowAssumptionPreview,
    CashflowBalance,
    CashflowBalancePoint,
    CashflowBucketFlow,
    CashflowCategoryTotal,
    CashflowDirection,
    CashflowMonth,
    CashflowRule,
    CashflowRuleInput,
    CashflowSummary,
    CashflowTransaction,
    InvestmentAction,
    InvestmentBucket,
)

INFLATION = 0.02
BUCKET_LABELS: dict[str, str] = {
    "cash": "现金/货币",
    "a_share": "A股基金",
    "overseas": "海外基金",
    "gold": "黄金",
    "bond": "债券",
    "other": "其他",
}

# High priority first. Patterns are matched case-insensitively against the
# selected field (counterparty + description + raw category by default).
DEFAULT_RULES: list[dict[str, Any]] = [
    # Investment sells need to win over the generic "基金" rule.
    {"priority": 130, "pattern": "赎回", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "other", "investment_action": "sell"},
    {"priority": 129, "pattern": "卖出", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "other", "investment_action": "sell"},
    {"priority": 128, "pattern": "黄金", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "gold", "investment_action": "buy"},
    {"priority": 127, "pattern": "积存金", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "gold", "investment_action": "buy"},
    {"priority": 126, "pattern": "债", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "bond", "investment_action": "buy"},
    {"priority": 125, "pattern": "纳斯达克", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "overseas", "investment_action": "buy"},
    {"priority": 124, "pattern": "标普", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "overseas", "investment_action": "buy"},
    {"priority": 123, "pattern": "QDII", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "overseas", "investment_action": "buy"},
    {"priority": 122, "pattern": "海外", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "overseas", "investment_action": "buy"},
    {"priority": 121, "pattern": "余额宝", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 120, "pattern": "零钱通", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 119, "pattern": "基金", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "a_share", "investment_action": "buy"},
    {"priority": 118, "pattern": "股票", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "a_share", "investment_action": "buy"},
    {"priority": 117, "pattern": "证券", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "a_share", "investment_action": "buy"},
    {"priority": 116, "pattern": "定投", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "a_share", "investment_action": "buy"},
    {"priority": 115, "pattern": "理财", "match_field": "any", "direction": "investment", "category": "投资", "bucket": "other", "investment_action": "buy"},
    # Internal transfers and refunds are not income or consumption.
    {"priority": 100, "pattern": "信用卡还款", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 99, "pattern": "还款", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 98, "pattern": "转账", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 97, "pattern": "提现", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 96, "pattern": "充值", "match_field": "any", "direction": "transfer", "category": "转账"},
    {"priority": 95, "pattern": "退款", "match_field": "any", "direction": "ignore", "category": "退款"},
    {"priority": 94, "pattern": "报销", "match_field": "any", "direction": "ignore", "category": "报销"},
    # Income.
    {"priority": 92, "pattern": "微信红包", "match_field": "any", "direction": "income", "category": "红包"},
    {"priority": 90, "pattern": "工资", "match_field": "any", "direction": "income", "category": "工资"},
    {"priority": 89, "pattern": "薪资", "match_field": "any", "direction": "income", "category": "工资"},
    {"priority": 88, "pattern": "奖金", "match_field": "any", "direction": "income", "category": "奖金"},
    {"priority": 87, "pattern": "年终奖", "match_field": "any", "direction": "income", "category": "奖金"},
    {"priority": 86, "pattern": "利息", "match_field": "any", "direction": "income", "category": "利息"},
    {"priority": 85, "pattern": "分红", "match_field": "any", "direction": "income", "category": "分红"},
    {"priority": 84, "pattern": "股息", "match_field": "any", "direction": "income", "category": "分红"},
    {"priority": 83, "pattern": "租金", "match_field": "any", "direction": "income", "category": "租金"},
    # Expense categories.
    {"priority": 80, "pattern": "餐饮", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 79, "pattern": "外卖", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 78, "pattern": "美团", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 77, "pattern": "饿了么", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "蜜雪冰城", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "奶茶", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "茶饮", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "coffee", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "粥", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "小吃", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "面", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "饭", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "饼", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "豆花", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "云吞", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "卤", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "茶", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "粉", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "烘焙", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "面包", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "麻糍", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "牛杂", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "鸡翅", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "汉堡", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "美食", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "喜茶", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 52, "pattern": "智能货柜", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 52, "pattern": "腾讯", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 52, "pattern": "Valve", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 52, "pattern": "加速器", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 76, "pattern": "糖水", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 76, "pattern": "水果", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 73, "pattern": "深圳通", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 73, "pattern": "交通e码", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 53, "pattern": "miHoYo", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 76, "pattern": "咖啡", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 75, "pattern": "餐厅", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 75, "pattern": "饭店", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 75, "pattern": "食堂", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 74, "pattern": "餐", "match_field": "any", "direction": "expense", "category": "餐饮"},
    {"priority": 75, "pattern": "地铁", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 74, "pattern": "公交", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 73, "pattern": "打车", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 72, "pattern": "滴滴", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 71, "pattern": "加油", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 70, "pattern": "停车", "match_field": "any", "direction": "expense", "category": "交通"},
    {"priority": 69, "pattern": "房租", "match_field": "any", "direction": "expense", "category": "居住"},
    {"priority": 68, "pattern": "物业", "match_field": "any", "direction": "expense", "category": "居住"},
    {"priority": 67, "pattern": "水电", "match_field": "any", "direction": "expense", "category": "居住"},
    {"priority": 66, "pattern": "燃气", "match_field": "any", "direction": "expense", "category": "居住"},
    {"priority": 65, "pattern": "宽带", "match_field": "any", "direction": "expense", "category": "通讯"},
    {"priority": 64, "pattern": "话费", "match_field": "any", "direction": "expense", "category": "通讯"},
    {"priority": 63, "pattern": "医院", "match_field": "any", "direction": "expense", "category": "医疗"},
    {"priority": 62, "pattern": "药店", "match_field": "any", "direction": "expense", "category": "医疗"},
    {"priority": 61, "pattern": "医疗", "match_field": "any", "direction": "expense", "category": "医疗"},
    {"priority": 60, "pattern": "学费", "match_field": "any", "direction": "expense", "category": "教育"},
    {"priority": 59, "pattern": "培训", "match_field": "any", "direction": "expense", "category": "教育"},
    {"priority": 58, "pattern": "教育", "match_field": "any", "direction": "expense", "category": "教育"},
    {"priority": 57, "pattern": "电影", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 56, "pattern": "游戏", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 55, "pattern": "旅游", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 54, "pattern": "酒店", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 53, "pattern": "健身", "match_field": "any", "direction": "expense", "category": "娱乐"},
    {"priority": 52, "pattern": "保险", "match_field": "any", "direction": "expense", "category": "保险"},
    {"priority": 51, "pattern": "淘宝", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 50, "pattern": "京东", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 49, "pattern": "拼多多", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 48, "pattern": "超市", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 47, "pattern": "便利店", "match_field": "any", "direction": "expense", "category": "购物"},
    {"priority": 46, "pattern": "购物", "match_field": "any", "direction": "expense", "category": "购物"},
]


def default_rules() -> list[CashflowRuleInput]:
    return [CashflowRuleInput(**item) for item in DEFAULT_RULES]


def _match_text(transaction: CashflowTransaction, field: str) -> str:
    if field == "counterparty":
        return transaction.counterparty
    if field == "description":
        return transaction.description
    if field == "category":
        return transaction.raw_category
    return " ".join(
        [
            transaction.counterparty,
            transaction.description,
            transaction.raw_category,
        ]
    )


def apply_rules(
    transaction: CashflowTransaction, rules: list[CashflowRule]
) -> CashflowTransaction:
    """Apply the first matching enabled rule; manual overrides are left alone."""
    if transaction.category_source == "manual":
        return transaction
    ordered = sorted(
        (rule for rule in rules if rule.enabled),
        key=lambda rule: rule.priority,
        reverse=True,
    )
    for rule in ordered:
        text = _match_text(transaction, rule.match_field).lower()
        if rule.pattern.lower() not in text:
            continue
        if rule.direction in ("income", "expense"):
            # The statement's 收/支 column is more reliable than a merchant
            # keyword. Income/expense rules only label rows already on the
            # same side; they never flip a row or relabel a transfer/investment.
            if transaction.direction != rule.direction:
                continue
        elif rule.direction is not None:
            # Transfer and investment rules intentionally reclassify a row
            # even when the platform labels it as 收入/支出.
            transaction.direction = rule.direction
        if rule.category:
            transaction.category = rule.category
        if rule.bucket is not None:
            transaction.bucket = rule.bucket
        if rule.investment_action is not None:
            transaction.investment_action = rule.investment_action
        return transaction
    return transaction


def finalize_classification(transaction: CashflowTransaction) -> CashflowTransaction:
    """Fill gaps after rule matching and keep direction/bucket consistent."""
    if transaction.direction == "income":
        transaction.category = transaction.category or "其他收入"
        transaction.bucket = None
        transaction.investment_action = None
    elif transaction.direction == "expense":
        transaction.category = transaction.category or "其他支出"
        transaction.bucket = None
        transaction.investment_action = None
    elif transaction.direction == "investment":
        transaction.category = transaction.category or "投资"
        transaction.bucket = transaction.bucket or "other"
        transaction.investment_action = transaction.investment_action or "buy"
    elif transaction.direction == "transfer":
        transaction.category = transaction.category or "转账"
        transaction.bucket = None
        transaction.investment_action = None
    else:
        transaction.direction = "ignore"
        transaction.category = transaction.category or "不计收支"
        transaction.bucket = None
        transaction.investment_action = None
    return transaction


def _deflate(amount: float, day: date, latest: date, inflation: float) -> float:
    years = max(0.0, (latest - day).days / 365.25)
    return amount / ((1.0 + inflation) ** years)


def summarize(
    transactions: list[CashflowTransaction],
    balances: list[CashflowBalance],
    *,
    inflation: float = INFLATION,
) -> CashflowSummary:
    if not transactions and not balances:
        return CashflowSummary(
            inflation_assumption=inflation,
            warnings=["还没有导入交易或资产余额。"],
        )
    latest = max(
        [tx.date for tx in transactions] + [item.date for item in balances]
    )
    month_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "income": 0.0,
            "expense": 0.0,
            "one_off_income": 0.0,
            "one_off_expense": 0.0,
            "investment_buy": 0.0,
            "investment_sell": 0.0,
            "bucket_buy": defaultdict(float),
            "transaction_count": 0,
            "uncategorized_count": 0,
        }
    )
    income_categories: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"amount": 0.0, "one_off": 0.0, "count": 0}
    )
    expense_categories: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"amount": 0.0, "one_off": 0.0, "count": 0}
    )
    bucket_flows: dict[str, dict[str, float]] = defaultdict(
        lambda: {"buy": 0.0, "sell": 0.0}
    )
    for tx in transactions:
        month = tx.date.strftime("%Y-%m")
        amount = _deflate(float(tx.amount), tx.date, latest, inflation)
        row = month_data[month]
        row["transaction_count"] += 1
        if tx.direction == "income":
            row["income"] += amount
            if tx.is_one_off:
                row["one_off_income"] += amount
            key = tx.category or "其他收入"
            income_categories[key]["amount"] += amount
            income_categories[key]["count"] += 1
            if tx.is_one_off:
                income_categories[key]["one_off"] += amount
            if key in ("其他收入", "未分类"):
                row["uncategorized_count"] += 1
        elif tx.direction == "expense":
            row["expense"] += amount
            if tx.is_one_off:
                row["one_off_expense"] += amount
            key = tx.category or "其他支出"
            expense_categories[key]["amount"] += amount
            expense_categories[key]["count"] += 1
            if tx.is_one_off:
                expense_categories[key]["one_off"] += amount
            if key in ("其他支出", "未分类"):
                row["uncategorized_count"] += 1
        elif tx.direction == "investment":
            bucket = tx.bucket or "other"
            if tx.investment_action == "sell":
                row["investment_sell"] += amount
                bucket_flows[bucket]["sell"] += amount
            else:
                row["investment_buy"] += amount
                row["bucket_buy"][bucket] += amount
                bucket_flows[bucket]["buy"] += amount

    months: list[CashflowMonth] = []
    for month in sorted(month_data):
        row = month_data[month]
        income = row["income"]
        expense = row["expense"]
        net = income - expense
        income_recurring = income - row["one_off_income"]
        expense_recurring = expense - row["one_off_expense"]
        net_recurring = income_recurring - expense_recurring
        months.append(
            CashflowMonth(
                month=month,
                income=income,
                expense=expense,
                net_savings=net,
                savings_rate=(net / income) if income > 0 else None,
                income_recurring=income_recurring,
                expense_recurring=expense_recurring,
                net_savings_recurring=net_recurring,
                savings_rate_recurring=(
                    net_recurring / income_recurring
                    if income_recurring > 0
                    else None
                ),
                investment_buy=row["investment_buy"],
                investment_sell=row["investment_sell"],
                investment_net=row["investment_buy"] - row["investment_sell"],
                bucket_buy=dict(row["bucket_buy"]),
                one_off_income=row["one_off_income"],
                one_off_expense=row["one_off_expense"],
                transaction_count=row["transaction_count"],
                uncategorized_count=row["uncategorized_count"],
            )
        )

    def category_list(
        data: dict[str, dict[str, Any]], total: float
    ) -> list[CashflowCategoryTotal]:
        return [
            CashflowCategoryTotal(
                category=key,
                amount=value["amount"],
                one_off_amount=value["one_off"],
                share=(value["amount"] / total) if total > 0 else 0.0,
                count=value["count"],
            )
            for key, value in sorted(
                data.items(), key=lambda item: item[1]["amount"], reverse=True
            )
        ]

    total_income = sum(month.income for month in months)
    total_expense = sum(month.expense for month in months)
    total_net = total_income - total_expense
    total_buy = sum(value["buy"] for value in bucket_flows.values())
    investment_buckets = [
        CashflowBucketFlow(
            bucket=bucket,
            buy=value["buy"],
            sell=value["sell"],
            net=value["buy"] - value["sell"],
            buy_share=(value["buy"] / total_buy) if total_buy > 0 else 0.0,
        )
        for bucket, value in sorted(
            bucket_flows.items(), key=lambda item: item[1]["buy"], reverse=True
        )
    ]

    balance_by_month: dict[str, dict[str, float]] = defaultdict(dict)
    for item in sorted(balances, key=lambda item: item.date):
        month = item.date.strftime("%Y-%m")
        balance_by_month[month][item.bucket] = _deflate(
            float(item.balance), item.date, latest, inflation
        )
    balance_points: list[CashflowBalancePoint] = []
    for month in sorted(balance_by_month):
        values = balance_by_month[month]
        balance_points.append(
            CashflowBalancePoint(
                month=month,
                balances=values,
                total=sum(values.values()),
            )
        )
    latest_balances = balance_points[-1].balances if balance_points else {}

    uncategorized = sum(month.uncategorized_count for month in months)
    warnings: list[str] = []
    if not transactions:
        warnings.append("还没有导入交易流水。")
    if uncategorized:
        warnings.append(f"有 {uncategorized} 笔收入/支出仍归在“其他”类别，建议手动修正。")
    if not balances:
        warnings.append("还没有资产余额快照，资产配置图会为空。")
    if any(month.savings_rate is not None and month.savings_rate < 0 for month in months):
        warnings.append("存在支出大于收入的月份；储蓄率为负是正常提示，不是错误。")
    if len(months) < 6:
        warnings.append("历史月份少于 6 个月，回填假设前建议先补足数据。")
    if total_income > 0 and total_expense > total_income * 2:
        warnings.append(
            "收入总额明显低于支出，可能只导入了支出账户；"
            "储蓄率和回填假设需补导工资卡/主账户后再看。"
        )

    return CashflowSummary(
        from_date=min([tx.date for tx in transactions], default=None),
        to_date=max([tx.date for tx in transactions], default=None),
        latest_month=max(month_data) if month_data else None,
        inflation_assumption=inflation,
        months=months,
        income_categories=category_list(income_categories, total_income),
        expense_categories=category_list(expense_categories, total_expense),
        investment_buckets=investment_buckets,
        balances=balance_points,
        latest_balances=latest_balances,
        total_income=total_income,
        total_expense=total_expense,
        total_net_savings=total_net,
        savings_rate=(total_net / total_income) if total_income > 0 else None,
        transaction_count=len(transactions),
        uncategorized_count=uncategorized,
        warnings=warnings,
    )


def assumption_preview(
    transactions: list[CashflowTransaction],
    summary: CashflowSummary,
    *,
    window_months: int = 12,
) -> CashflowAssumptionPreview:
    if not summary.months:
        raise ValueError("没有可用的月度收支数据")
    window = summary.months[-window_months:]
    with_data = [month for month in window if month.transaction_count > 0]
    if not with_data:
        raise ValueError("所选窗口没有交易数据")
    incomes = np.array([month.income_recurring for month in with_data], dtype=float)
    expenses = np.array([month.expense_recurring for month in with_data], dtype=float)
    rates = np.array(
        [
            month.savings_rate_recurring
            for month in with_data
            if month.savings_rate_recurring is not None
        ],
        dtype=float,
    )
    monthly_income = float(np.median(incomes))
    monthly_expense = float(np.median(expenses))
    savings_rate = float(np.median(rates)) if rates.size else None
    excluded = sum(
        1
        for tx in transactions
        if tx.is_one_off
        and with_data[0].month <= tx.date.strftime("%Y-%m") <= with_data[-1].month
    )
    warnings: list[str] = []
    if len(with_data) < 6:
        warnings.append("可用月份少于 6 个月，中位数可能不稳定。")
    if monthly_income <= 0:
        warnings.append("月收入中位数为 0，无法得到可靠的储蓄率。")
    if monthly_expense <= 0:
        warnings.append("月支出中位数为 0，请确认是否漏导出了支出。")
    if monthly_income > 0 and monthly_expense > monthly_income * 2:
        warnings.append(
            "月收入中位数明显低于月支出，可能只导入了支出账户；"
            "建议补导工资卡/主账户后再回填。"
        )
    if excluded:
        warnings.append(f"已排除 {excluded} 笔标记为一次性的交易。")
    return CashflowAssumptionPreview(
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        savings_rate=savings_rate,
        months_used=len(with_data),
        window_start=with_data[0].month,
        window_end=with_data[-1].month,
        excluded_one_off_count=excluded,
        inflation_assumption=summary.inflation_assumption,
        warnings=warnings,
    )
