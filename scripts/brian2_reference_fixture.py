"""Run tiny Brian2 2.5.1 scheduler probes and emit machine-readable JSON.

This file intentionally has no dependency on the project package.  It is run by
the isolated Python 3.10 reference environment created under ``runs/``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path

# Keep Brian's cache inside the ignored run tree.  This matters in sandboxed
# reproductions and prevents the fixture from mutating the user's profile.
_runtime_home = Path(__file__).resolve().parents[1] / "runs" / "reference-env" / "brian-home"
_runtime_home.mkdir(parents=True, exist_ok=True)
os.environ["USERPROFILE"] = str(_runtime_home)
os.environ["HOME"] = str(_runtime_home)

import brian2 as b2
import numpy as np


EQUATIONS = """
dv/dt = (v_0 - v + g) / t_mbr : volt (unless refractory)
dg/dt = -g / tau : volt (unless refractory)
rfc : second
"""


def _values(values, unit):
    return [float(value / unit) for value in values]


def _group(size=1, reset="v = v_rst; g = 0*mV", threshold="v > v_th"):
    return b2.NeuronGroup(
        size,
        EQUATIONS,
        method="linear",
        threshold=threshold,
        reset=reset,
        refractory="rfc",
        namespace={
            "v_0": -52 * b2.mV,
            "v_rst": -52 * b2.mV,
            "v_th": -45 * b2.mV,
            "t_mbr": 20 * b2.ms,
            "tau": 5 * b2.ms,
        },
    )


def exact_source_reset_probe():
    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = 0.1 * b2.ms
    try:
        group = _group(reset="v = v_rst; w = 0; g = 0*mV")
        group.v = -44 * b2.mV
        group.g = 3 * b2.mV
        group.rfc = 2.2 * b2.ms
        network = b2.Network(group)
        network.run(0.1 * b2.ms)
    except Exception as error:  # the exact upstream reset refers to an undeclared w
        return {
            "compiles": False,
            "exception_type": type(error).__name__,
            "exception": str(error),
        }
    return {"compiles": True, "exception_type": None, "exception": None}


def continuous_probe():
    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = 0.1 * b2.ms
    group = _group(threshold="False")
    group.v = -50 * b2.mV
    group.g = 2 * b2.mV
    group.rfc = 2.2 * b2.ms
    monitor = b2.StateMonitor(group, ("v", "g"), record=True, when="end")
    b2.Network(group, monitor).run(1.0 * b2.ms)
    return {
        "sample_times_ms": _values(monitor.t, b2.ms),
        "v_mV": _values(monitor.v[0], b2.mV),
        "g_mV": _values(monitor.g[0], b2.mV),
    }


def reset_refractory_probe():
    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = 0.1 * b2.ms
    group = _group()
    group.v = -44 * b2.mV
    group.g = 3 * b2.mV
    group.rfc = 2.2 * b2.ms
    states = b2.StateMonitor(group, ("v", "g", "not_refractory"), record=True, when="end")
    spikes = b2.SpikeMonitor(group)
    b2.Network(group, states, spikes).run(2.6 * b2.ms)
    return {
        "sample_times_ms": _values(states.t, b2.ms),
        "v_mV": _values(states.v[0], b2.mV),
        "g_mV": _values(states.g[0], b2.mV),
        "not_refractory": [bool(value) for value in states.not_refractory[0]],
        "spike_times_ms": _values(spikes.t, b2.ms),
    }


def delay_probe():
    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = 0.1 * b2.ms
    source = b2.SpikeGeneratorGroup(1, np.array([0]), np.array([0.0]) * b2.ms)
    target = _group(threshold="False")
    target.v = -52 * b2.mV
    target.g = 0 * b2.mV
    target.rfc = 2.2 * b2.ms
    synapse = b2.Synapses(source, target, "w : volt", on_pre="g += w", delay=1.8 * b2.ms)
    synapse.connect(i=[0], j=[0])
    synapse.w = 5 * b2.mV
    states = b2.StateMonitor(target, ("v", "g"), record=True, when="end")
    b2.Network(source, target, synapse, states).run(2.2 * b2.ms)
    return {
        "sample_times_ms": _values(states.t, b2.ms),
        "v_mV": _values(states.v[0], b2.mV),
        "g_mV": _values(states.g[0], b2.mV),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = {
        "python": platform.python_version(),
        "brian2": b2.__version__,
        "numpy": np.__version__,
        "dt_ms": 0.1,
        "exact_source_reset": exact_source_reset_probe(),
        "continuous": continuous_probe(),
        "reset_refractory": reset_refractory_probe(),
        "delay": delay_probe(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
