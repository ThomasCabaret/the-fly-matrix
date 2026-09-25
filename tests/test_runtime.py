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
    FLYBODY_LOCAL_TOUCH_CHANNEL_PATH,
    FLYBODY_TOUCH_CHANNEL_PATH,
    FLYBODY_ACTUATOR_CHANNEL_PATH,
    FLYBODY_VISION_CHANNEL_PATH,
    MECHANO_CHANNEL_PATH,
    MECHANO_INPUT_CANDIDATE_PATH,
    MECHANO_ROUTE_PATH,
    MOTOR_CHANNEL_PATH,
    MOTOR_ROUTE_PATH,
    MOTOR_ACTUATOR_CANDIDATE_PATH,
    PROPRIO_CHANNEL_PATH,
    PROPRIO_INPUT_CANDIDATE_PATH,
    PROPRIO_PROXY_CANDIDATE_PATH,
    PROPRIO_ROUTE_PATH,
    ROUTE_PATH,
    UNCLASSIFIED_CHANNEL_PATH,
    UNCLASSIFIED_ROUTE_PATH,
    VISION_CHANNEL_PATH,
    VISION_COLUMN_RECEPTOR_PATH,
    VISION_REMAINDER_RECEPTOR_PATH,
    VISION_ROUTE_PATH,
    MechanosensationRoutingBox,
    MechanosensationTransductionBox,
    GroupedChannelActivity,
    MotorRoutingBox,
    MotorTransductionBox,
    ProprioceptionTransductionBox,
    ProprioceptionRoutingBox,
    ResidualSensoryNominalSourceBox,
    SparseActivity,
    UnclassifiedSensoryRoutingBox,
    VisionRoutingBox,
    VisionTransductionBox,
    FlyBodyProprioceptionSensor,
    FlyBodyLocalContactSensor,
    FlyBodyGroundContactSensor,
    FlyBodyActuatorInterface,
    FlyBodyPhysicsLoop,
    FlyBodyVisionSensor,
)
from the_fly_matrix.wiring_smoke import (
    _arbitrary_remainder_retinal_registration,
    _arbitrary_retinal_registration,
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

    def test_central_connectome_retains_inventory_but_excludes_flagged_bodies(self) -> None:
        nodes = pd.DataFrame(
            {
                "node_index": [0, 1, 2, 3],
                "body_id": [10, 15, 20, 30],
                "included_in_neural_runtime": [True, False, True, True],
                "runtime_node_index": [0, -1, 1, 2],
            }
        )
        table = pa.table(
            {
                "body_pre": [10, 10, 15, 20, 30],
                "body_post": [20, 15, 20, 30, 99],
                "weight": [2, 7, 11, 3, 100],
            }
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "weights.feather"
            feather.write_feather(table, path)
            central = CentralConnectomeBox(nodes, path, expected_induced_edges=2)
            output = central.project(SparseActivity(
                body_ids=np.asarray([10], dtype=np.int64),
                values=np.asarray([4.0], dtype=np.float64),
            ))
        self.assertEqual(len(central.inventory_nodes), 4)
        self.assertTrue(np.array_equal(output.values, np.asarray([0.0, 8.0, 0.0])))
        self.assertTrue(np.array_equal(output.body_ids, np.asarray([10, 20, 30])))

    def test_generated_central_runtime_rejects_unclassified_legacy_index(self) -> None:
        legacy_nodes = pd.DataFrame({"node_index": [0], "body_id": [10]})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            node_path = root / "central-node-index.parquet"
            summary_path = root / "central-connectome.json"
            legacy_nodes.to_parquet(node_path, index=False)
            summary_path.write_text('{"induced_edge_rows": 0}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "predates population classification"):
                CentralConnectomeBox.from_generated_wiring(
                    node_path=node_path, weight_path=root / "weights.feather", summary_path=summary_path
                )

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

    def test_proprioception_transduction_executes_sparse_candidates_and_terminals(self) -> None:
        if (
            not PROPRIO_INPUT_CANDIDATE_PATH.is_file()
            or not PROPRIO_PROXY_CANDIDATE_PATH.is_file()
        ):
            self.skipTest("generated proprioception transduction candidates are absent")
        sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
        box = ProprioceptionTransductionBox.from_generated_wiring()
        joint_state = sensor.step(
            np.ones(sensor.qpos_size, dtype=np.float64),
            np.full(sensor.qvel_size, 2.0, dtype=np.float64),
        )
        output = box.step(
            joint_state,
            np.ones(len(box.parameter_ids), dtype=np.float64),
        )
        self.assertEqual(len(box.parameter_ids), 1992)
        self.assertEqual(len(box.direct_parameter_ids), 1439)
        self.assertEqual(len(box.proxy_parameter_ids), 553)
        self.assertEqual(len(box.parameterized_channel_ids), 171)
        self.assertEqual(len(box.proxy_channel_ids), 91)
        self.assertEqual(len(box.resolved_channel_ids), 262)
        self.assertEqual(len(box.unresolved_channel_ids), 0)
        self.assertEqual(len(output.channel_ids), 262)
        self.assertTrue(np.all(output.values > 0))
        self.assertEqual(
            set(box.parameterized_channel_ids) | set(box.proxy_channel_ids),
            set(box.channel_ids),
        )

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

    def test_flybody_physics_loop_applies_commands_and_reads_joint_state(self) -> None:
        if not FLYBODY_ACTUATOR_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody actuator wiring is absent")
        interface = FlyBodyActuatorInterface.from_generated_wiring()
        commands = interface.step(
            np.linspace(-1e-4, 1e-4, len(interface.actuator_names), dtype=np.float64)
        )
        with FlyBodyPhysicsLoop.from_generated_wiring() as loop:
            result = loop.step(commands, substeps=2)
        self.assertEqual(result.actuator_names, interface.actuator_names)
        self.assertEqual(len(result.joint_state.joint_names), 102)
        self.assertEqual(result.actuator_forces.shape, (102,))
        self.assertTrue(np.array_equal(result.applied_commands, commands.values))
        self.assertGreater(result.simulation_time, 0.0)

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

    def test_flybody_local_touch_validates_head_and_thorax_forces(self) -> None:
        if not FLYBODY_LOCAL_TOUCH_CHANNEL_PATH.is_file():
            self.skipTest("generated FlyBody local touch wiring is absent")
        sensor = FlyBodyLocalContactSensor.from_generated_wiring()
        forces = np.arange(6, dtype=np.float64).reshape(2, 3)
        state = sensor.step(forces)
        self.assertEqual(set(state.segment_names), {"c_head", "c_thorax"})
        self.assertTrue(np.array_equal(state.forces, forces))
        with self.assertRaises(ValueError):
            sensor.step(np.zeros((2, 2), dtype=np.float64))

    def test_mechanosensation_transduction_executes_local_candidates_and_terminals(self) -> None:
        if not MECHANO_INPUT_CANDIDATE_PATH.is_file():
            self.skipTest("generated mechanosensation transduction candidates are absent")
        sensor = FlyBodyGroundContactSensor.from_generated_wiring()
        local_sensor = FlyBodyLocalContactSensor.from_generated_wiring()
        joint_sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
        box = MechanosensationTransductionBox.from_generated_wiring()
        contact_state = sensor.step(
            np.arange(sensor.sensor_data_size, dtype=np.float64) + 1.0
        )
        joint_state = joint_sensor.step(
            np.arange(joint_sensor.qpos_size, dtype=np.float64) + 0.5,
            np.arange(joint_sensor.qvel_size, dtype=np.float64) + 100.5,
        )
        local_contact_state = local_sensor.step(
            np.arange(6, dtype=np.float64).reshape(2, 3) + 200.0
        )
        fallback = np.arange(len(box.unresolved_channel_ids), dtype=np.float64) + 1000.0
        output = box.step(
            contact_state,
            local_contact_state,
            joint_state,
            np.ones(len(box.parameter_ids), dtype=np.float64),
            fallback,
        )
        self.assertEqual(len(box.parameter_ids), 2108)
        self.assertEqual(len(box.resolved_channel_ids), 323)
        self.assertEqual(len(box.unresolved_channel_ids), 0)
        self.assertEqual(len(output.channel_ids), 323)
        self.assertTrue(np.all(output.values > 0))
        values_by_channel = dict(zip(output.channel_ids, output.values))
        self.assertTrue(
            np.array_equal(
                np.asarray([values_by_channel[item] for item in box.unresolved_channel_ids]),
                fallback,
            )
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

    def test_visual_transduction_executes_published_r7_r8_columns(self) -> None:
        if not (
            VISION_COLUMN_RECEPTOR_PATH.is_file()
            and VISION_REMAINDER_RECEPTOR_PATH.is_file()
        ):
            self.skipTest("generated visual column assignments are absent")
        sensor = FlyBodyVisionSensor.from_generated_wiring()
        box = VisionTransductionBox.from_generated_wiring()
        readouts = np.arange(np.prod(sensor.readout_shape), dtype=np.float64).reshape(
            sensor.readout_shape
        ) + 1.0
        samples = sensor.step(readouts)
        registration = _arbitrary_retinal_registration(box)
        remainder_registration = _arbitrary_remainder_retinal_registration(box)
        output = box.step(
            samples,
            registration,
            remainder_registration,
            np.ones(len(box.parameter_ids), dtype=np.float64),
        )
        self.assertEqual(len(box.column_ids), 1332)
        self.assertEqual(len(box.published_channel_ids), 2628)
        self.assertEqual(len(box.registration_channel_ids), 3463)
        self.assertEqual(len(box.proxy_channel_ids), 7)
        self.assertEqual(len(box.parameter_ids), 6098)
        self.assertEqual(len(box.resolved_channel_ids), 6098)
        self.assertEqual(len(box.unresolved_channel_ids), 0)
        self.assertEqual(len(output.channel_ids), 6098)
        self.assertTrue(np.all(output.values > 0))
        duplicate_registration = dict(registration)
        first, second = box.column_ids[:2]
        duplicate_registration[second] = duplicate_registration[first]
        with self.assertRaises(ValueError):
            box.step(
                samples,
                duplicate_registration,
                remainder_registration,
                np.ones(len(box.parameter_ids), dtype=np.float64),
            )
        cross_eye_registration = dict(remainder_registration)
        first_remainder = box.registration_channel_ids[0]
        expected_side = box._remainder_side[first_remainder]
        cross_eye_source = next(
            channel_id
            for channel_id in box.physical_channel_ids
            if box._physical_side[channel_id] != expected_side
        )
        cross_eye_registration[first_remainder] = cross_eye_source
        with self.assertRaisesRegex(ValueError, "cross-eye remainder"):
            box.step(
                samples,
                registration,
                cross_eye_registration,
                np.ones(len(box.parameter_ids), dtype=np.float64),
            )

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

    def test_residual_sensory_sources_own_every_unclassified_terminal(self) -> None:
        if not UNCLASSIFIED_CHANNEL_PATH.is_file():
            self.skipTest("generated unclassified sensory wiring is absent")
        source_ids = (
            "source.sensory.residual.chemosensory",
            "source.sensory.residual.mechanosensory_tbc",
            "source.sensory.residual.unknown",
        )
        sources = [
            ResidualSensoryNominalSourceBox.from_generated_wiring(source_id)
            for source_id in source_ids
        ]
        activities = [
            source.step(np.arange(len(source.parameter_ids), dtype=np.float64))
            for source in sources
        ]
        all_channel_ids = [
            channel_id for activity in activities for channel_id in activity.channel_ids
        ]
        router = UnclassifiedSensoryRoutingBox.from_generated_wiring()
        self.assertEqual([len(source.channel_ids) for source in sources], [57, 11, 1815])
        self.assertEqual(len(all_channel_ids), 1883)
        self.assertEqual(len(set(all_channel_ids)), 1883)
        self.assertEqual(set(all_channel_ids), set(router.channel_ids))


if __name__ == "__main__":
    unittest.main()
