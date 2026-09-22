from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

from the_fly_matrix.runtime import (
    BasalClampBox,
    CHANNEL_PATH,
    CentralConnectomeBox,
    CNSInputBuffer,
    FLYBODY_PROPRIO_CHANNEL_PATH,
    FLYBODY_TOUCH_CHANNEL_PATH,
    FLYBODY_ACTUATOR_CHANNEL_PATH,
    FLYBODY_VISION_CHANNEL_PATH,
    MECHANO_CHANNEL_PATH,
    MECHANO_ROUTE_PATH,
    MOTOR_CHANNEL_PATH,
    MOTOR_ROUTE_PATH,
    MOTOR_ACTUATOR_CANDIDATE_PATH,
    PROPRIO_CHANNEL_PATH,
    PROPRIO_ROUTE_PATH,
    ROUTE_PATH,
    UNCLASSIFIED_CHANNEL_PATH,
    UNCLASSIFIED_ROUTE_PATH,
    VISION_CHANNEL_PATH,
    VISION_ROUTE_PATH,
    MechanosensationRoutingBox,
    GroupedChannelActivity,
    MotorRoutingBox,
    MotorTransductionBox,
    ProprioceptionRoutingBox,
    SparseActivity,
    UnclassifiedSensoryRoutingBox,
    VisionRoutingBox,
    FlyBodyProprioceptionSensor,
    FlyBodyGroundContactSensor,
    FlyBodyActuatorInterface,
    FlyBodyVisionSensor,
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

    def test_central_connectome_streams_only_annotated_induced_edges(self) -> None:
        nodes = pd.DataFrame({"node_index": [0, 1, 2], "body_id": [10, 20, 30]})
        table = pa.table(
            {
                "body_pre": [10, 10, 99, 20],
                "body_post": [20, 30, 20, 99],
                "weight": [2, 3, 100, 100],
            }
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "weights.feather"
            feather.write_feather(table, path)
            central = CentralConnectomeBox(nodes, path, expected_induced_edges=2)
            activity = SparseActivity(
                body_ids=np.asarray([10], dtype=np.int64),
                values=np.asarray([4.0], dtype=np.float64),
            )
            output = central.project(activity)
        self.assertTrue(np.array_equal(output.body_ids, np.asarray([10, 20, 30])))
        self.assertTrue(np.array_equal(output.values, np.asarray([0.0, 8.0, 12.0])))

    def test_proprioception_router_executes_downstream_only(self) -> None:
        if not PROPRIO_CHANNEL_PATH.is_file() or not PROPRIO_ROUTE_PATH.is_file():
            self.skipTest("generated proprioceptive wiring is absent")
        box = ProprioceptionRoutingBox.from_generated_wiring()
        output = box.step(np.arange(len(box.channel_ids), dtype=np.float64))
        self.assertEqual(len(box.channel_ids), 262)
        self.assertEqual(len(output.body_ids), 1454)
        self.assertEqual(len(np.unique(output.body_ids)), 1454)

    def test_flybody_joint_state_executes_upstream_without_receptor_claims(self) -> None:
        if not FLYBODY_PROPRIO_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody proprioception wiring is absent")
        sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
        qpos = np.arange(sensor.qpos_size, dtype=np.float64) + 0.25
        qvel = np.arange(sensor.qvel_size, dtype=np.float64) - 0.5
        output = sensor.step(qpos, qvel)
        self.assertEqual(len(sensor.channel_ids), 102)
        self.assertEqual(len(output.joint_names), 102)
        self.assertEqual(sensor.qpos_size, 102)
        self.assertEqual(sensor.qvel_size, 102)
        self.assertTrue(np.array_equal(output.positions, qpos))
        self.assertTrue(np.array_equal(output.velocities, qvel))
        self.assertEqual(set(sensor.channels["observables"]), {"position,velocity"})

    def test_flybody_ground_contacts_execute_without_receptor_claims(self) -> None:
        if not FLYBODY_TOUCH_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody touch wiring is absent")
        sensor = FlyBodyGroundContactSensor.from_generated_wiring()
        raw = np.arange(sensor.sensor_data_size, dtype=np.float64)
        output = sensor.step(raw)
        self.assertEqual(sensor.leg_names, ("lf", "lm", "lh", "rf", "rm", "rh"))
        self.assertEqual(sensor.sensor_data_size, 96)
        self.assertEqual(output.contact_found.shape, (6,))
        self.assertEqual(output.forces.shape, (6, 3))
        self.assertEqual(output.torques.shape, (6, 3))
        self.assertEqual(output.positions.shape, (6, 3))
        self.assertEqual(output.normals.shape, (6, 3))
        self.assertEqual(output.tangents.shape, (6, 3))
        self.assertTrue(np.array_equal(output.forces[0], raw[1:4]))

    def test_flybody_actuator_interface_addresses_all_control_slots(self) -> None:
        if not FLYBODY_ACTUATOR_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody actuator wiring is absent")
        interface = FlyBodyActuatorInterface.from_generated_wiring()
        values = np.arange(len(interface.actuator_names), dtype=np.float64)
        output = interface.step(values)
        self.assertEqual(len(interface.actuator_names), 102)
        self.assertEqual(interface.control_size, 102)
        self.assertEqual(len(output.actuator_names), 102)
        self.assertTrue(np.array_equal(output.values, values))
        self.assertEqual(interface.channels["target_joint_name"].nunique(), 102)
        self.assertEqual(
            interface.channels["actuator_config_status"].value_counts().to_dict(),
            {"configured": 100, "missing": 2},
        )

    def test_flybody_vision_extracts_one_active_sample_per_ommatidium(self) -> None:
        if not FLYBODY_VISION_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody vision wiring is absent")
        sensor = FlyBodyVisionSensor.from_generated_wiring()
        readouts = np.arange(np.prod(sensor.readout_shape), dtype=np.float64).reshape(
            sensor.readout_shape
        )
        output = sensor.step(readouts)
        self.assertEqual(sensor.readout_shape, (2, 721, 2))
        self.assertEqual(len(sensor.channel_ids), 1442)
        self.assertEqual(len(output.values), 1442)
        first = sensor.channels.iloc[0]
        expected_first = readouts[
            int(first["eye_index"]),
            int(first["ommatidium_id"]),
            int(first["component_index"]),
        ]
        self.assertEqual(output.values[0], expected_first)
        self.assertEqual(set(sensor.channels["eye"]), {"left", "right"})
        self.assertEqual(set(sensor.channels["ommatidium_type"]), {"yellow", "pale"})

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

    def test_motor_router_preserves_one_channel_per_motor_neuron(self) -> None:
        if not MOTOR_CHANNEL_PATH.is_file() or not MOTOR_ROUTE_PATH.is_file():
            self.skipTest("generated motor wiring is absent")
        box = MotorRoutingBox.from_generated_wiring()
        values = np.arange(len(box.source_body_ids), dtype=np.float64)
        output = box.step(values)
        self.assertEqual(len(box.source_body_ids), 815)
        self.assertEqual(len(output.channel_ids), 815)
        self.assertEqual(len(set(output.channel_ids)), 815)
        self.assertEqual(len(output.group_ids), 815)
        self.assertEqual(len(set(output.group_ids)), 441)
        self.assertTrue(np.array_equal(output.values, values))
        self.assertEqual(
            set(box.routes["group_id"]),
            {"motor.vnc", "motor.central_brain"},
        )

    def test_motor_transduction_executes_only_anatomical_candidate_edges(self) -> None:
        if not MOTOR_ACTUATOR_CANDIDATE_PATH.is_file():
            self.skipTest("generated motor transduction candidates are absent")
        router = MotorRoutingBox.from_generated_wiring()
        transduction = MotorTransductionBox.from_generated_wiring()
        activity = router.step(np.ones(len(router.source_body_ids), dtype=np.float64))
        output = transduction.step(
            activity, np.ones(len(transduction.parameter_ids), dtype=np.float64)
        )
        self.assertEqual(len(transduction.parameter_ids), 7849)
        self.assertEqual(len(transduction.source_channel_ids), 804)
        self.assertEqual(len(transduction.resolved_group_ids), 431)
        self.assertEqual(len(transduction.covered_actuator_ids), 102)
        self.assertEqual(len(transduction.uncovered_actuator_ids), 0)
        self.assertEqual(len(transduction.unsupported_terminal_channel_ids), 11)
        self.assertEqual(output.values.shape, (102,))
        self.assertTrue(np.all(output.values[list(transduction.covered_actuator_ids)] > 0))
        terminal_values = np.asarray(
            [
                float(channel_id in transduction.unsupported_terminal_channel_ids)
                for channel_id in activity.channel_ids
            ]
        )
        terminal_activity = GroupedChannelActivity(
            channel_ids=activity.channel_ids,
            group_ids=activity.group_ids,
            values=terminal_values,
        )
        terminal_output = transduction.step(
            terminal_activity, np.ones(len(transduction.parameter_ids), dtype=np.float64)
        )
        self.assertEqual(np.count_nonzero(terminal_output.values), 0)

    def test_unclassified_sensory_router_closes_inventory_coverage(self) -> None:
        if not UNCLASSIFIED_CHANNEL_PATH.is_file() or not UNCLASSIFIED_ROUTE_PATH.is_file():
            self.skipTest("generated unclassified sensory wiring is absent")
        box = UnclassifiedSensoryRoutingBox.from_generated_wiring()
        output = box.step(np.arange(len(box.channel_ids), dtype=np.float64))
        self.assertEqual(len(box.channel_ids), 1883)
        self.assertEqual(len(output.body_ids), 1883)
        self.assertEqual(len(np.unique(output.body_ids)), 1883)


if __name__ == "__main__":
    unittest.main()
