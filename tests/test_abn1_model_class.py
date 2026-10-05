from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import torch
from scipy import sparse

from the_fly_matrix.abn1_model_class import (
    Abn1ModelClassError,
    _event_trial,
    _rate_trial,
    aggregate_rate_input,
    event_unitary_weight_mV,
    load_protocol,
    poisson_source_schedule,
    summarize_directional_pilot,
)
from the_fly_matrix.lif_gate import LifConstants
from the_fly_matrix.lif_source_fidelity import SourceAlignedProfile, _linear_factors


def _micro_profile(
    *, threshold_mV: float = 100.0, delay_ms: float = 0.2
) -> SimpleNamespace:
    return SimpleNamespace(
        constants=LifConstants(-52.0, -52.0, threshold_mV, 20.0, 5.0, 0.3, delay_ms),
        dt_ms=0.1,
        forced_weight_mV=0.0001,
        model={
            "reference_constants": {
                "unitary_synaptic_weight_mV": {
                    "value": 0.275,
                    "origin": "published_behavior_exposed_fit",
                }
            }
        },
    )


def _event_semantics(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key != "wall_seconds"}


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


def test_rate_aggregation_rejects_partial_bins() -> None:
    with pytest.raises(ValueError, match="complete rate bins"):
        aggregate_rate_input(np.zeros((51, 1), dtype=bool))


