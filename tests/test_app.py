import unittest
import sqlite3
import tempfile
from uuid import uuid4
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, init_app_db, init_demo_db, seed_defaults


class ReportAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_app_db()
        init_demo_db()
        seed_defaults()
        cls.client = TestClient(app)

    def sqlite_template(self):
        templates = self.client.get("/api/report-templates").json()
        return next(item for item in templates if item.get("config", {}).get("database", {}).get("type") == "sqlite")

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["field_mysql"]["password"], "***")

    def test_static_defaults_do_not_embed_field_credentials(self):
        html = Path("static/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Br54644800@", html)
        self.assertNotIn("192.168.50.22", html)
        self.assertNotIn("opc.tcp://192.168.50.233:4840", html)

    def test_opcua_mock_read(self):
        response = self.client.post(
            "/api/opcua/read",
            json={
                "server_url": "mock://local",
                "nodes": ["batch_no", "shift"],
                "node_values": {"batch_no": "B20260514", "shift": "A"},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["values"]["batch_no"], "B20260514")

    def test_database_preview(self):
        health = self.client.get("/api/health").json()
        response = self.client.post(
            "/api/database/query-preview",
            json={
                "connection": {"type": "sqlite", "path": health["demo_db"]},
                "table": "production_records",
                "columns": ["record_time", "line_name", "quantity"],
                "filters": [{"column": "batch_no", "operator": "=", "value": "B20260514"}],
                "order_by": [{"column": "record_time", "direction": "ASC"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["row_count"], 1)
        self.assertEqual(body["columns"][0]["name"], "record_time")

    def test_database_preview_decimal_places(self):
        health = self.client.get("/api/health").json()
        response = self.client.post(
            "/api/database/query-preview",
            json={
                "connection": {"type": "sqlite", "path": health["demo_db"]},
                "table": "production_records",
                "columns": [
                    {"name": "record_time", "label": "时间", "decimal_places": 2},
                    {"name": "quantity", "label": "数量", "decimal_places": 1},
                    {"name": "temperature", "label": "温度", "decimal_places": 2},
                ],
                "limit": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["columns"][2]["decimal_places"], 2)
        self.assertNotRegex(body["rows"][0]["record_time"], r"\.\d{2}$")
        self.assertRegex(body["rows"][0]["quantity"], r"^-?\d+\.\d{1}$")
        self.assertRegex(body["rows"][0]["temperature"], r"^-?\d+\.\d{2}$")

    def test_generate_report_decimal_places(self):
        template = self.sqlite_template()["config"]
        template["body"] = {
            "tables": [
                {
                    "id": "q_decimal",
                    "kind": "query",
                    "name": "小数位测试",
                    "table": "production_records",
                    "columns": [
                        {"name": "record_time", "label": "时间", "decimal_places": 2},
                        {"name": "quantity", "label": "数量", "decimal_places": 1},
                        {"name": "temperature", "label": "温度", "decimal_places": 2},
                    ],
                    "filters": [],
                    "order_by": [],
                    "limit": 1,
                }
            ]
        }
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        table = response.json()["body"]["tables"][0]
        row = table["rows"][0]
        self.assertEqual(table["columns"][1]["decimal_places"], 1)
        self.assertEqual(table["columns"][2]["decimal_places"], 2)
        self.assertNotRegex(row["record_time"], r"\.\d{2}$")
        self.assertRegex(row["quantity"], r"^-?\d+\.\d{1}$")
        self.assertRegex(row["temperature"], r"^-?\d+\.\d{2}$")

    def test_database_schema_returns_all_tables(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "many_tables.sqlite"
            with sqlite3.connect(db_path) as conn:
                for index in range(55):
                    conn.execute(f"CREATE TABLE t_{index:02d} (id INTEGER)")
            response = self.client.post(
                "/api/database/schema",
                json={"type": "sqlite", "path": str(db_path)},
            )
            body = response.json()
        self.assertEqual(response.status_code, 200)
        table_names = [table["table"] for table in body["tables"]]
        self.assertEqual(len(table_names), 55)
        self.assertIn("t_54", table_names)

    def test_generate_sample_report(self):
        template = self.sqlite_template()
        response = self.client.post("/api/reports/generate", json={"template_id": template["id"], "persist_run": False})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertIn("header", report)
        self.assertIn("body", report)
        self.assertIn("footer", report)
        self.assertGreaterEqual(report["body"]["row_count"], 1)

    def test_generate_body_custom_table(self):
        template = self.sqlite_template()["config"]
        template["body"]["custom_tables"] = [
            {
                "title": "body custom",
                "rows": [
                    [{"type": "static", "value": "row count"}, {"type": "db_summary", "aggregate": "count"}],
                    [{"type": "static", "value": "first line"}, {"type": "db_field", "column": "line_name"}],
                ],
            }
        ]
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        table = response.json()["body"]["custom_tables"][0]
        self.assertEqual(table["title"], "body custom")
        self.assertEqual(table["rows"][0][0], "row count")
        self.assertGreaterEqual(table["rows"][0][1], 1)

    def test_pdf_repeat_header_footer_flags(self):
        template = self.sqlite_template()["config"]
        template["header"]["repeat_pdf_each_page"] = True
        template["footer"]["repeat_pdf_each_page"] = True
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertTrue(report["header"]["repeat_pdf_each_page"])
        self.assertTrue(report["footer"]["repeat_pdf_each_page"])

        pdf_response = self.client.post("/api/reports/export/pdf", json={"template": template, "persist_run": False})
        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn("application/pdf", pdf_response.headers["content-type"])
        self.assertGreater(len(pdf_response.content), 100)

    def test_empty_header_footer_are_allowed(self):
        template = self.sqlite_template()["config"]
        template["header"]["rows"] = []
        template["footer"]["rows"] = []
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["header"]["rows"], [])
        self.assertEqual(report["footer"]["rows"], [])

    def test_generate_body_tables_multi_query(self):
        template = self.sqlite_template()["config"]
        legacy = template["body"]
        template["body"] = {
            "tables": [
                {
                    "id": "q_main",
                    "kind": "query",
                    "title": "主查询",
                    "table": legacy.get("table", "production_records"),
                    "columns": legacy.get("columns", []),
                    "filters": legacy.get("filters", []),
                    "order_by": legacy.get("order_by", []),
                    "limit": legacy.get("limit", 100),
                },
                {
                    "id": "q_alt",
                    "kind": "query",
                    "title": "辅查询",
                    "table": legacy.get("table", "production_records"),
                    "columns": legacy.get("columns", []),
                    "filters": [],
                    "order_by": [],
                    "limit": 5,
                },
                {
                    "id": "c_one",
                    "kind": "custom",
                    "title": "自定义表",
                    "rows": [
                        [
                            {"type": "static", "value": "main count"},
                            {"type": "db_summary", "aggregate": "count", "source_id": "q_main"},
                        ],
                        [
                            {"type": "static", "value": "alt count"},
                            {"type": "db_summary", "aggregate": "count", "source_id": "q_alt"},
                        ],
                        [
                            {"type": "static", "value": "alt first line"},
                            {"type": "db_field", "column": "line_name", "source_id": "q_alt"},
                        ],
                    ],
                },
            ]
        }
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        body = response.json()["body"]
        self.assertIn("tables", body)
        kinds = [t["kind"] for t in body["tables"]]
        self.assertEqual(kinds, ["query", "query", "custom"])
        q_main = body["tables"][0]
        q_alt = body["tables"][1]
        custom = body["tables"][2]
        self.assertEqual(q_main["title"], "主查询")
        self.assertGreaterEqual(q_main["row_count"], 1)
        self.assertLessEqual(q_alt["row_count"], 5)
        # source-aware cell resolution
        self.assertEqual(custom["rows"][0][1], q_main["row_count"])
        self.assertEqual(custom["rows"][1][1], q_alt["row_count"])
        if q_alt["rows"]:
            self.assertEqual(custom["rows"][2][1], q_alt["rows"][0].get("line_name", ""))

    def test_body_table_order_is_preserved(self):
        template = self.sqlite_template()["config"]
        legacy = template["body"]
        template["body"] = {
            "tables": [
                {
                    "id": "c_first",
                    "kind": "custom",
                    "name": "自定义在前",
                    "rows": [[{"type": "static", "value": "first custom"}]],
                },
                {
                    "id": "q_middle",
                    "kind": "query",
                    "name": "查询在中间",
                    "table": legacy.get("table", "production_records"),
                    "columns": legacy.get("columns", []),
                    "filters": legacy.get("filters", []),
                    "order_by": legacy.get("order_by", []),
                    "limit": 1,
                },
                {
                    "id": "c_last",
                    "kind": "custom",
                    "name": "自定义在后",
                    "rows": [[{"type": "static", "value": "last custom"}]],
                },
            ]
        }
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        tables = response.json()["body"]["tables"]
        self.assertEqual([table["id"] for table in tables], ["c_first", "q_middle", "c_last"])
        self.assertEqual([table["kind"] for table in tables], ["custom", "query", "custom"])

    def test_body_table_setting_name_is_separate_from_print_title(self):
        template = self.sqlite_template()["config"]
        legacy = template["body"]
        template["body"] = {
            "tables": [
                {
                    "id": "q_main",
                    "kind": "query",
                    "name": "配置用名称",
                    "title": "",
                    "table": legacy.get("table", "production_records"),
                    "columns": legacy.get("columns", []),
                    "filters": legacy.get("filters", []),
                    "order_by": legacy.get("order_by", []),
                    "limit": 5,
                }
            ]
        }
        response = self.client.post("/api/reports/generate", json={"template": template, "persist_run": False})
        self.assertEqual(response.status_code, 200)
        table = response.json()["body"]["tables"][0]
        self.assertEqual(table["name"], "配置用名称")
        self.assertEqual(table["title"], "")

    def test_copy_template_uses_numeric_suffix_for_duplicate_name(self):
        base_name = f"复制后缀测试 {uuid4().hex[:8]}"
        created = self.client.post(
            "/api/report-templates",
            json={"name": base_name, "config": {"name": base_name, "body": {}}},
        )
        self.assertEqual(created.status_code, 200)
        created_id = created.json()["id"]
        copy_ids = []
        try:
            first_copy = self.client.post(f"/api/report-templates/{created_id}/copy", json={})
            second_copy = self.client.post(f"/api/report-templates/{created_id}/copy", json={})
            self.assertEqual(first_copy.status_code, 200)
            self.assertEqual(second_copy.status_code, 200)
            copy_ids = [first_copy.json()["id"], second_copy.json()["id"]]
            self.assertEqual(first_copy.json()["name"], f"{base_name} 副本")
            self.assertEqual(second_copy.json()["name"], f"{base_name} 副本 2")
        finally:
            for template_id in copy_ids + [created_id]:
                self.client.delete(f"/api/report-templates/{template_id}")

    def test_export_files(self):
        template = self.sqlite_template()
        for fmt, content_type in [
            ("html", "text/html"),
            ("excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("pdf", "application/pdf"),
        ]:
            response = self.client.post(f"/api/reports/export/{fmt}", json={"template_id": template["id"], "persist_run": False})
            self.assertEqual(response.status_code, 200)
            self.assertIn(content_type, response.headers["content-type"])
            self.assertGreater(len(response.content), 100)


if __name__ == "__main__":
    unittest.main()
