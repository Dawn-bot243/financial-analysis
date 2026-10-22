"""Generic CSV/Excel import for bank, Alipay and WeChat statements.

The platform formats change and contain preamble/footer rows, so the importer
detects the header row, previews the headers, and lets the user map columns.
The platform presets are only suggestions; the normalized data is independent
of the source file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from ..models import (
    CashflowBalanceInput,
    CashflowMapping,
    CashflowPreview,
    CashflowRule,
    CashflowTransaction,
    InvestmentBucket,
)
from .cashflow import apply_rules, finalize_classification

BALANCE_BUCKETS: dict[str, InvestmentBucket] = {
    "现金": "cash",
    "货币": "cash",
    "a股": "a_share",
    "股票": "a_share",
    "基金": "a_share",
    "海外": "overseas",
    "qdii": "overseas",
    "黄金": "gold",
    "债券": "bond",
    "债基": "bond",
    "其他": "other",
}

DATE_KEYS = ("交易时间", "交易日期", "记账日期", "入账日期", "日期", "时间", "date", "time")
AMOUNT_KEYS = ("交易金额", "金额", "发生额", "收支金额", "人民币金额", "amount", "money")
INCOME_AMOUNT_KEYS = (
    "交易金额(收入)",
    "交易金额（收入）",
    "收入金额",
    "贷方金额",
    "存入金额",
    "收入",
    "credit",
    "deposit",
)
EXPENSE_AMOUNT_KEYS = (
    "交易金额(支出)",
    "交易金额（支出）",
    "支出金额",
    "借方金额",
    "取出金额",
    "支出",
    "debit",
    "withdrawal",
)
DIRECTION_KEYS = ("收/支", "收支", "交易类型", "借贷标志", "收支类型", "direction", "type")
COUNTERPARTY_KEYS = (
    "交易对方",
    "对方名称",
    "交易场所",
    "对方",
    "商户",
    "收款方",
    "付款方",
    "counterparty",
    "merchant",
)
DESCRIPTION_KEYS = ("商品说明", "商品", "交易说明", "交易描述", "摘要", "备注", "用途", "description", "memo", "note")
CATEGORY_KEYS = ("交易分类", "分类", "类别", "交易类型", "类型", "category")
ACCOUNT_KEYS = ("账户", "卡号", "账号", "account")
STATUS_KEYS = ("交易状态", "当前状态", "状态", "status")


@dataclass
class ParsedImport:
    transactions: list[CashflowTransaction] = field(default_factory=list)
    row_count: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedBalances:
    balances: list[CashflowBalanceInput] = field(default_factory=list)
    row_count: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("nan", "none", "nat"):
        return ""
    return text


def _find_header_row(rows: list[list[str]]) -> int:
    best_index = 0
    best_score = -1.0
    for index, row in enumerate(rows[:80]):
        cells = [_clean(cell) for cell in row]
        non_empty = [cell for cell in cells if cell]
        if len(non_empty) < 2:
            continue
        joined = " ".join(cells)
        score = len(non_empty)
        for keyword in DATE_KEYS + AMOUNT_KEYS:
            if keyword.lower() in joined.lower():
                score += 4
        for keyword in DIRECTION_KEYS + COUNTERPARTY_KEYS:
            if keyword.lower() in joined.lower():
                score += 2
        # Preambles often have one long sentence in the first cell.
        if len(non_empty) <= 2:
            score -= 5
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _decode_csv(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "utf-16", "utf-8"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 CSV 编码，请另存为 UTF-8 或 GB18030")


def read_table(content: bytes, filename: str) -> tuple[pd.DataFrame, int, str]:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
        rows = raw.fillna("").astype(str).values.tolist()
        header_row = _find_header_row(rows)
        frame = pd.read_excel(io.BytesIO(content), header=header_row, dtype=str)
        frame = frame.dropna(how="all")
        return _dedupe_headers(frame), header_row, "excel"
    text, encoding = _decode_csv(content)
    rows = list(csv.reader(io.StringIO(text)))
    header_row = _find_header_row(rows)
    frame = pd.read_csv(
        io.StringIO(text),
        header=header_row,
        dtype=str,
        index_col=False,
        on_bad_lines="skip",
        skip_blank_lines=False,
    )
    frame = frame.dropna(how="all")
    return _dedupe_headers(frame), header_row, encoding


def _dedupe_headers(frame: pd.DataFrame) -> pd.DataFrame:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for column in frame.columns:
        name = _clean(column) or "未命名列"
        count = seen.get(name, 0)
        seen[name] = count + 1
        headers.append(name if count == 0 else f"{name}_{count + 1}")
    frame = frame.copy()
    frame.columns = headers
    return frame


def _pick(headers: list[str], keys: tuple[str, ...]) -> str | None:
    """Pick the highest-priority header, preferring an exact match per key."""
    lowered = [(header, header.lower()) for header in headers]
    for key in keys:
        needle = key.lower()
        for header, lower in lowered:
            if needle == lower:
                return header
        for header, lower in lowered:
            if needle in lower:
                return header
    return None


def suggest_mapping(headers: list[str], source: str, header_row: int) -> CashflowMapping:
    income_amount = _pick(headers, INCOME_AMOUNT_KEYS)
    expense_amount = _pick(headers, EXPENSE_AMOUNT_KEYS)
    if income_amount and expense_amount:
        amount = ""
        amount_mode = "two_columns"
    else:
        amount = _pick(headers, AMOUNT_KEYS) or ""
        amount_mode = "signed"
    return CashflowMapping(
        date=_pick(headers, DATE_KEYS) or "",
        amount=amount,
        income_amount=income_amount,
        expense_amount=expense_amount,
        direction=_pick(headers, DIRECTION_KEYS),
        counterparty=_pick(headers, COUNTERPARTY_KEYS),
        description=_pick(headers, DESCRIPTION_KEYS),
        category=_pick(headers, CATEGORY_KEYS),
        account=_pick(headers, ACCOUNT_KEYS),
        status=_pick(headers, STATUS_KEYS),
        header_row=header_row,
        amount_mode=amount_mode,
    )


def preview(content: bytes, filename: str, source: str = "generic") -> CashflowPreview:
    frame, header_row, encoding = read_table(content, filename)
    headers = list(frame.columns)
    rows: list[dict[str, str]] = []
    for _, row in frame.head(12).iterrows():
        rows.append({header: _clean(row[header]) for header in headers})
    return CashflowPreview(
        headers=headers,
        rows=rows,
        suggested_mapping=suggest_mapping(headers, source, header_row),
        header_row=header_row,
        encoding=encoding,
        total_rows=int(len(frame)),
    )


def _parse_date(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        try:
            parsed = pd.to_datetime(float(text), unit="D", origin="1899-12-30")
        except (TypeError, ValueError):
            return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _parse_amount(value: Any) -> float | None:
    text = _clean(value)
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    text = text.replace(",", "").replace("，", "")
    text = text.replace("¥", "").replace("￥", "").replace("元", "").replace(" ", "")
    text = re.sub(r"[^0-9.\-+]", "", text)
    if not text or text in ("-", "+", "."):
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return -abs(amount) if negative else amount


def _direction_from_text(
    raw: str, mapping: CashflowMapping
) -> str | None:
    text = _clean(raw).lower()
    if not text:
        return None
    for key, direction in sorted(
        mapping.direction_values.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if key and key.lower() in text:
            return direction
    return None


def _infer_direction(amount: float, mapping: CashflowMapping) -> str:
    if mapping.amount_mode == "positive_expense":
        return "expense" if amount > 0 else "income"
    if mapping.amount_mode == "absolute":
        return "expense"
    return "income" if amount >= 0 else "expense"


def _fingerprint(payload: dict[str, Any], occurrence: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(f"{text}#{occurrence}".encode("utf-8")).hexdigest()[:32]


def parse_import(
    content: bytes,
    filename: str,
    mapping: CashflowMapping,
    *,
    source: str,
    account: str,
    import_id: str,
    rules: list[CashflowRule],
) -> ParsedImport:
    frame, _header_row, _encoding = read_table(content, filename)
    headers = list(frame.columns)
    if not mapping.date or mapping.date not in headers:
        raise ValueError("必须选择有效的日期列")
    if mapping.amount_mode == "two_columns":
        for required in (mapping.income_amount, mapping.expense_amount):
            if not required or required not in headers:
                raise ValueError("两列金额模式需要有效的收入列和支出列")
    elif not mapping.amount or mapping.amount not in headers:
        raise ValueError("必须选择有效的金额列")
    result = ParsedImport(row_count=int(len(frame)))
    seen: dict[str, int] = {}
    for _, row in frame.iterrows():
        raw = {header: _clean(row[header]) for header in headers}
        status_text = raw.get(mapping.status, "") if mapping.status else ""
        if any(word in status_text for word in ("关闭", "失败", "撤销", "退款")):
            result.skipped += 1
            continue
        day = _parse_date(raw.get(mapping.date, ""))
        direction: str | None = None
        amount: float | None = None
        if mapping.amount_mode == "two_columns":
            income = _parse_amount(
                raw.get(mapping.income_amount or "", "")
            ) or 0.0
            expense = _parse_amount(
                raw.get(mapping.expense_amount or "", "")
            ) or 0.0
            income, expense = abs(income), abs(expense)
            if income > 0 and expense > 0:
                net = income - expense
                direction = "income" if net >= 0 else "expense"
                amount = abs(net)
            elif income > 0:
                direction, amount = "income", income
            elif expense > 0:
                direction, amount = "expense", expense
        else:
            amount = _parse_amount(raw.get(mapping.amount, ""))
            raw_direction = (
                raw.get(mapping.direction, "") if mapping.direction else ""
            )
            direction = _direction_from_text(raw_direction, mapping)
            if direction is None and amount is not None:
                direction = _infer_direction(amount, mapping)
        if day is None and not any(
            value and value.lower() != "nan" for value in raw.values()
        ):
            continue
        if day is None:
            footer_text = " ".join(raw.values())
            if any(
                marker in footer_text
                for marker in (
                    "共",
                    "合计",
                    "已收入",
                    "已支出",
                    "待收入",
                    "待支出",
                    "导出时间",
                    "用户:",
                    "------",
                )
            ):
                continue
        if day is None or amount is None or direction is None or abs(amount) < 1e-9:
            result.skipped += 1
            continue
        if direction == "income" and amount < 0:
            amount = abs(amount)
        transaction = CashflowTransaction(
            id=0,
            import_id=import_id,
            source=source,
            account=(
                raw.get(mapping.account, "").strip()
                if mapping.account and mapping.account in headers
                else account
            ) or account or source,
            date=day,
            amount=abs(float(amount)),
            direction=direction,
            category="",
            counterparty=raw.get(mapping.counterparty, "") if mapping.counterparty else "",
            description=raw.get(mapping.description, "") if mapping.description else "",
            raw_category=raw.get(mapping.category, "") if mapping.category else "",
            category_source="rule",
            fingerprint="",
            raw_json=json.dumps(raw, ensure_ascii=False),
        )
        transaction = finalize_classification(apply_rules(transaction, rules))
        base_payload = {
            "source": transaction.source,
            "account": transaction.account,
            "date": transaction.date,
            "amount": transaction.amount,
            "direction": transaction.direction,
            "counterparty": transaction.counterparty,
            "description": transaction.description,
            "raw_category": transaction.raw_category,
            "raw": raw,
        }
        base = _fingerprint(base_payload, 0)
        occurrence = seen.get(base, 0) + 1
        seen[base] = occurrence
        transaction.fingerprint = _fingerprint(base_payload, occurrence)
        result.transactions.append(transaction)
    if result.skipped:
        result.warnings.append(
            f"{result.skipped} 行缺少有效日期/金额，或状态为关闭/失败/退款，已跳过。"
        )
    if not result.transactions:
        result.warnings.append("没有解析出可用交易。")
    return result


def parse_balances(content: bytes, filename: str) -> ParsedBalances:
    """Parse a simple date/asset/balance CSV or Excel file."""
    frame, _header_row, _encoding = read_table(content, filename)
    headers = list(frame.columns)
    date_col = _pick(headers, DATE_KEYS)
    bucket_col = _pick(headers, ("资产", "类别", "分类", "bucket", "asset"))
    balance_col = _pick(headers, ("余额", "金额", "市值", "balance", "value"))
    if not date_col or not bucket_col or not balance_col:
        raise ValueError("余额文件需要日期、资产/类别、余额三列")
    note_col = _pick(headers, ("备注", "note"))
    result = ParsedBalances(row_count=int(len(frame)))
    for _, row in frame.iterrows():
        raw = {header: _clean(row[header]) for header in headers}
        day = _parse_date(raw.get(date_col, ""))
        balance = _parse_amount(raw.get(balance_col, ""))
        bucket_text = raw.get(bucket_col, "").lower()
        bucket: InvestmentBucket | None = None
        for key, value in BALANCE_BUCKETS.items():
            if key in bucket_text:
                bucket = value
                break
        if day is None or balance is None or bucket is None:
            result.skipped += 1
            continue
        result.balances.append(
            CashflowBalanceInput(
                date=day,
                bucket=bucket,
                balance=abs(balance),
                note=raw.get(note_col, "") if note_col else "",
            )
        )
    if result.skipped:
        result.warnings.append(f"{result.skipped} 行余额无法解析或资产类别未知，已跳过。")
    return result