def test_event_trial_does_not_mutate_canonical_csr_weights() -> None:
    outgoing = sparse.csr_matrix(
        (np.asarray([2.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    before = outgoing.data.copy()
    profile = SimpleNamespace(
        constants=LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 0.2),
        dt_ms=0.1,
        model={
            "reference_constants": {
                "unitary_synaptic_weight_mV": {
                    "value": 0.275,
                    "origin": "published_behavior_exposed_fit",
                }
            }
        },
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


def test_scientific_weight_is_selected_instead_of_benchmark_load_weight() -> None:
    profile = SourceAlignedProfile.load()
    value, origin = event_unitary_weight_mV(profile)
    assert value == pytest.approx(0.275)
    assert origin == "published_behavior_exposed_fit"
    assert profile.forced_weight_mV == pytest.approx(0.0001)
    assert value != profile.forced_weight_mV


def test_weight_provenance_drift_is_rejected() -> None:
    profile = _micro_profile()
    profile.model["reference_constants"]["unitary_synaptic_weight_mV"][
        "origin"
    ] = "synthetic_benchmark_load"
    with pytest.raises(Abn1ModelClassError, match="provenance"):
        event_unitary_weight_mV(profile)


def test_single_event_has_exact_weight_and_delay_before_membrane_integration() -> None:
    profile = _micro_profile()
    outgoing = sparse.csr_matrix(
        (np.asarray([2.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    events = np.zeros((6, 1), dtype=bool)
    events[0, 0] = True
    result = _event_trial(
        outgoing,
        np.ones(2, dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
        trace_indices=np.asarray([0, 1], dtype=np.int64),
    )
    trace = result["trace"]
    assert trace["emitted_indices"][0] == []
    assert trace["emitted_indices"][1] == [0]
    assert trace["g_mV"][2, 1] == pytest.approx(0.0)
    assert trace["g_mV"][3, 1] == pytest.approx(0.55)
    assert trace["v_mV"][3, 1] == pytest.approx(-52.0)
    membrane_decay, synaptic_decay, coupling = _linear_factors(profile.constants, 0.1)
    del membrane_decay
    assert trace["v_mV"][4, 1] == pytest.approx(-52.0 + 0.55 * coupling, abs=1e-6)
    assert trace["g_mV"][4, 1] == pytest.approx(0.55 * synaptic_decay, abs=1e-6)
    assert result["delivered_edge_events"] == 1


def test_consecutive_poisson_events_reset_source_with_zero_refractory() -> None:
    profile = _micro_profile()
    outgoing = sparse.csr_matrix(
        (np.asarray([1.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    events = np.zeros((6, 1), dtype=bool)
    events[0:2, 0] = True
    result = _event_trial(
        outgoing,
        np.ones(2, dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
        trace_indices=np.asarray([0], dtype=np.int64),
    )
    trace = result["trace"]
    assert trace["emitted_indices"][1] == [0]
    assert trace["emitted_indices"][2] == [0]
    assert result["forced_source_spikes"] == 2
    assert result["delivered_edge_events"] == 2
    np.testing.assert_array_equal(trace["refractory_steps"][:, 0], 0)
    assert trace["v_mV"][1, 0] == pytest.approx(profile.constants.reset_mV)
    assert trace["g_mV"][1, 0] == pytest.approx(0.0)


def test_presynaptic_sign_controls_the_delivered_current_direction() -> None:
    profile = _micro_profile()
    outgoing = sparse.csr_matrix(
        (np.asarray([2.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    events = np.zeros((6, 1), dtype=bool)
    events[0, 0] = True
    excitatory = _event_trial(
        outgoing,
        np.asarray([1.0, 1.0], dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
        trace_indices=np.asarray([1], dtype=np.int64),
    )
    inhibitory = _event_trial(
        outgoing,
        np.asarray([-1.0, 1.0], dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
        trace_indices=np.asarray([1], dtype=np.int64),
    )
    assert excitatory["trace"]["g_mV"][3, 0] == pytest.approx(0.55)
    assert inhibitory["trace"]["g_mV"][3, 0] == pytest.approx(-0.55)
    assert excitatory["trace"]["v_mV"][4, 0] > profile.constants.v_rest_mV
    assert inhibitory["trace"]["v_mV"][4, 0] < profile.constants.v_rest_mV


def test_generated_target_spike_resets_all_state_and_sets_refractory() -> None:
    profile = _micro_profile(threshold_mV=-51.5)
    outgoing = sparse.csr_matrix(
        (np.asarray([2000.0], dtype=np.float32), ([0], [1])), shape=(2, 2)
    )
    events = np.zeros((12, 1), dtype=bool)
    events[0, 0] = True
    result = _event_trial(
        outgoing,
        np.ones(2, dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([1], dtype=np.int64),
        events,
        "cpu",
        profile,
        trace_indices=np.asarray([1], dtype=np.int64),
    )
    trace = result["trace"]
    spike_step = next(
        step for step, emitted in enumerate(trace["emitted_indices"]) if 1 in emitted
    )
    assert trace["v_mV"][spike_step, 0] == pytest.approx(profile.constants.reset_mV)
    assert trace["g_mV"][spike_step, 0] == pytest.approx(0.0)
    assert trace["refractory_steps"][spike_step, 0] == 3
    assert result["endogenous_spikes"] >= 1


def test_event_conditions_are_order_independent_and_fresh() -> None:
    profile = _micro_profile()
    outgoing = sparse.csr_matrix(
        (np.asarray([4.0, 1.0], dtype=np.float32), ([0, 1], [2, 2])),
        shape=(3, 3),
    )
    first = np.zeros((8, 1), dtype=bool)
    second = np.zeros((8, 1), dtype=bool)
    first[0, 0] = True
    second[0:2, 0] = True

    def run(source: int, schedule: np.ndarray) -> dict[str, object]:
        return _event_semantics(
            _event_trial(
                outgoing,
                np.ones(3, dtype=np.float32),
                np.asarray([source], dtype=np.int64),
                np.asarray([2], dtype=np.int64),
                schedule,
                "cpu",
                profile,
                trace_indices=np.asarray([2], dtype=np.int64),
            )
        )

    a_then_b = (run(0, first), run(1, second))
    b_then_a = (run(1, second), run(0, first))
    for left, right in ((a_then_b[0], b_then_a[1]), (a_then_b[1], b_then_a[0])):
        assert left.keys() == right.keys()
        for key in left:
            if key == "trace":
                np.testing.assert_allclose(left[key]["v_mV"], right[key]["v_mV"])
                np.testing.assert_allclose(left[key]["g_mV"], right[key]["g_mV"])
                np.testing.assert_array_equal(
                    left[key]["refractory_steps"], right[key]["refractory_steps"]
                )
                assert left[key]["emitted_indices"] == right[key]["emitted_indices"]
            else:
                assert left[key] == right[key]


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is unavailable")
def test_event_micro_oracle_matches_between_cpu_and_gpu() -> None:
    profile = _micro_profile(threshold_mV=-51.8)
    outgoing = sparse.csr_matrix(
        (np.asarray([80.0, 3.0], dtype=np.float32), ([0, 1], [2, 2])),
        shape=(3, 3),
    )
    events = np.zeros((20, 1), dtype=bool)
    events[[0, 3, 4], 0] = True
    arguments = (
        outgoing,
        np.ones(3, dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        np.asarray([2], dtype=np.int64),
        events,
    )
    cpu = _event_trial(
        *arguments, "cpu", profile, trace_indices=np.asarray([0, 2], dtype=np.int64)
    )
    gpu = _event_trial(
        *arguments, "cuda", profile, trace_indices=np.asarray([0, 2], dtype=np.int64)
    )
    for key in (
        "target_spikes",
        "forced_source_spikes",
        "endogenous_spikes",
        "delivered_edge_events",
    ):
        assert cpu[key] == gpu[key]
    for key in ("v_mV", "g_mV"):
        np.testing.assert_allclose(cpu["trace"][key], gpu["trace"][key], atol=1e-6)
    np.testing.assert_array_equal(
        cpu["trace"]["refractory_steps"], gpu["trace"]["refractory_steps"]
    )
    assert cpu["trace"]["emitted_indices"] == gpu["trace"]["emitted_indices"]


def test_real_configuration_to_tiny_graph_distinguishes_strong_and_weak_routes() -> None:
    profile = SourceAlignedProfile.load()
    outgoing = sparse.csr_matrix(
        (np.asarray([2000.0, 1.0], dtype=np.float32), ([0, 1], [2, 2])),
        shape=(3, 3),
    )
    events = np.zeros((100, 1), dtype=bool)
    events[0, 0] = True
    common = (outgoing, np.ones(3, dtype=np.float32))
    strong = _event_trial(
        *common,
        np.asarray([0], dtype=np.int64),
        np.asarray([2], dtype=np.int64),
        events,
        "cpu",
        profile,
    )
    weak = _event_trial(
        *common,
        np.asarray([1], dtype=np.int64),
        np.asarray([2], dtype=np.int64),
        events,
        "cpu",
        profile,
    )
    assert strong["unitary_synaptic_weight_mV"] == pytest.approx(0.275)
    assert strong["target_spikes"] > 0
    assert weak["target_spikes"] == 0
    assert strong["target_g_peak_mV"] == pytest.approx(550.0)
    assert weak["target_g_peak_mV"] == pytest.approx(0.275)


def test_rate_trial_starts_from_fresh_state_and_has_cpu_gpu_parity() -> None:
    matrix_cpu = torch.sparse_csr_tensor(
        torch.tensor([0, 0, 0, 1]),
        torch.tensor([0]),
        torch.tensor([1.0]),
        size=(3, 3),
        check_invariants=True,
    )
    inverse_cpu = torch.ones(3)
    strong = np.ones((8, 1), dtype=np.float32)
    silent = np.zeros((8, 1), dtype=np.float32)
    candidate = {"time_constant_ms": 20.0, "input_gain": 1.0, "bias": 0.0}
    source = np.asarray([0], dtype=np.int64)
    target = np.asarray([2], dtype=np.int64)
    excited = _rate_trial(
        matrix_cpu, inverse_cpu, source, target, strong, 1.0, candidate, "cpu"
    )
    silent_after = _rate_trial(
        matrix_cpu, inverse_cpu, source, target, silent, 1.0, candidate, "cpu"
    )
    silent_fresh = _rate_trial(
        matrix_cpu, inverse_cpu, source, target, silent, 1.0, candidate, "cpu"
    )
    assert excited["response"] > 0
    assert silent_after["response"] == pytest.approx(0.0)
    assert silent_after["response"] == silent_fresh["response"]
    if torch.cuda.is_available():
        gpu = _rate_trial(
            matrix_cpu.to("cuda"),
            inverse_cpu.to("cuda"),
            source,
            target,
            strong,
            1.0,
            candidate,
            "cuda",
        )
        assert gpu["response"] == pytest.approx(excited["response"], abs=1e-6)


def test_protocol_keeps_behavior_and_cross_model_amplitudes_outside_runner() -> None:
    protocol, campaign = load_protocol()
    assert campaign["behavior_targets"] == []
    assert campaign["optimization"]["enabled"] is False
    assert (
        protocol["native_metrics_locked_before_candidate_execution"]["forbidden_metric"]
        == "cross_model_native_amplitude_difference"
    )
    assert protocol["stimulus_contract"]["rate_bridge_scale_sensitivity"] == [0.25, 1.0, 4.0]


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
