"""API response wrapping middleware.

Wraps all API responses in standard format: {code, data, message}
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi.responses import RedirectResponse, StreamingResponse
import json


class ApiResponseMiddleware(BaseHTTPMiddleware):
    """Middleware to wrap all API responses in standard format.
    
    Converts raw response data to: {"code": 200, "data": ..., "message": "success"}
    Converts error responses to: {"code": xxx, "data": null, "message": "error detail"}
    """

    async def dispatch(self, request: Request, call_next):
        # Skip wrapping for non-API paths (docs, redoc, openapi, static files)
        path = request.url.path
        if not path.startswith("/api/") and path not in ("/health", "/"):
            return await call_next(request)

        try:
            response: Response = await call_next(request)

            # Skip wrapping for non-JSON responses (e.g. redirects, streaming)
            if isinstance(response, (RedirectResponse, StreamingResponse)):
                return response

            # Read response body
            body = b""
            async for chunk in response.__dict__.get("body_iterator", []):
                body += chunk

            # If response is already wrapped or empty, skip
            if not body:
                return response

            try:
                data = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return response

            # Wrap successful responses
            if response.status_code < 400:
                wrapped = {
                    "code": 200,
                    "data": data,
                    "message": "success",
                }
            else:
                # Wrap error responses
                wrapped = {
                    "code": response.status_code,
                    "data": None,
                    "message": data.get("detail", str(data)) if isinstance(data, dict) else str(data),
                }

            return JSONResponse(
                content=wrapped,
                status_code=200,  # Always return 200 for wrapped responses
            )

        except Exception as exc:
            # Catch any unhandled exceptions
            return JSONResponse(
                content={
                    "code": 500,
                    "data": None,
                    "message": f"Internal server error: {str(exc)}",
                },
                status_code=200,
            )
