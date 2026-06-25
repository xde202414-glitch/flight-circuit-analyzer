from fastapi import APIRouter, HTTPException, Query

from app.models.route_schemas import (
    AnalysisAuthoritativeLayerImportRequest,
    AnalysisAuthoritativeLayerUpdateRequest,
    AnalysisFactorInputUpdateRequest,
    AnalysisFactorParamsUpdateRequest,
    AnalysisFactorRunRequest,
    AnalysisRunRequest,
)
from app.services.analysis_service import (
    delete_authoritative_layer,
    get_analysis_catalog,
    list_authoritative_layers,
    get_route_analysis_view,
    import_authoritative_layer,
    run_route_analysis,
    update_authoritative_layer,
    update_factor_input,
    update_factor_params,
)

router = APIRouter(prefix="", tags=["analysis"])


def _raise_http_for_value_error(exc: ValueError) -> None:
    detail = str(exc)
    if "not found" in detail.lower():
        raise HTTPException(status_code=404, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/analysis/catalog")
def read_analysis_catalog():
    return get_analysis_catalog()


@router.get("/routes/{route_id}/analysis")
def read_route_analysis(route_id: int):
    try:
        return get_route_analysis_view(route_id)
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.post("/routes/{route_id}/analysis/run")
def run_analysis(route_id: int, payload: AnalysisRunRequest):
    try:
        return run_route_analysis(
            route_id,
            aircraft_type=payload.aircraft_type,
            factor_ids=payload.factor_ids,
            param_overrides=payload.param_overrides,
        )
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.put("/routes/{route_id}/analysis/factors/{factor_id}/input")
def write_factor_input(route_id: int, factor_id: str, payload: AnalysisFactorInputUpdateRequest):
    try:
        return update_factor_input(
            route_id,
            factor_id,
            input_mode=payload.input_mode,
            manual_value=payload.manual_value,
        )
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.put("/routes/{route_id}/analysis/factors/{factor_id}/params")
def write_factor_params(route_id: int, factor_id: str, payload: AnalysisFactorParamsUpdateRequest):
    try:
        return update_factor_params(route_id, factor_id, payload.params)
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.post("/routes/{route_id}/analysis/factors/{factor_id}/run")
def run_single_factor(route_id: int, factor_id: str, payload: AnalysisFactorRunRequest):
    try:
        return run_route_analysis(
            route_id,
            aircraft_type=payload.aircraft_type,
            factor_ids=[factor_id],
            param_overrides={factor_id: payload.param_override or {}},
        )
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.get("/analysis/authoritative-layers")
def read_authoritative_layers(
    factor_id: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
):
    try:
        return {"items": list_authoritative_layers(factor_id=factor_id, enabled_only=enabled_only)}
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.post("/analysis/authoritative-layers/import")
def create_authoritative_layer(payload: AnalysisAuthoritativeLayerImportRequest):
    try:
        return import_authoritative_layer(payload.model_dump())
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.put("/analysis/authoritative-layers/{layer_id}")
def edit_authoritative_layer(layer_id: int, payload: AnalysisAuthoritativeLayerUpdateRequest):
    try:
        return update_authoritative_layer(layer_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        _raise_http_for_value_error(exc)


@router.delete("/analysis/authoritative-layers/{layer_id}")
def remove_authoritative_layer(layer_id: int):
    try:
        return delete_authoritative_layer(layer_id)
    except ValueError as exc:
        _raise_http_for_value_error(exc)
