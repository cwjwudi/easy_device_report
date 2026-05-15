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
