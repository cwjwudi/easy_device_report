import unittest

from fastapi.testclient import TestClient

from app.main import app, init_app_db, init_demo_db, seed_defaults


class ReportAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_app_db()
        init_demo_db()
        seed_defaults()
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

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

    def test_generate_sample_report(self):
        templates = self.client.get("/api/report-templates").json()
        self.assertGreaterEqual(len(templates), 1)
        template = next(item for item in templates if item["config"]["database"]["type"] == "sqlite")
        response = self.client.post("/api/reports/generate", json={"template_id": template["id"], "persist_run": False})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertIn("header", report)
        self.assertIn("body", report)
        self.assertIn("footer", report)
        self.assertGreaterEqual(report["body"]["row_count"], 1)

    def test_generate_body_custom_table(self):
        templates = self.client.get("/api/report-templates").json()
        template = next(item for item in templates if item["config"]["database"]["type"] == "sqlite")["config"]
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
        templates = self.client.get("/api/report-templates").json()
        template = next(item for item in templates if item["config"]["database"]["type"] == "sqlite")["config"]
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

    def test_generate_body_tables_multi_query(self):
        templates = self.client.get("/api/report-templates").json()
        template = next(item for item in templates if item["config"]["database"]["type"] == "sqlite")["config"]
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

    def test_export_files(self):
        templates = self.client.get("/api/report-templates").json()
        template = next(item for item in templates if item["config"]["database"]["type"] == "sqlite")
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
