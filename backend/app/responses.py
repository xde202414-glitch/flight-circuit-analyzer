"""Standard API response helpers.

All API endpoints should return responses using these helpers
to ensure the frontend receives consistent {code, data, message} format.
"""
from fastapi.responses import JSONResponse


def success(data=None, message: str = "success"):
    """Return a success JSONResponse."""
    return JSONResponse(content={
        "code": 200,
        "data": data,
        "message": message,
    })


def error(code: int = 422, message: str = "error", data=None):
    """Return an error JSONResponse."""
    return JSONResponse(content={
        "code": code,
        "data": data,
        "message": message,
    }, status_code=200)
