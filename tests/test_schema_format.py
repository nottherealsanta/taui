"""Tests for taui.tools.schema_format — JSON-schema parameter rendering."""

from __future__ import annotations

from taui.tools.schema_format import (
    SchemaParam,
    format_schema_type,
    schema_param_rows,
)


class TestFormatSchemaType:
    def test_enum(self):
        assert format_schema_type({"enum": ["a", "b", "c"]}) == "one of: a | b | c"

    def test_enum_takes_precedence_over_type(self):
        assert format_schema_type({"type": "string", "enum": ["x"]}) == "one of: x"

    def test_simple_type(self):
        assert format_schema_type({"type": "string"}) == "string"

    def test_union_type(self):
        assert format_schema_type({"type": ["string", "null"]}) == "string | null"

    def test_array_with_items(self):
        assert format_schema_type(
            {"type": "array", "items": {"type": "string"}}
        ) == "array<string>"

    def test_array_without_items(self):
        assert format_schema_type({"type": "array"}) == "array<any>"

    def test_nested_array(self):
        assert format_schema_type(
            {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}
        ) == "array<array<integer>>"

    def test_missing_type_is_any(self):
        assert format_schema_type({}) == "any"

    def test_empty_enum_falls_back_to_type(self):
        assert format_schema_type({"enum": [], "type": "number"}) == "number"


class TestSchemaParamRows:
    def test_non_mapping_returns_empty(self):
        assert schema_param_rows(None) == []
        assert schema_param_rows("not a schema") == []

    def test_no_properties_returns_empty(self):
        assert schema_param_rows({"type": "object"}) == []

    def test_required_listed_before_optional(self):
        schema = {
            "type": "object",
            "properties": {
                "opt1": {"type": "string"},
                "req1": {"type": "string"},
                "opt2": {"type": "string"},
                "req2": {"type": "string"},
            },
            "required": ["req1", "req2"],
        }
        rows = schema_param_rows(schema)
        # Required first (declaration order), then optional (declaration order).
        assert [r.name for r in rows] == ["req1", "req2", "opt1", "opt2"]
        assert [r.required for r in rows] == [True, True, False, False]

    def test_captures_description_and_default(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "  how many  ",
                    "default": 10,
                },
            },
        }
        rows = schema_param_rows(schema)
        assert rows == [
            SchemaParam(
                name="count",
                type_label="integer",
                required=False,
                description="how many",
                default=10,
            )
        ]

    def test_required_accepts_non_list_iterables(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ("b",),
        }
        rows = schema_param_rows(schema)
        assert rows[0].name == "b" and rows[0].required is True
        assert rows[1].name == "a" and rows[1].required is False
