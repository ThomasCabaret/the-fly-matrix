from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from the_fly_matrix.central_graph import classify_population_scope


class PopulationScopeTests(unittest.TestCase):
    def test_classification_retains_every_row_and_builds_dense_runtime_indices(self) -> None:
        annotated_bodies = pd.DataFrame(
            {
                "bodyId": [10, 20, 30, 40],
                "superclass": ["sensory", "(unknown)", "(unknown)", "motor"],
                "status": ["Traced", "Glia", "Unimportant", "Traced"],
            }
        )

        classified = classify_population_scope(annotated_bodies)

        self.assertEqual(classified["bodyId"].tolist(), [10, 20, 30, 40])
        self.assertEqual(
            classified["population_scope"].tolist(),
            [
                "canonical_neuron",
                "non_neuronal_glia",
                "unresolved_or_non_neuronal_body",
                "canonical_neuron",
            ],
        )
        self.assertEqual(classified["runtime_node_index"].tolist(), [0, -1, -1, 1])
        self.assertEqual(classified["included_in_neural_runtime"].tolist(), [True, False, False, True])
    def test_generated_terminal_routes_only_reference_canonical_neurons(self) -> None:
        root = Path(__file__).resolve().parents[1]
        wiring = root / "data" / "derived" / "wiring"
        node_path = wiring / "central-node-index.parquet"
        input_route_names = [
            "basal-clamp-routes.parquet",
            "proprioception-routes.parquet",
            "mechanosensation-routes.parquet",
            "vision-routes.parquet",
            "unclassified-sensory-routes.parquet",
        ]
        required = [node_path, wiring / "motor-routes.parquet"] + [
            wiring / name for name in input_route_names
        ]
        if not all(path.is_file() for path in required):
            self.skipTest("generated wiring artifacts are absent")

        nodes = pd.read_parquet(
            node_path, columns=["body_id", "included_in_neural_runtime"]
        )
        canonical_ids = set(
            nodes.loc[nodes["included_in_neural_runtime"], "body_id"].astype(int)
        )
        input_ids = pd.concat(
            [
                pd.read_parquet(wiring / name, columns=["target_body_id"])
                for name in input_route_names
            ],
            ignore_index=True,
        )["target_body_id"].astype(int)
        output_ids = pd.read_parquet(
            wiring / "motor-routes.parquet", columns=["source_body_id"]
        )["source_body_id"].astype(int)
        self.assertEqual(input_ids.nunique(), 17884)
        self.assertEqual(output_ids.nunique(), 815)
        self.assertLessEqual(set(input_ids), canonical_ids)
        self.assertLessEqual(set(output_ids), canonical_ids)



if __name__ == "__main__":
    unittest.main()
