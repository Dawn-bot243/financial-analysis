import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.cashflow import assumption_preview, summarize
from backend.app.core.cashflow_import import parse_import, preview
from backend.app.main import app
from backend.app.models import CashflowBalance, CashflowTransactionPatch
from backend.app.storage import CashflowStore

client = TestClient(app)

ALIPAY_CSV = """支付宝交易记录明细查询
账号:[test]
---------------------------------交易记录明细列表------------------------------------
交易时间,交易对方,商品说明,金额（元）,收/支,交易状态
2026-01-05,公司,工资,10000.00,收入,交易成功
2026-01-06,餐厅,午餐,50.00,支出,交易成功
2026-01-07,基金公司,基金定投,1000.00,支出,交易成功
2026-01-08,本人,转账,2000.00,不计收支,交易成功
2026-02-05,公司,工资,10000.00,收入,交易成功
2026-02-06,超市,日用品,300.00,支出,交易成功
"""


def test_preview_detects_header_and_columns():
    payload = preview(ALIPAY_CSV.encode("gb18030"), "alipay.csv", "alipay")
    assert payload.header_row == 3
    assert payload.encoding == "gb18030"
    assert payload.suggested_mapping.date == "交易时间"
    assert payload.suggested_mapping.amount == "金额（元）"
    assert payload.suggested_mapping.direction == "收/支"
    assert payload.total_rows == 6


def test_parse_and_summary(tmp_path: Path):
    store = CashflowStore(tmp_path / "cashflow.db")
    payload = preview(ALIPAY_CSV.encode("gb18030"), "alipay.csv", "alipay")
    parsed = parse_import(
        ALIPAY_CSV.encode("gb18030"),
        "alipay.csv",
        payload.suggested_mapping,
        source="alipay",
        account="支付宝",
        import_id="test-import",
        rules=store.list_rules(),
    )
    assert len(parsed.transactions) == 6
    directions = [tx.direction for tx in parsed.transactions]
    assert directions.count("income") == 2
    assert directions.count("expense") == 2
    assert directions.count("investment") == 1
    assert directions.count("transfer") == 1
    investment = next(tx for tx in parsed.transactions if tx.direction == "investment")
    assert investment.bucket == "a_share"
    assert investment.investment_action == "buy"

    store.save_transactions(parsed.transactions, "now")
    transactions, total = store.list_transactions(limit=100)
    assert total == 6

    balances = [
        CashflowBalance(
            id=1,
            date=date(2026, 1, 31),
            bucket="cash",
            balance=50_000,
        ),
        CashflowBalance(
            id=2,
            date=date(2026, 1, 31),
            bucket="a_share",
            balance=10_000,
        ),
        CashflowBalance(
            id=3,
            date=date(2026, 2, 28),
            bucket="cash",
            balance=52_000,
        ),
        CashflowBalance(
            id=4,
            date=date(2026, 2, 28),
            bucket="a_share",
            balance=12_000,
        ),
    ]
    summary = summarize(transactions, balances)
    assert len(summary.months) == 2
    assert summary.months[0].income == pytest.approx(10_000, rel=1e-2)
    assert summary.months[0].expense == pytest.approx(50, rel=1e-2)
    assert summary.months[0].investment_buy == pytest.approx(1_000, rel=1e-2)
    assert summary.latest_balances["a_share"] == pytest.approx(12_000, rel=1e-3)
    preview_values = assumption_preview(transactions, summary, window_months=12)
    assert preview_values.months_used == 2
    assert preview_values.monthly_income > 0
    assert preview_values.monthly_expense > 0


