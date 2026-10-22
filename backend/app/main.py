from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse

from .assets import load_calibration
from .config import settings
from .core.advice import analyze
from .core.cashflow import (
    apply_rules,
    assumption_preview,
    finalize_classification,
    summarize,
)
from .core.cashflow_import import parse_balances, parse_import, preview
from .core.engine import run_simulation
from .core.explain import explain_run, template_explanation
from .core.history import history_meta, load_history_data, run_history_backtest
from .core.metrics import build_metrics
from .core.snapshot import (
    code_fingerprint,
    export_analysis_snapshot,
    export_history_snapshot,
    export_snapshot,
    make_run_id,
)
from .defaults import defaults_payload
from .models import (
    AnalysisRequest,
    AnalysisResponse,
    CashflowAssumptionPreview,
    CashflowBalance,
    CashflowBalanceInput,
    CashflowImportBatch,
    CashflowImportResult,
    CashflowMapping,
    CashflowPreview,
    CashflowRule,
    CashflowRuleInput,
    CashflowSummary,
    CashflowTransaction,
    CashflowTransactionList,
    CashflowTransactionPatch,
    CompareItem,
    CompareResponse,
    DefaultsResponse,
    HistoryMetaResponse,
    HistoryRequest,
    HistoryResponse,
    RunListItem,
    RunResponse,
    ScenarioRequest,
)
from .simple import SimpleRequest, build_simple_request
from .storage import AnalysisStore, CashflowStore, HistoryStore, RunStore

app = FastAPI(title="家庭财务情景推演", version=settings.code_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RunStore(settings.database_path)
history_store = HistoryStore(settings.database_path)
analysis_store = AnalysisStore(settings.database_path)
cashflow_store = CashflowStore(settings.database_path)
IMPORTS_DIR = settings.database_path.parent / "imports"
FINGERPRINT = code_fingerprint()


def _execute(request: ScenarioRequest, use_llm: bool) -> RunResponse:
    mode = "llm" if use_llm else "template"
    data_version = (
        request.data_version
        if request.data_version and request.data_version != "none"
        else settings.data_version
    )
    run_id = make_run_id(
        request.model_dump(mode="json"),
        settings.code_version,
        FINGERPRINT,
        data_version,
        explanation_mode=mode,
    )
    existing = store.get(run_id)
    if existing is not None:
        return RunResponse.model_validate(existing)

    simulation = run_simulation(request)
    metrics = build_metrics(request, simulation)
    if use_llm:
        explanation, explanation_warnings = explain_run(request, metrics, settings)
    else:
        explanation = template_explanation(request, metrics)
        explanation_warnings = []

    response = RunResponse(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        request=request,
        metrics=metrics,
        explanation=explanation,
        warnings=[*simulation.warnings, *explanation_warnings],
        code_version=settings.code_version,
        code_fingerprint=FINGERPRINT,
        data_version=data_version,
    )
    store.save(response)
    export_snapshot(response, settings.runs_dir)
    return response


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "code_version": settings.code_version,
        "llm_enabled": settings.llm_enabled,
        "data_version": load_calibration().get("data_version", settings.data_version),
        "history_data_version": load_history_data().data_version,
    }


@app.get("/api/calibration")
def get_calibration() -> dict:
    calibration = load_calibration()
    if not calibration:
        raise HTTPException(status_code=404, detail="calibration snapshot not found")
    return calibration


@app.get("/api/defaults", response_model=DefaultsResponse)
def get_defaults(window: str = "10y") -> DefaultsResponse:
    calibration = load_calibration()
    if calibration and window not in calibration.get("correlations", {}):
        raise HTTPException(status_code=422, detail=f"unknown calibration window {window!r}")
    return defaults_payload(window=window)


