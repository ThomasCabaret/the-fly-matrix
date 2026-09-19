from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from the_fly_matrix.config import ROOT, read_env_file


class ConfigTests(unittest.TestCase):
    def test_env_parser_splits_only_on_first_equals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nNEUPRINT_SERVER=https://example.test\n"
                "NEUPRINT_APPLICATION_CREDENTIALS=abc=def==\n",
                encoding="utf-8",
            )
            values = read_env_file(path)
        self.assertEqual(values["NEUPRINT_SERVER"], "https://example.test")
        self.assertEqual(values["NEUPRINT_APPLICATION_CREDENTIALS"], "abc=def==")

    def test_generated_neuprint_audit_never_contains_local_credential(self) -> None:
        env_path = ROOT / ".env"
        audit_path = ROOT / "data" / "derived" / "inventory" / "neuprint-audit.json"
        if not env_path.is_file() or not audit_path.is_file():
            self.skipTest("local neuPrint configuration or audit is absent")
        token = read_env_file(env_path).get("NEUPRINT_APPLICATION_CREDENTIALS", "")
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertFalse(bool(token and token in audit_text), "credential leaked into audit")
        audit = json.loads(audit_text)
        self.assertFalse(audit["credential_persisted"])
        self.assertTrue(all(item["exact_match"] for item in audit["group_comparisons"]))

    def test_generated_roi_audit_never_contains_local_credential(self) -> None:
        env_path = ROOT / ".env"
        audit_path = ROOT / "data" / "derived" / "inventory" / "roi-audit.json"
        if not env_path.is_file() or not audit_path.is_file():
            self.skipTest("local neuPrint configuration or ROI audit is absent")
        token = read_env_file(env_path).get("NEUPRINT_APPLICATION_CREDENTIALS", "")
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertFalse(bool(token and token in audit_text), "credential leaked into ROI audit")
        audit = json.loads(audit_text)
        self.assertFalse(audit["credential_persisted"])
        self.assertEqual(len(audit["groups"]), 7)
        self.assertTrue(all(item["neurons"] > 0 for item in audit["groups"]))
        self.assertTrue(
            all(0 <= item["primary_roi_coverage_percent"] <= 100 for item in audit["groups"])
        )


if __name__ == "__main__":
    unittest.main()
