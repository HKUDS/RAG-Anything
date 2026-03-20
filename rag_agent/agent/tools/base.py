"""Base abstraction for tools used by the RAG agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Abstract base class for all agent tools."""

    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name exposed to the LLM function-calling interface."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short user-facing description of this tool."""

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON schema for tool parameters."""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the tool and return a string result."""

    def to_schema(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cast raw LLM arguments into schema-aligned Python values."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object" or not isinstance(params, dict):
            return params

        props = schema.get("properties", {})
        result: dict[str, Any] = {}
        for key, value in params.items():
            child_schema = props.get(key)
            result[key] = self._cast_value(value, child_schema) if child_schema else value
        return result

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate required fields and basic types. Return an error list."""
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]

        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return ["tool schema must be an object"]

        return self._validate_value(params, schema, "parameter")

    def _cast_value(self, value: Any, schema: dict[str, Any]) -> Any:
        expected_type = schema.get("type")

        if expected_type == "integer" and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value

        if expected_type == "number" and isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return value

        if expected_type == "boolean" and isinstance(value, str):
            lowered = value.lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no"):
                return False
            return value

        if expected_type == "string":
            return value if value is None else str(value)

        if expected_type == "array" and isinstance(value, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                return [self._cast_value(item, item_schema) for item in value]
            return value

        if expected_type == "object" and isinstance(value, dict):
            props = schema.get("properties", {})
            casted: dict[str, Any] = {}
            for k, v in value.items():
                child_schema = props.get(k)
                casted[k] = self._cast_value(v, child_schema) if child_schema else v
            return casted

        return value

    def _validate_value(self, value: Any, schema: dict[str, Any], label: str) -> list[str]:
        errors: list[str] = []
        expected_type = schema.get("type")

        if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return [f"{label} should be integer"]
        if expected_type == "number" and (
            not isinstance(value, self._TYPE_MAP["number"]) or isinstance(value, bool)
        ):
            return [f"{label} should be number"]
        if expected_type in ("string", "boolean", "array", "object"):
            if not isinstance(value, self._TYPE_MAP[expected_type]):
                return [f"{label} should be {expected_type}"]

        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            errors.append(f"{label} must be one of {enum_values}")

        if expected_type == "object":
            props = schema.get("properties", {})
            for key in schema.get("required", []):
                if key not in value:
                    errors.append(f"missing required {key} in {label}")
            for key, child in value.items():
                child_schema = props.get(key)
                if isinstance(child_schema, dict):
                    errors.extend(self._validate_value(child, child_schema, f"{label}.{key}"))

        if expected_type == "array":
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for idx, item in enumerate(value):
                    errors.extend(self._validate_value(item, item_schema, f"{label}[{idx}]"))

        return errors
