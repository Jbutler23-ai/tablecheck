import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tablecheck.cli import InputError, check_csv, load_schema, main, validate_schema


class TablecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schema = {"columns": [
            {"name": "id", "type": "integer", "required": True, "min": 1},
            {"name": "name", "type": "string", "required": True},
        ]}

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def check(self, text, schema=None):
        return check_csv(self.write("data.csv", text), self.schema if schema is None else schema)

    def codes(self, report):
        return [issue["code"] for issue in report["issues"]]

    def test_clean_quoted_csv_and_read_only_behavior(self):
        path = self.write("data.csv", 'id,name\r\n1,"Lantern, blue"\r\n')
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        report = check_csv(path, self.schema)
        self.assertEqual(report["row_count"], 1)
        self.assertEqual(report["issues"], [])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_bom_in_schema_and_csv(self):
        schema_path = self.write("schema.json", "\ufeff" + json.dumps(self.schema))
        report = self.check("\ufeffid,name\n1,Torch\n", load_schema(schema_path))
        self.assertEqual(report["issues"], [])

    def test_missing_duplicate_extra_and_blank_headers(self):
        report = self.check("id,id,unexpected,\n1,2,x,y\n")
        self.assertCountEqual(self.codes(report), [
            "duplicate_header", "blank_header", "missing_header", "extra_header", "extra_header",
        ])
        self.assertTrue(all(issue["row"] == 1 for issue in report["issues"]))

    def test_extra_columns_can_be_allowed(self):
        self.schema["allow_extra_columns"] = True
        self.assertEqual(self.check("id,name,note\n1,Torch,test\n")["issues"], [])

    def test_short_and_long_records(self):
        report = self.check("id,name\n1\n2,Torch,extra\n")
        self.assertEqual(self.codes(report), ["row_length", "row_length"])
        self.assertEqual([issue["row"] for issue in report["issues"]], [2, 3])

    def test_required_and_optional_blank_cells(self):
        report = self.check("id,name\n1,  \n,Thing\n")
        self.assertEqual(self.codes(report), ["required", "required"])
        self.schema["columns"][1]["required"] = False
        self.assertEqual(self.check("id,name\n1, \n")["issues"], [])

    def test_integer_syntax_rejects_decimal_and_underscores(self):
        report = self.check("id,name\n1.0,Torch\n1_000,Rope\n+2,Key\n")
        self.assertEqual(self.codes(report), ["type", "type"])

    def test_number_bounds_choices_and_boolean(self):
        schema = {"columns": [
            {"name": "weight", "type": "number", "min": 0, "max": 2},
            {"name": "kind", "type": "string", "choices": ["tool", "food"]},
            {"name": "enabled", "type": "boolean"},
        ]}
        report = self.check("weight,kind,enabled\n-1,magic,yes\n3,tool,FALSE\n.5,food,true\n", schema)
        self.assertEqual(self.codes(report), ["min", "choices", "type", "max"])

    def test_nonfinite_and_nondecimal_numbers_rejected(self):
        schema = {"columns": [{"name": "n", "type": "number"}]}
        report = self.check("n\nnan\nInfinity\n1e9999\n1_000\n0x10\n1e-3\n", schema)
        self.assertEqual(self.codes(report), ["type"] * 5)

    def test_typed_choices(self):
        schema = {"columns": [
            {"name": "n", "type": "number", "choices": [0.5, 2]},
            {"name": "b", "type": "boolean", "choices": [True]},
        ]}
        report = self.check("n,b\n.5,TRUE\n2,false\n3,true\n", schema)
        self.assertEqual(self.codes(report), ["choices", "choices"])

    def test_physical_line_numbers_after_multiline_record(self):
        report = self.check('id,name\n1,"First\nsecond"\nwrong,Torch\n')
        self.assertEqual(report["row_count"], 2)
        self.assertEqual(report["issues"][0]["row"], 4)

    def test_blank_physical_record_is_a_length_issue(self):
        report = self.check("id,name\n\n1,Torch\n")
        self.assertEqual(report["row_count"], 2)
        self.assertEqual(self.codes(report), ["row_length"])
        self.assertEqual(report["issues"][0]["row"], 2)

    def test_empty_csv_and_header_only(self):
        self.assertEqual(self.codes(self.check("")), ["missing_header"])
        self.assertEqual(self.check("id,name\n")["issues"], [])

    def test_malformed_csv_and_invalid_encoding_are_input_errors(self):
        with self.assertRaises(InputError):
            self.check('id,name\n1,"unclosed\n')
        path = self.root / "bad.csv"
        path.write_bytes(b"id,name\n1,\xff\n")
        with self.assertRaises(InputError):
            check_csv(path, self.schema)

    def test_invalid_schemas_are_rejected(self):
        cases = [
            [], {}, {"columns": []}, {"columns": [None]},
            {"columns": self.schema["columns"], "colums": []},
            {"columns": self.schema["columns"], "allow_extra_columns": 1},
            {"columns": [{"name": "id", "type": "integer", "requried": True}]},
            {"columns": [{"name": " ", "type": "string"}]},
            {"columns": [{"name": "x", "type": "date"}]},
            {"columns": [{"name": "x", "type": []}]},
            {"columns": [{"name": "x", "type": "integer", "required": 1}]},
            {"columns": [self.schema["columns"][0]] * 2},
            {"columns": [{"name": "x", "type": "string", "min": 1}]},
            {"columns": [{"name": "x", "type": "number", "max": True}]},
            {"columns": [{"name": "x", "type": "number", "min": float("inf")}]},
            {"columns": [{"name": "x", "type": "integer", "min": 2, "max": 1}]},
            {"columns": [{"name": "x", "type": "integer", "choices": [True]}]},
            {"columns": [{"name": "x", "type": "boolean", "choices": [1]}]},
            {"columns": [{"name": "x", "type": "string", "choices": []}]},
            {"columns": [{"name": "x", "type": "string", "choices": ["a", "a"]}]},
            {"columns": [{"name": "x", "type": "integer", "min": 1, "choices": [0]}]},
        ]
        for schema in cases:
            with self.subTest(schema=schema), self.assertRaises(InputError):
                validate_schema(schema)

    def test_schema_json_errors_and_missing_file(self):
        for content in ('{"columns":', '{"columns": [], "columns": []}', '{"columns": NaN}'):
            with self.subTest(content=content), self.assertRaises(InputError):
                load_schema(self.write("bad.json", content))
        with self.assertRaises(InputError):
            load_schema(self.root / "missing.json")

    def test_schema_parser_resource_limits_are_input_errors(self):
        with self.assertRaises(InputError):
            load_schema(self.write("nested.json", "[" * 2000 + "]" * 2000))
        if hasattr(sys, "get_int_max_str_digits") and sys.get_int_max_str_digits():
            huge_integer = "9" * (sys.get_int_max_str_digits() + 1)
            with self.assertRaises(InputError):
                load_schema(self.write("large.json", '{"columns": ' + huge_integer + '}'))

    def test_cli_reports_and_exit_codes(self):
        schema_path = self.write("schema.json", json.dumps(self.schema))
        for csv_text, status in (("id,name\n1,Torch\n", 0), ("id,name\nwrong,Torch\n", 1)):
            csv_path = self.write("data.csv", csv_text)
            output = io.StringIO()
            with self.subTest(status=status), contextlib.redirect_stdout(output):
                self.assertEqual(main([str(csv_path), "--schema", str(schema_path), "--format", "json"]), status)
            self.assertEqual(json.loads(output.getvalue())["issue_count"], status)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main([str(self.root / "missing.csv"), "--schema", str(schema_path), "--format", "json"]), 2)
        self.assertIn("cannot read CSV", json.loads(errors.getvalue())["error"])

    def test_module_entry_point_in_real_process(self):
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run([
            sys.executable, "-m", "tablecheck", str(project / "examples" / "items.csv"),
            "--schema", str(project / "examples" / "items.schema.json"),
        ], cwd=project / "src", text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 data row(s), 0 issue(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