def test_manual_override_wins(tmp_path: Path):
    store = CashflowStore(tmp_path / "cashflow.db")
    payload = preview(ALIPAY_CSV.encode("gb18030"), "alipay.csv", "alipay")
    parsed = parse_import(
        ALIPAY_CSV.encode("gb18030"),
        "alipay.csv",
        payload.suggested_mapping,
        source="alipay",
        account="支付宝",
        import_id="manual",
        rules=store.list_rules(),
    )
    store.save_transactions(parsed.transactions, "now")
    transactions, _ = store.list_transactions(limit=10)
    target = next(tx for tx in transactions if tx.direction == "expense")
    updated = store.update_transaction(
        target.id,
        CashflowTransactionPatch(category="自定义", is_one_off=True),
    )
    assert updated is not None
    assert updated.category == "自定义"
    assert updated.category_source == "manual"
    assert updated.is_one_off is True
    moved = store.update_transaction(
        target.id, CashflowTransactionPatch(direction="investment")
    )
    assert moved is not None
    assert moved.category == "投资"
    assert moved.bucket == "other"
    assert moved.investment_action == "buy"


def test_cashflow_api_preview_import_summary_and_balances():
    files = {"file": ("alipay.csv", ALIPAY_CSV.encode("gb18030"), "text/csv")}
    data = {"source": "alipay", "account": "API测试", "mapping": "{}"}
    response = client.post("/api/cashflow/preview", files=files, data={"source": "alipay"})
    assert response.status_code == 200, response.text
    preview_body = response.json()
    assert preview_body["suggested_mapping"]["date"] == "交易时间"

    files = {"file": ("alipay.csv", ALIPAY_CSV.encode("gb18030"), "text/csv")}
    data = {
        "source": "alipay",
        "account": "API测试",
        "mapping": json.dumps(preview_body["suggested_mapping"], ensure_ascii=False),
    }
    response = client.post("/api/cashflow/import", files=files, data=data)
    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["imported"] > 0

    summary = client.get("/api/cashflow/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["transaction_count"] >= imported["imported"]

    transaction = client.get("/api/cashflow/transactions?limit=5").json()["items"][0]
    patched = client.patch(
        f"/api/cashflow/transactions/{transaction['id']}",
        json={"is_one_off": True},
    )
    assert patched.status_code == 200
    assert patched.json()["is_one_off"] is True

    balance = client.post(
        "/api/cashflow/balances",
        json={
            "date": "2026-02-28",
            "bucket": "cash",
            "balance": 50_000,
            "note": "test",
        },
    )
    assert balance.status_code == 200, balance.text
    assert client.get("/api/cashflow/balances").status_code == 200
    assert client.delete(f"/api/cashflow/balances/{balance.json()['id']}").status_code == 200

    deleted = client.delete(f"/api/cashflow/imports/{imported['import_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] > 0


WECHAT_SAMPLE = """微信支付账单明细,,,,,,,,,,
微信昵称：[测试],,,,,,,,,,
----------------------微信支付账单明细列表--------------------,,,,,,,,,,
交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
2026-01-01 12:00:00,商户消费,某餐厅,总共消费,支出,¥30.00,零钱,支付成功,1,1,/
2026-01-02 12:00:00,微信红包,好友,/,收入,¥5.00,零钱,已存入零钱,2,2,/
2026-01-03 12:00:00,转账,房东,转账备注,支出,¥500.00,零钱,朋友已收钱,3,3,/
2026-01-04 12:00:00,转入零钱通-来自银行卡,/,/,/,¥2000.00,银行卡,支付成功,4,4,/
2026-01-05 12:00:00,零钱提现,某银行,/,/,¥100.00,零钱,提现已到账,5,5,/
2026-01-06 12:00:00,信用卡还款,某银行,/,/,¥500.00,零钱,支付成功,6,6,/
2026-01-07 12:00:00,购买理财通,理财通,某基金,/,¥1000.00,银行卡,支付成功,7,7,/
"""


def test_wechat_format_and_transaction_type_rules(tmp_path: Path):
    content = WECHAT_SAMPLE.encode("utf-8-sig")
    payload = preview(content, "wechat.csv", "wechat")
    assert payload.suggested_mapping.description == "商品"
    assert payload.suggested_mapping.category == "交易类型"
    assert payload.suggested_mapping.status == "当前状态"
    store = CashflowStore(tmp_path / "wechat.db")
    parsed = parse_import(
        content,
        "wechat.csv",
        payload.suggested_mapping,
        source="wechat",
        account="微信",
        import_id="wechat",
        rules=store.list_rules(),
    )
    assert len(parsed.transactions) == 7
    by_type = {tx.raw_category: tx for tx in parsed.transactions}
    assert by_type["商户消费"].direction == "expense"
    assert by_type["微信红包"].direction == "income"
    assert by_type["微信红包"].category == "红包"
    assert by_type["转账"].direction == "transfer"
    assert by_type["转入零钱通-来自银行卡"].direction == "transfer"
    assert by_type["零钱提现"].direction == "transfer"
    assert by_type["信用卡还款"].direction == "transfer"
    assert by_type["购买理财通"].direction == "investment"


ALIPAY_MODERN = """支付宝交易记录明细查询
账号:[test]
---------------------------------交易记录明细列表------------------------------------
交易号,商家订单号,交易创建时间,类型,交易对方,商品名称,金额（元）,收/支,交易状态,收/付款方式,备注
1,ORDER-1,2026-01-01 10:00:00,即时到账交易,示例书店,教材,88.50,支出,交易成功,银行卡,脱敏
2,ORDER-2,2026-01-02 10:00:00,转账,家人,生活费,500.00,收入,交易成功,余额,脱敏
共2笔记录,,,,,,,,,,
已支出:1笔 88.50元,,,,,,,,,,
"""


def test_alipay_header_description_and_footer(tmp_path: Path):
    content = ALIPAY_MODERN.encode("utf-8")
    payload = preview(content, "alipay.csv", "alipay")
    assert payload.suggested_mapping.description == "商品名称"
    store = CashflowStore(tmp_path / "alipay.db")
    parsed = parse_import(
        content,
        "alipay.csv",
        payload.suggested_mapping,
        source="alipay",
        account="支付宝",
        import_id="alipay",
        rules=store.list_rules(),
    )
    assert len(parsed.transactions) == 2
    assert parsed.skipped == 0
    assert parsed.transactions[0].description == "教材"
    assert parsed.transactions[0].direction == "expense"
    assert parsed.transactions[1].direction == "transfer"


ICBC_SAMPLE = """明细查询文件下载

卡号: 1234****5678

子账户类别:

交易日期,记账日期,摘要,交易场所,交易国家或地区简称,交易金额(收入),交易金额(支出),交易币种,记账金额(收入),记账金额(支出),记账币种,余额,对方户名
2026-01-01,2026-01-01,消费,财付通-某餐厅,CHN,,18.00,人民币,,18.00,人民币,-100.00,
2026-01-02,2026-01-02,自动转帐还款,某银行,CHN,500.00,,人民币,500.00,,人民币,-618.00,
合计金额,,,,,500.00,18.00,,500.00,18.00,,
"""


def test_icbc_two_amount_columns(tmp_path: Path):
    content = ICBC_SAMPLE.encode("utf-8-sig")
    payload = preview(content, "icbc.csv", "bank")
    mapping = payload.suggested_mapping
    assert mapping.amount_mode == "two_columns"
    assert mapping.income_amount == "交易金额(收入)"
    assert mapping.expense_amount == "交易金额(支出)"
    assert mapping.counterparty == "交易场所"
    store = CashflowStore(tmp_path / "icbc.db")
    parsed = parse_import(
        content,
        "icbc.csv",
        mapping,
        source="bank",
        account="工行",
        import_id="icbc",
        rules=store.list_rules(),
    )
    assert len(parsed.transactions) == 2
    assert parsed.skipped == 0
    assert parsed.transactions[0].direction == "expense"
    assert parsed.transactions[0].category == "餐饮"
    assert parsed.transactions[1].direction == "transfer"
