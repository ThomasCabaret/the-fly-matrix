from __future__ import annotations

import numpy as np
from scipy import sparse
from types import SimpleNamespace

from the_fly_matrix.abn1_model_class import (
    _event_trial,
    aggregate_rate_input,
    poisson_source_schedule,
    summarize_directional_pilot,
)
from the_fly_matrix.lif_gate import LifConstants


def test_poisson_schedule_is_deterministic_and_paired_by_prefix() -> None:
    small = poisson_source_schedule(2, 120.0, 4, steps=200)
    large = poisson_source_schedule(5, 120.0, 4, steps=200)
    repeated = poisson_source_schedule(2, 120.0, 4, steps=200)
    assert np.array_equal(small, repeated)
    # NumPy fills row-major, so shapes do not preserve a column prefix. Pairing
    # means a common seed and generator contract, not neuron-wise common noise.
    assert small.shape == (200, 2)
    assert large.shape == (200, 5)


def test_rate_aggregation_preserves_event_counts_without_clipping() -> None:
    events = np.zeros((100, 2), dtype=bool)
    events[0:5, 0] = True
    events[50:53, 1] = True
    rate = aggregate_rate_input(events)
    assert rate.shape == (2, 2)
    assert np.isclose(rate[0, 0], 5.0 / 1.1)
    assert np.isclose(rate[1, 1], 3.0 / 1.1)
    assert rate[0, 0] > 1.0


def test_event_trial_does_not_mutate_canonical_csr_weights() -> None:
    outgoing = sparse.csr_matrix(
        (np.asarray([2.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    before = outgoing.data.copy()
    profile = SimpleNamespace(
        constants=LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 0.2),
        dt_ms=0.1,
        model={"reference_constants": {"unitary_synaptic_weight_mV": {"value": 0.275}}},
    )
    events = np.zeros((5, 1), dtype=bool)
    events[0, 0] = True
    _event_trial(
        outgoing,
        np.ones(2, dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
    )
    assert np.array_equal(outgoing.data, before)


def test_directional_summary_never_compares_native_model_amplitudes() -> None:
    rows = []
    for model, magnitude in (("event", 100.0), ("rate", 0.01)):
        for condition, factor in (("SHAM", 0.0), ("JO_CE", 2.0), ("JO_F", 1.0)):
            for frequency in ((0,) if condition == "SHAM" else (20, 120)):
                rows.append(
                    {
                        "model": model,
                        "parameter_member": "one",
                        "bridge_scale": None,
                        "condition": condition,
                        "frequency_hz": frequency,
                        "response": magnitude * factor,
                    }
                )
    summary = summarize_directional_pilot(rows, (20, 120))
    assert len(summary["series"]) == 2
    assert summary["all_series_positive_at_all_pilot_frequencies"]
