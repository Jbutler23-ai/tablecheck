# Tablecheck

A small Python CLI that checks a CSV file against an explicit JSON schema. It reports header problems, uneven rows, blank required cells, invalid types, out-of-range numbers, and disallowed choices. It reads input files without modifying them and makes no network requests.

The bundled examples are synthetic. It uses only the Python standard library at runtime and requires Python 3.10 or newer. The included data describes invented game items. It is released under the [MIT License](LICENSE).

## Run it

From this directory:

```sh
python -m pip install -e .
tablecheck examples/items.csv --schema examples/items.schema.json
tablecheck examples/items-invalid.csv --schema examples/items.schema.json --format json
```

The first example reports `3 data row(s), 0 issue(s)`. The second exits with code 1 and reports five issues. `python -m tablecheck` is equivalent to the installed command.

To run directly from source without installing, change into `src` and use:

```sh
python -m tablecheck ../examples/items.csv --schema ../examples/items.schema.json
```

Installation uses setuptools as a build dependency. For an offline install where setuptools is already available, use `python -m pip install --no-build-isolation --no-deps -e .`.

## Schema format

This is Tablecheck's own small schema format, not JSON Schema:

```json
{
  "allow_extra_columns": false,
  "columns": [
    {"name": "id", "type": "integer", "required": true, "min": 1},
    {"name": "label", "type": "string", "required": true},
    {"name": "weight", "type": "number", "min": 0, "max": 100},
    {"name": "enabled", "type": "boolean", "choices": [true]}
  ]
}
```

- `columns` is a nonempty list with unique, nonblank names. Every listed column must have a header in the CSV, even if its cells are optional. Header spelling, spacing, and case must match exactly; column order can vary.
- `type` is `string`, `integer`, `number`, or `boolean`. Integers use signed decimal digits. Numbers accept decimal and scientific notation and must be finite Python floats. Booleans accept `true` and `false`, ignoring case.
- `required` defaults to `false`. Empty and whitespace-only cells skip type and constraint checks unless required. Nonempty strings keep their whitespace. Numeric and boolean cells are trimmed before parsing.
- `min` and `max` are inclusive and apply only to numeric columns. `choices` is a nonempty list of distinct values of the column's type. Numeric choices must also satisfy any bounds.
- `allow_extra_columns` defaults to `false`. Setting it to `true` allows extra headers but does not validate their cells. Duplicate and blank headers still produce issues.

Unknown fields, duplicate JSON keys, invalid types, contradictory bounds, and inconsistent choices are schema errors. Input files must be UTF-8; a leading UTF-8 BOM is accepted. CSV uses commas, double quotes, and standard doubled quote escaping.

## Reports and exit codes

Text reports show each issue's physical starting line, column name when applicable, code, and explanation. Quoted multiline cells count as one record. Blank physical records count as data rows and usually have a row-length issue. A header-only file is valid; an empty file has a missing-header issue. Ambiguous duplicate headers are reported and their cells are skipped. A short row gets a row-length issue; absent cells are not also reported as blank.

JSON reports have `file`, `row_count`, `issue_count`, and `issues`. Each issue has `code`, `message`, `row`, and `column` (or `null`). Successful checks and data reports go to stdout. Input/schema errors go to stderr, as `{"error": "..."}` when `--format json` is selected. Argument syntax errors use argparse's text output.

| Exit code | Meaning |
| --- | --- |
| 0 | Input was checked and no data issues were found |
| 1 | Input was checked and data issues were found |
| 2 | Invalid arguments, schema, encoding, malformed CSV, or unreadable input |

Malformed CSV aborts the check rather than returning a partial report. The parser's standard field-size limit applies. Reports retain all issues in memory, so this starter is intended for small project tables. Number checks use binary floating point; exact decimal arithmetic and row uniqueness rules are not implemented.

## Develop

```sh
python -m unittest discover -s tests -v
```

Tests cover schema validation, quoting, BOMs, physical line numbers, type constraints, reports, exit codes, and preservation of input bytes and modification time. Tests use temporary files and no network. See [ROADMAP.md](ROADMAP.md) for proposed work; those features are not implemented yet.
