"""JSON utilities for handling datetime and other special types."""

import json
from datetime import datetime, date
from decimal import Decimal
from typing import Any
from uuid import UUID

import orjson
from pydantic import BaseModel


def json_serial(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    raise TypeError(f"Type {type(obj)} not serializable")


class CustomORJSONResponse:
    """Custom ORJSON response that handles datetime and other special types."""
    
    @staticmethod
    def default(obj):
        """Default handler for non-serializable objects."""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    @staticmethod
    def serialize(obj: Any) -> bytes:
        """Serialize object to JSON bytes."""
        return orjson.dumps(
            obj,
            default=CustomORJSONResponse.default,
            option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_SERIALIZE_UUID
        )


def safe_json_dumps(obj: Any) -> str:
    """Safely dump object to JSON string, handling special types."""
    if hasattr(obj, 'model_dump'):
        obj = obj.model_dump()
    
    try:
        # Try orjson first (faster)
        return orjson.dumps(
            obj,
            default=CustomORJSONResponse.default,
            option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_SERIALIZE_UUID
        ).decode('utf-8')
    except:
        # Fallback to standard json
        return json.dumps(obj, default=json_serial)


def safe_json_response(data: Any) -> dict:
    """Convert any data to a JSON-safe dictionary."""
    if isinstance(data, BaseModel):
        # Use Pydantic's built-in serialization
        return json.loads(data.model_dump_json())
    elif isinstance(data, dict):
        # Recursively convert dictionary
        return {k: safe_json_response(v) for k, v in data.items()}
    elif isinstance(data, list):
        # Recursively convert list
        return [safe_json_response(item) for item in data]
    elif isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, UUID):
        return str(data)
    elif isinstance(data, Decimal):
        return float(data)
    else:
        return data