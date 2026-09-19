from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.runtime import (
    BasalClampBox,
    CHANNEL_PATH,
    CNSInputBuffer,
    MECHANO_CHANNEL_PATH,
    MECHANO_ROUTE_PATH,
    PROPRIO_CHANNEL_PATH,
    PROPRIO_ROUTE_PATH,
    ROUTE_PATH,
    VISION_CHANNEL_PATH,
    VISION_ROUTE_PATH,
    MechanosensationRoutingBox,
    ProprioceptionRoutingBox,
    VisionRoutingBox,
)


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

    def test_proprioception_router_executes_downstream_only(self) -> None:
        if not PROPRIO_CHANNEL_PATH.is_file() or not PROPRIO_ROUTE_PATH.is_file():
            self.skipTest("generated proprioceptive wiring is absent")
        box = ProprioceptionRoutingBox.from_generated_wiring()
        output = box.step(np.arange(len(box.channel_ids), dtype=np.float64))
        self.assertEqual(len(box.channel_ids), 262)
        self.assertEqual(len(output.body_ids), 1454)
        self.assertEqual(len(np.unique(output.body_ids)), 1454)

    def test_mechanosensation_router_executes_both_disjoint_groups(self) -> None:
        if not MECHANO_CHANNEL_PATH.is_file() or not MECHANO_ROUTE_PATH.is_file():
            self.skipTest("generated mechanosensory wiring is absent")
        box = MechanosensationRoutingBox.from_generated_wiring()
        output = box.step(np.arange(len(box.channel_ids), dtype=np.float64))
        self.assertEqual(len(box.channel_ids), 323)
        self.assertEqual(len(output.body_ids), 4291)
        self.assertEqual(len(np.unique(output.body_ids)), 4291)
        self.assertEqual(
            set(box.routes["group_id"]),
            {"sensory.tactile", "sensory.mechanosensory_other"},
        )

    def test_visual_router_preserves_one_channel_per_sensory_neuron(self) -> None:
        if not VISION_CHANNEL_PATH.is_file() or not VISION_ROUTE_PATH.is_file():
            self.skipTest("generated visual wiring is absent")
        box = VisionRoutingBox.from_generated_wiring()
        output = box.step(np.arange(len(box.channel_ids), dtype=np.float64))
        self.assertEqual(len(box.channel_ids), 6098)
        self.assertEqual(len(output.body_ids), 6098)
        self.assertEqual(len(np.unique(output.body_ids)), 6098)
        self.assertEqual(len(np.unique(box.routes["channel_id"])), 6098)


if __name__ == "__main__":
    unittest.main()
