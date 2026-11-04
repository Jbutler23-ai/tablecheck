"""CSV validation and the command-line entry point. Runtime uses only the stdlib."""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


class InputError(ValueError):
    """A schema or input could not be read or interpreted."""


TYPES = {"string", "integer", "number", "boolean"}
INTEGER = re.compile(r"[+-]?[0-9]+")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _matches(value, kind):
    if kind == "number":
        return _finite_number(value)
    return type(value) is {"string": str, "integer": int, "boolean": bool}[kind]


def _unknown_fields(value, allowed, where):
    unknown = set(value) - allowed
    if unknown:
        raise InputError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def validate_schema(schema):
    """Validate our schema format, returning the original mapping unchanged."""
    if not isinstance(schema, dict):
        raise InputError("schema must be a JSON object")
    _unknown_fields(schema, {"columns", "allow_extra_columns"}, "schema")
    if type(schema.get("allow_extra_columns", False)) is not bool:
        raise InputError("allow_extra_columns must be a boolean")
    columns = schema.get("columns")
    if not isinstance(columns, list) or not columns:
        raise InputError("columns must be a nonempty array")
    names = set()
    for index, column in enumerate(columns):
        where = f"columns[{index}]"
        if not isinstance(column, dict):
            raise InputError(f"{where} must be an object")
        _unknown_fields(column, {"name", "type", "required", "min", "max", "choices"}, where)
        name = column.get("name")
        if not isinstance(name, str) or not name.strip():
            raise InputError(f"{where}.name must be a nonempty string")
        if name in names:
            raise InputError(f"{where}.name duplicates {name!r}")
        names.add(name)
        kind = column.get("type")
        if not isinstance(kind, str) or kind not in TYPES:
            raise InputError(f"{where}.type must be string, integer, number, or boolean")
        if type(column.get("required", False)) is not bool:
            raise InputError(f"{where}.required must be a boolean")
        for bound in ("min", "max"):
            if bound in column:
                if kind not in {"integer", "number"} or not _finite_number(column[bound]):
                    raise InputError(f"{where}.{bound} requires a finite numeric bound and numeric type")
        if "min" in column and "max" in column and column["min"] > column["max"]:
            raise InputError(f"{where}.min cannot exceed max")
        if "choices" in column:
            choices = column["choices"]
            if not isinstance(choices, list) or not choices:
                raise InputError(f"{where}.choices must be a nonempty array")
            if any(not _matches(choice, kind) for choice in choices):
                raise InputError(f"{where}.choices must contain only {kind} values")
            if len(set(choices)) != len(choices):
                raise InputError(f"{where}.choices contains duplicate values")
            for choice in choices:
                if ("min" in column and choice < column["min"]) or (
                    "max" in column and choice > column["max"]
                ):
                    raise InputError(f"{where}.choices contains a value outside min/max")
    return schema


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"schema contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise InputError(f"schema contains nonstandard JSON number {value}")


def load_schema(path):
    try:
        with Path(path).open(encoding="utf-8-sig") as stream:
            schema = json.load(stream, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise InputError(f"cannot read schema {str(path)!r}: {error}") from error
    return validate_schema(schema)


def _parse_cell(raw, kind):
    if kind == "string":
        return raw
    value = raw.strip()
    if kind == "boolean" and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if kind == "integer" and INTEGER.fullmatch(value):
        return int(value)
    if kind == "number" and NUMBER.fullmatch(value):
        number = float(value)
        if math.isfinite(number):
            return number
    raise ValueError(f"expected {kind}")


def check_csv(path, schema):
    """Return all data issues. Row numbers refer to physical record start lines."""
    validate_schema(schema)
    issues = []
    row_count = 0

    def issue(code, message, row, column=None):
        issues.append({"code": code, "message": message, "row": row, "column": column})

    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None:
                issue("missing_header", "CSV is empty; expected a header row", 1)
            else:
                counts = Counter(header)
                for name, count in counts.items():
                    if not name.strip():
                        issue("blank_header", "header name is empty or whitespace", 1, name)
                    if count > 1:
                        issue("duplicate_header", f"header appears {count} times", 1, name)
                expected = {column["name"] for column in schema["columns"]}
                for column in schema["columns"]:
                    if column["name"] not in counts:
                        issue("missing_header", "schema column is missing", 1, column["name"])
                if not schema.get("allow_extra_columns", False):
                    for name in counts:
                        if name not in expected:
                            issue("extra_header", "column is not declared in schema", 1, name)
                # Ambiguous duplicate headers cannot safely identify a cell.
                positions = {name: index for index, name in enumerate(header) if counts[name] == 1}
                while True:
                    row_number = reader.line_num + 1
                    row = next(reader, None)
                    if row is None:
                        break
                    row_count += 1
                    if len(row) != len(header):
                        issue("row_length", f"expected {len(header)} cells, found {len(row)}", row_number)
                    for column in schema["columns"]:
                        name = column["name"]
                        position = positions.get(name)
                        if position is None or position >= len(row):
                            continue
                        raw = row[position]
                        if not raw.strip():
                            if column.get("required", False):
                                issue("required", "required cell is blank", row_number, name)
                            continue
                        try:
                            value = _parse_cell(raw, column["type"])
                        except (ValueError, OverflowError):
                            issue("type", f"expected {column['type']}", row_number, name)
                            continue
                        if "min" in column and value < column["min"]:
                            issue("min", f"value is below {column['min']}", row_number, name)
                        if "max" in column and value > column["max"]:
                            issue("max", f"value exceeds {column['max']}", row_number, name)
                        if "choices" in column and value not in column["choices"]:
                            issue("choices", "value is not an allowed choice", row_number, name)
    except (OSError, UnicodeError, csv.Error) as error:
        raise InputError(f"cannot read CSV {str(path)!r}: {error}") from error
    return {"file": str(path), "row_count": row_count, "issue_count": len(issues), "issues": issues}


def render_text(report):
    lines = [f"{report['file']}: {report['row_count']} data row(s), {report['issue_count']} issue(s)"]
    for issue in report["issues"]:
        location = f"row {issue['row']}"
        if issue["column"] is not None:
            location += f", column {issue['column']!r}"
        lines.append(f"{location}: [{issue['code']}] {issue['message']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check CSV data against an explicit JSON schema.")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        report = check_csv(args.csv_file, load_schema(args.schema))
    except InputError as error:
        if args.format == "json":
            print(json.dumps({"error": str(error)}), file=sys.stderr)
        else:
            print(f"tablecheck: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.format == "json" else render_text(report))
    return 1 if report["issues"] else 0
