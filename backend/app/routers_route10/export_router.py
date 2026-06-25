from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.models.route_schemas import KMLExportRequest
from app.services.export_service import export_kml, export_shp

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/kml")
def export_kml_file(payload: KMLExportRequest):
    try:
        content, filename, has_protection_zone = export_kml(payload.route_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Protection-Zone-Included": "1" if has_protection_zone else "0",
    }
    return Response(content=content, media_type="application/vnd.google-earth.kml+xml", headers=headers)


@router.post("/shp")
def export_shp_file(payload: KMLExportRequest):
    try:
        path = export_shp(payload.route_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path=path, media_type="application/zip", filename=path.name)
