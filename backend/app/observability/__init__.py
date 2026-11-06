"""Observability boundary: request ID tracking and redacted metadata helpers.

Per ARCHITECTURE.md section 2 & 8:
- Attach a stable request_id to every request/response.
- Never log raw API keys or sensitive credentials.
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Ensure every HTTP request and response carries a correlation request_id."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_id = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming_id or f"req_{uuid4().hex[:12]}"
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
