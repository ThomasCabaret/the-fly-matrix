from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from the_fly_matrix.calibration_parameters import (
    ParameterCompilationError,
    compile_factorized_parameters,
    load_candidate_frame,
    load_compiler_contract,
    validate_all_contracts,
)


class CalibrationParameterCompilerTests(unittest.TestCase):
    def test_real_contracts_are_exhaustive_and_deterministic(self) -> None:
        result = validate_all_contracts()
        self.assertEqual(
            {key: value["runtime_coefficients"] for key, value in result.items()},
            {
                "parameter.proprioception.transfer.v0": 1992,
                "parameter.mechanosensation.transfer.v0": 2108,
                "parameter.motor.transfer.v0": 7849,
            },
        )
        self.assertEqual(result["parameter.motor.transfer.v0"]["logical_routes"], 3746)

    def test_motor_route_is_replicated_without_duplicating_the_route_decision(self) -> None:
        frame = pd.DataFrame(
            {
                "parameter_id": ["p1", "p2", "p3", "p4"],
                "group": ["g1", "g1", "g1", "g1"],
                "terminal": ["n1", "n2", "n1", "n2"],
                "actuator": ["a1", "a1", "a2", "a2"],
            }
        )
        spec = {
            "runtime_parameter_id_column": "parameter_id",
            "route_group_column": "group",
            "route_key_columns": ["group", "actuator"],
            "expected_counts": {
                "runtime_coefficients": 4,
                "logical_routes": 2,
                "route_groups": 1,
            },
        }
        route = {
            '["g1","a1"]': 0.25,
            '["g1","a2"]': 0.75,
        }
        assignment = {"p1": "n1", "p2": "n2", "p3": "n1", "p4": "n2"}
        compiled = compile_factorized_parameters(
            family_id="test.motor",
            candidates=frame,
            spec=spec,
            routing_weights=route,
            transfer_assignment=assignment,
            transfer_values={"n1": 2.0, "n2": -1.0},
        )
        np.testing.assert_allclose(compiled.values, [0.5, -0.25, 1.5, -0.75])

    def test_rejects_incomplete_or_non_normalized_routing(self) -> None:
        contract = load_compiler_contract()
        spec = contract["families"]["parameter.proprioception.transfer.v0"]
        frame = load_candidate_frame(spec)
        keys = frame["parameter_id"].astype(str).tolist()
        assignment = dict(zip(keys, frame["target_channel_id"].astype(str)))
        transfers = {key: 1.0 for key in assignment.values()}
        with self.assertRaisesRegex(ParameterCompilationError, "Routing key mismatch"):
            compile_factorized_parameters(
                family_id="parameter.proprioception.transfer.v0",
                candidates=frame,
                spec=spec,
                routing_weights={},
                transfer_assignment=assignment,
                transfer_values=transfers,
            )
        bad_routes = {key: 1.0 for key in keys}
        with self.assertRaisesRegex(ParameterCompilationError, "simplex violation"):
            compile_factorized_parameters(
                family_id="parameter.proprioception.transfer.v0",
                candidates=frame,
                spec=spec,
                routing_weights=bad_routes,
                transfer_assignment=assignment,
                transfer_values=transfers,
            )


if __name__ == "__main__":
    unittest.main()
