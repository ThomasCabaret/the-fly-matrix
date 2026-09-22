from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DATA = {
    "body-annotations-male-cns-v1.0-minconf-0.5.feather": 14_483_314,
    "body-neurotransmitters-male-cns-v1.0.feather": 43_282_834,
    "connectome-weights-male-cns-v1.0-minconf-0.5.feather": 1_051_241_946,
    "optic-column-type-assignments-v1.0.xlsx": 111_565,
}


class ScaffoldTests(unittest.TestCase):
    def test_project_name_and_python_range(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        self.assertEqual(project["name"], "the-fly-matrix")
        self.assertEqual(project["requires-python"], ">=3.12,<3.13")

    def test_ledger_categories_exist(self) -> None:
        for category in ("boxes", "groups", "wires", "parameter_families", "validations"):
            folder = ROOT / "ledger" / category
            self.assertTrue(folder.is_dir(), category)
            self.assertTrue((folder / "_template.yaml").is_file(), category)

    def test_downloaded_data_have_exact_sizes(self) -> None:
        data_root = ROOT / "data" / "raw" / "malecns" / "v1.0"
        for name, expected_bytes in EXPECTED_DATA.items():
            path = data_root / name
            if path.exists():
                self.assertEqual(path.stat().st_size, expected_bytes, name)

    def test_user_facing_batch_scripts_pause(self) -> None:
        for name in (
            "download_data.bat",
            "setup.bat",
            "setup_gpu.bat",
            "status.bat",
            "verify_install.bat",
            "run_analysis.bat",
            "build_preview.bat",
            "dashboard.bat",
        ):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("pause", content.lower(), name)


if __name__ == "__main__":
    unittest.main()
