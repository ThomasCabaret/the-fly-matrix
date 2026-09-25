from __future__ import annotations

import unittest

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from the_fly_matrix.connectome_topology import bfs_generations, characterize_cycles


class ConnectomeTopologyTests(unittest.TestCase):
    @staticmethod
    def graph(edges: list[tuple[int, int]], node_count: int) -> tuple[np.ndarray, np.ndarray]:
        source = np.asarray([edge[0] for edge in edges], dtype=np.int32)
        target = np.asarray([edge[1] for edge in edges], dtype=np.int32)
        graph = csr_matrix(
            (np.ones(len(edges), dtype=np.uint8), (source, target)),
            shape=(node_count, node_count),
        )
        return graph.indptr, graph.indices

    def test_bfs_depths_start_at_zero_for_every_declared_input(self) -> None:
        indptr, indices = self.graph([(0, 1), (1, 2), (4, 3), (3, 2)], 6)
        depth, parent, order = bfs_generations(
            indptr, indices, np.asarray([0, 4], dtype=np.int32)
        )
        self.assertEqual(depth.tolist(), [0, 1, 2, 1, 0, -1])
        self.assertEqual(parent[0], -1)
        self.assertEqual(parent[4], -1)
        self.assertEqual(set(order.tolist()), {0, 1, 2, 3, 4})

    def test_exact_tree_cycle_is_separate_from_nonancestor_feedback(self) -> None:
        # 0->1->2->3->1 closes an exact tree cycle of length 3.
        # 0->4->2 reaches a seen node but 2 is not an ancestor of 4.
        edges = [(0, 1), (1, 2), (2, 3), (3, 1), (0, 4), (4, 2)]
        indptr, indices = self.graph(edges, 5)
        graph = csr_matrix(
            (np.ones(len(indices), dtype=np.uint8), indices, indptr), shape=(5, 5)
        )
        depth, parent, order = bfs_generations(indptr, indices, np.asarray([0], dtype=np.int32))
        component_count, labels = connected_components(
            graph, directed=True, connection="strong", return_labels=True
        )
        sizes = np.bincount(labels, minlength=component_count)
        result = characterize_cycles(indptr, indices, depth, parent, order, labels, sizes)
        self.assertEqual(result["exact_tree_cycle_histogram"][3], 1)
        self.assertEqual(result["fundamental_cycle_closing_edges"], 1)
        self.assertEqual(result["feedback_generation_gap_histogram"][2], 1)

    def test_self_loop_is_cycle_length_one_and_cyclic_singleton(self) -> None:
        indptr, indices = self.graph([(0, 0), (0, 1)], 2)
        graph = csr_matrix(
            (np.ones(len(indices), dtype=np.uint8), indices, indptr), shape=(2, 2)
        )
        depth, parent, order = bfs_generations(indptr, indices, np.asarray([0], dtype=np.int32))
        component_count, labels = connected_components(
            graph, directed=True, connection="strong", return_labels=True
        )
        sizes = np.bincount(labels, minlength=component_count)
        result = characterize_cycles(indptr, indices, depth, parent, order, labels, sizes)
        self.assertEqual(result["exact_tree_cycle_histogram"][1], 1)
        self.assertEqual(result["feedback_generation_gap_histogram"][0], 1)
        self.assertEqual(result["self_loop_nodes"], 1)
        self.assertEqual(int(result["cyclic_component_mask"].sum()), 1)


if __name__ == "__main__":
    unittest.main()
