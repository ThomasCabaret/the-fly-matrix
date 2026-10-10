from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "reproduction-pipeline.md"


class ReproductionPipelineTests(unittest.TestCase):
    def test_documented_batch_entry_points_exist(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        commands = sorted(set(re.findall(r"(?m)^([A-Za-z0-9_.-]+\.bat)(?:\s|$)", text)))
        self.assertGreater(len(commands), 20)
        missing = [command for command in commands if not (ROOT / command).is_file()]
        self.assertEqual(missing, [])

    def test_reference_readiness_claim_matches_calibration_state(self) -> None:
        state = yaml.safe_load(
            (ROOT / "calibration" / "state.yaml").read_text(encoding="utf-8")
        )
        text = RUNBOOK.read_text(encoding="utf-8")
        no_reference_claim = bool(
            re.search(
                r"(?m)^\| Calibrated reference fly \|.*\| \*\*No\.\*\*.*\|$",
                text,
            )
        )
        has_reference = bool(
            state.get("reference_parameter_set_id")
            or state.get("last_promoted_parameter_set_id")
        )
        self.assertEqual(no_reference_claim, not has_reference)

    def test_primary_readmes_link_the_canonical_runbook(self) -> None:
        for relative_path in ("README.md", "PROJECT_STATE.md", "calibration/README.md"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("reproduction-pipeline.md", text, relative_path)


if __name__ == "__main__":
    unittest.main()