@app.post("/api/runs", response_model=RunResponse)
def create_run(request: ScenarioRequest) -> RunResponse:
    try:
        return _execute(request, use_llm=request.include_explanation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/simple", response_model=RunResponse)
def create_simple_run(payload: SimpleRequest) -> RunResponse:
    try:
        request = build_simple_request(payload)
        return _execute(request, use_llm=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/history/meta", response_model=HistoryMetaResponse)
def get_history_meta() -> HistoryMetaResponse:
    return history_meta()


@app.post("/api/history/backtest", response_model=HistoryResponse)
def create_history_run(request: HistoryRequest) -> HistoryResponse:
    data = load_history_data()
    run_id = make_run_id(
        {"kind": "history", "request": request.model_dump(mode="json")},
        settings.code_version,
        FINGERPRINT,
        data.data_version,
        explanation_mode="none",
    )
    existing = history_store.get(run_id)
    if existing is not None:
        return HistoryResponse.model_validate(existing)
    try:
        result = run_history_backtest(request, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = HistoryResponse(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        request=request,
        data_version=data.data_version,
        code_version=settings.code_version,
        code_fingerprint=FINGERPRINT,
        **result.__dict__,
    )
    history_store.save(response)
    export_history_snapshot(response, settings.runs_dir)
    return response


@app.get("/api/history/runs/{run_id}", response_model=HistoryResponse)
def get_history_run(run_id: str) -> HistoryResponse:
    existing = history_store.get(run_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="history run not found")
    return HistoryResponse.model_validate(existing)


def _cached_analysis(analysis_id: str) -> AnalysisResponse | None:
    existing = analysis_store.get(analysis_id)
    if existing is None:
        return None
    return AnalysisResponse.model_validate(existing)


def _save_analysis(response: AnalysisResponse) -> None:
    analysis_store.save(response)
    export_analysis_snapshot(response, settings.runs_dir)


@app.post("/api/analysis", response_model=AnalysisResponse)
def create_analysis(payload: AnalysisRequest) -> AnalysisResponse:
    run: RunResponse | None = None
    history: HistoryResponse | None = None
    if payload.mode in ("simple", "full"):
        existing = store.get(payload.run_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="run not found")
        run = RunResponse.model_validate(existing)
        data_version = run.data_version
    else:
        existing = history_store.get(payload.run_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="history run not found")
        history = HistoryResponse.model_validate(existing)
        data_version = history.data_version
    try:
        return analyze(
            mode=payload.mode,
            run=run,
            history=history,
            settings=settings,
            code_version=settings.code_version,
            code_fingerprint=FINGERPRINT,
            data_version=data_version,
            cache_get=_cached_analysis,
            cache_save=_save_analysis,
            force=payload.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/analysis/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str) -> AnalysisResponse:
    existing = _cached_analysis(analysis_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return existing


def _safe_filename(filename: str) -> str:
    cleaned = "".join(
        char for char in filename if char.isalnum() or char in "._-"
    )
    return cleaned[-100:] or "upload.csv"


@app.post("/api/cashflow/preview", response_model=CashflowPreview)
async def cashflow_preview(
    file: UploadFile = File(...), source: str = Form("generic")
) -> CashflowPreview:
    content = await file.read()
    try:
        return preview(content, file.filename or "upload.csv", source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/cashflow/import", response_model=CashflowImportResult)
async def cashflow_import(
    file: UploadFile = File(...),
    source: str = Form("generic"),
    account: str = Form(""),
    mapping: str = Form(...),
) -> CashflowImportResult:
    try:
        mapping_payload = CashflowMapping.model_validate(json.loads(mapping))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="无效的字段映射") from exc
    content = await file.read()
    import_id = uuid4().hex[:16]
    try:
        parsed = parse_import(
            content,
            file.filename or "upload.csv",
            mapping_payload,
            source=source,
            account=account or source,
            import_id=import_id,
            rules=cashflow_store.list_rules(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename or "upload.csv")
    raw_path = IMPORTS_DIR / f"{import_id}_{safe_name}"
    raw_path.write_bytes(content)
    created_at = datetime.now(timezone.utc).isoformat()
    imported = cashflow_store.save_transactions(parsed.transactions, created_at)
    duplicates = len(parsed.transactions) - imported
    cashflow_store.save_import(
        import_id=import_id,
        source=source,
        account=account or source,
        filename=file.filename or safe_name,
        row_count=parsed.row_count,
        imported=imported,
        duplicates=duplicates,
        skipped=parsed.skipped,
        mapping=mapping_payload.model_dump(mode="json"),
        warnings=parsed.warnings,
        raw_path=str(raw_path),
        created_at=created_at,
    )
    warnings = list(parsed.warnings)
    if duplicates:
        warnings.append(f"{duplicates} 笔交易与已有记录重复，未重复导入。")
    return CashflowImportResult(
        import_id=import_id,
        source=source,
        account=account or source,
        filename=file.filename or safe_name,
        row_count=parsed.row_count,
        imported=imported,
        duplicates=duplicates,
        skipped=parsed.skipped,
        warnings=warnings,
    )


@app.get(
    "/api/cashflow/transactions", response_model=CashflowTransactionList
)
def list_cashflow_transactions(
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 200,
    offset: int = 0,
    direction: str | None = None,
    category: str | None = None,
) -> CashflowTransactionList:
    items, total = cashflow_store.list_transactions(
        from_date=from_date,
        to_date=to_date,
        limit=max(1, min(limit, 1000)),
        offset=max(0, offset),
        direction=direction,
        category=category,
    )
    return CashflowTransactionList(items=items, total=total)


@app.patch(
    "/api/cashflow/transactions/{transaction_id}",
    response_model=CashflowTransaction,
)
def update_cashflow_transaction(
    transaction_id: int, patch: CashflowTransactionPatch
) -> CashflowTransaction:
    updated = cashflow_store.update_transaction(transaction_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return updated


@app.get("/api/cashflow/rules", response_model=list[CashflowRule])
def list_cashflow_rules() -> list[CashflowRule]:
    return cashflow_store.list_rules()


@app.post("/api/cashflow/rules", response_model=CashflowRule)
def create_cashflow_rule(rule: CashflowRuleInput) -> CashflowRule:
    return cashflow_store.add_rule(rule)


@app.patch("/api/cashflow/rules/{rule_id}", response_model=CashflowRule)
def update_cashflow_rule(rule_id: int, rule: CashflowRuleInput) -> CashflowRule:
    updated = cashflow_store.update_rule(rule_id, rule)
    if updated is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return updated


@app.post("/api/cashflow/reapply-rules")
def reapply_cashflow_rules() -> dict:
    transactions, _ = cashflow_store.list_transactions(limit=1_000_000)
    rules = cashflow_store.list_rules()
    updated = 0
    for transaction in transactions:
        if transaction.category_source == "manual":
            continue
        before = (
            transaction.direction,
            transaction.category,
            transaction.bucket,
            transaction.investment_action,
        )
        changed = finalize_classification(apply_rules(transaction, rules))
        after = (
            changed.direction,
            changed.category,
            changed.bucket,
            changed.investment_action,
        )
        if before == after:
            continue
        cashflow_store.set_classification(
            transaction.id,
            direction=changed.direction,
            category=changed.category,
            bucket=changed.bucket,
            investment_action=changed.investment_action,
        )
        updated += 1
    return {"updated": updated}


@app.delete("/api/cashflow/rules/{rule_id}")
def delete_cashflow_rule(rule_id: int) -> dict:
    if not cashflow_store.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="rule not found")
    return {"deleted": True}


@app.get("/api/cashflow/balances", response_model=list[CashflowBalance])
def list_cashflow_balances(
    from_date: date | None = None, to_date: date | None = None
) -> list[CashflowBalance]:
    return cashflow_store.list_balances(from_date=from_date, to_date=to_date)


@app.post("/api/cashflow/balances", response_model=CashflowBalance)
def upsert_cashflow_balance(balance: CashflowBalanceInput) -> CashflowBalance:
    return cashflow_store.upsert_balance(balance)


@app.delete("/api/cashflow/balances/{balance_id}")
def delete_cashflow_balance(balance_id: int) -> dict:
    if not cashflow_store.delete_balance(balance_id):
        raise HTTPException(status_code=404, detail="balance not found")
    return {"deleted": True}


@app.post("/api/cashflow/balances/import")
async def import_cashflow_balances(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        parsed = parse_balances(content, file.filename or "balances.csv")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    imported = 0
    for balance in parsed.balances:
        cashflow_store.upsert_balance(balance, source="csv")
        imported += 1
    return {
        "row_count": parsed.row_count,
        "imported": imported,
        "skipped": parsed.skipped,
        "warnings": parsed.warnings,
    }


@app.get("/api/cashflow/summary", response_model=CashflowSummary)
def cashflow_summary(
    from_date: date | None = None, to_date: date | None = None
) -> CashflowSummary:
    transactions, _ = cashflow_store.list_transactions(
        from_date=from_date,
        to_date=to_date,
        limit=1_000_000,
        offset=0,
    )
    balances = cashflow_store.list_balances(
        from_date=from_date, to_date=to_date
    )
    return summarize(transactions, balances)


@app.get(
    "/api/cashflow/assumptions", response_model=CashflowAssumptionPreview
)
def cashflow_assumptions(window: int = 12) -> CashflowAssumptionPreview:
    if window < 1 or window > 36:
        raise HTTPException(status_code=422, detail="window must be 1-36")
    transactions, _ = cashflow_store.list_transactions(
        limit=1_000_000, offset=0
    )
    balances = cashflow_store.list_balances()
    summary = summarize(transactions, balances)
    try:
        return assumption_preview(
            transactions, summary, window_months=window
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/cashflow/imports", response_model=list[CashflowImportBatch])
def list_cashflow_imports() -> list[CashflowImportBatch]:
    return cashflow_store.list_imports()


@app.delete("/api/cashflow/imports/{import_id}")
def delete_cashflow_import(import_id: str) -> dict:
    raw_path = cashflow_store.get_import_raw_path(import_id)
    deleted = cashflow_store.delete_import(import_id)
    if raw_path:
        Path(raw_path).unlink(missing_ok=True)
    return {"deleted": deleted}


@app.get("/api/runs", response_model=list[RunListItem])
def list_runs(limit: int = 20) -> list[RunListItem]:
    return store.list_recent(limit=max(1, min(limit, 100)))


@app.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    existing = store.get(run_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="run not found")
    return RunResponse.model_validate(existing)


@app.post("/api/compare", response_model=CompareResponse)
def compare_runs(requests: list[ScenarioRequest]) -> CompareResponse:
    if not 2 <= len(requests) <= 5:
        raise HTTPException(status_code=422, detail="compare requires 2-5 scenarios")
    baseline = requests[0]
    for request in requests[1:]:
        if request.n_paths != baseline.n_paths:
            raise HTTPException(status_code=422, detail="scenarios must share n_paths")
        if request.horizon_years != baseline.horizon_years:
            raise HTTPException(
                status_code=422, detail="scenarios must share horizon_years"
            )
        if request.seed != baseline.seed:
            raise HTTPException(status_code=422, detail="scenarios must share seed")
        if request.market.student_t_df != baseline.market.student_t_df:
            raise HTTPException(
                status_code=422, detail="scenarios must share student_t_df"
            )
        if [asset.name for asset in request.market.assets] != [
            asset.name for asset in baseline.market.assets
        ]:
            raise HTTPException(
                status_code=422,
                detail="scenarios must share asset names and order",
            )

    items: list[CompareItem] = []
    for request in requests:
        try:
            response = _execute(request, use_llm=False)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        items.append(
            CompareItem(
                run_id=response.run_id,
                name=request.name,
                terminal_assets_p50=response.metrics.terminal_assets.p50,
                terminal_net_worth_p50=response.metrics.terminal_net_worth.p50,
                max_drawdown_p50=response.metrics.max_drawdown.p50,
                joint_shortfall_probability=response.metrics.joint_shortfall_probability,
                ruin_probability=response.metrics.ruin_probability,
                terminal_assets_p5=response.metrics.terminal_assets.p5,
                terminal_assets_p25=response.metrics.terminal_assets.p25,
                terminal_assets_p75=response.metrics.terminal_assets.p75,
                terminal_assets_p95=response.metrics.terminal_assets.p95,
                terminal_emergency_p50=(
                    response.metrics.terminal_emergency_fund.p50
                    if response.metrics.terminal_emergency_fund is not None
                    else None
                ),
                terminal_illiquid_p50=(
                    response.metrics.terminal_illiquid_assets.p50
                    if response.metrics.terminal_illiquid_assets is not None
                    else None
                ),
                terminal_liabilities_p50=(
                    response.metrics.terminal_liabilities.p50
                    if response.metrics.terminal_liabilities is not None
                    else None
                ),
                total_contributions=response.metrics.total_contributions,
                total_event_withdrawals=response.metrics.total_event_withdrawals,
            )
        )
    return CompareResponse(items=items)


class SafeStaticFiles(StaticFiles):
    """Serve the SPA, but turn malformed paths into 404s.

    On Windows a request such as ``/**。`` reaches ``os.stat`` with characters
    that are invalid in a filename, raising OSError and becoming a 500. A bad
    URL should not look like a server failure.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except OSError:
            return PlainTextResponse("Not Found", status_code=404)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount(
        "/",
        SafeStaticFiles(directory=frontend_dist, html=True),
        name="frontend",
    )
