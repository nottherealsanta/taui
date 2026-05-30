"""Helpers for rendering JSON-schema tool parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SchemaParam:
    """Display-ready metadata for one JSON-schema object property."""

    name: str
    type_label: str
    required: bool
    description: str = ""
    default: Any = None


def format_schema_type(prop: Mapping[str, Any]) -> str:
    """Render a JSON-schema property's type concisely."""
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        return "one of: " + " | ".join(str(v) for v in enum)
    value_type = prop.get("type")
    if isinstance(value_type, list):
        return " | ".join(str(x) for x in value_type)
    if value_type == "array":
        items = prop.get("items") or {}
        inner = format_schema_type(items) if isinstance(items, Mapping) else "any"
        return f"array<{inner}>"
    return str(value_type) if value_type else "any"


def schema_param_rows(schema: object) -> list[SchemaParam]:
    """Return display rows for a tool's object-parameter schema.

    Required parameters are listed first while preserving declaration order
    within the required and optional groups.
    """
    if not isinstance(schema, Mapping):
        return []
    props = schema.get("properties") or {}
    if not isinstance(props, Mapping) or not props:
        return []

    required_raw = schema.get("required") or []
    if isinstance(required_raw, (list, tuple, set)):
        required = {str(name) for name in required_raw}
    else:
        required = set()
    indexed_props = [
        (idx, str(name), prop) for idx, (name, prop) in enumerate(props.items())
    ]
    indexed_props.sort(key=lambda row: (row[1] not in required, row[0]))

    rows: list[SchemaParam] = []
    for _idx, name, prop in indexed_props:
        prop_map = prop if isinstance(prop, Mapping) else {}
        rows.append(
            SchemaParam(
                name=name,
                type_label=format_schema_type(prop_map),
                required=name in required,
                description=str(prop_map.get("description") or "").strip(),
                default=prop_map.get("default"),
            )
        )
    return rows
