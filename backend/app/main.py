from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse

from .assets import load_calibration
from .config import settings
from .core.engine import run_simulation
from .core.explain import explain_run, template_explanation
from .core.history import history_meta, load_history_data, run_history_backtest
from .core.metrics import build_metrics
from .core.snapshot import (
    code_fingerprint,
    export_history_snapshot,
    export_snapshot,
    make_run_id,
)
from .defaults import defaults_payload
from .models import (
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
from .storage import HistoryStore, RunStore

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
