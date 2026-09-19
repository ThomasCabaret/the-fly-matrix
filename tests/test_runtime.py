from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.runtime import BasalClampBox, CNSInputBuffer, CHANNEL_PATH, ROUTE_PATH


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        if not CHANNEL_PATH.is_file() or not ROUTE_PATH.is_file():
            self.skipTest("generated basal clamp wiring is absent")

    def test_basal_clamps_execute_every_exact_route(self) -> None:
        olfaction = BasalClampBox.from_generated_wiring("clamp.olfaction")
        gustation = BasalClampBox.from_generated_wiring("clamp.gustation")
        thermohygro = BasalClampBox.from_generated_wiring("clamp.thermohygro")
        olfactory_values = np.arange(len(olfaction.channel_ids), dtype=np.float64)
        gustatory_values = np.arange(len(gustation.channel_ids), dtype=np.float64) + 1000
        thermohygro_values = np.arange(len(thermohygro.channel_ids), dtype=np.float64) + 2000
        olfactory_output = olfaction.step(olfactory_values)
        gustatory_output = gustation.step(gustatory_values)
        thermohygro_output = thermohygro.step(thermohygro_values)
        merged = CNSInputBuffer.merge(olfactory_output, gustatory_output, thermohygro_output)
        self.assertEqual(len(olfactory_output.body_ids), 2639)
        self.assertEqual(len(gustatory_output.body_ids), 1428)
        self.assertEqual(len(thermohygro_output.body_ids), 91)
        self.assertEqual(len(merged.body_ids), 4158)
        self.assertEqual(len(np.unique(merged.body_ids)), 4158)

    def test_basal_clamp_rejects_incomplete_parameter_vector(self) -> None:
        box = BasalClampBox.from_generated_wiring("clamp.olfaction")
        with self.assertRaises(ValueError):
            box.step(np.zeros(len(box.channel_ids) - 1))

    def test_cns_ingress_sums_duplicate_sources_deterministically(self) -> None:
        box = BasalClampBox.from_generated_wiring("clamp.gustation")
        values = np.ones(len(box.channel_ids), dtype=np.float64)
        activity = box.step(values)
        merged = CNSInputBuffer.merge(activity, activity)
        self.assertTrue(np.all(merged.values == 2.0))


if __name__ == "__main__":
    unittest.main()
