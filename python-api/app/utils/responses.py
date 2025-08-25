"""Custom response handlers for FastAPI."""

from typing import Any
import orjson
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.utils.json_utils import CustomORJSONResponse


class CustomJSONResponse(JSONResponse):
    """Custom JSON response that properly handles datetime and other special types."""
    
    def render(self, content: Any) -> bytes:
        """Render response content to bytes."""
        return CustomORJSONResponse.serialize(content)


class SafeORJSONResponse(Response):
    """Safe ORJSON response that handles all special types."""
    
    media_type = "application/json"
    
    def render(self, content: Any) -> bytes:
        """Render response content to bytes."""
        return CustomORJSONResponse.serialize(content)