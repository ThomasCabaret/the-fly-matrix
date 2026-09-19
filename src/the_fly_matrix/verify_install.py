from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import mujoco
import numpy as np
import pyarrow.dataset as ds
import torch
import warp as wp
from PIL import Image
from flygym.compose import ActuatorType
from flygym.compose.fly.flybody import FlyBody
from flygym.flybody.anatomy_flybody import (
    FlyBodyActuatedDOFPreset,
    FlyBodyAxisOrder,
    FlyBodyJointPreset,
    FlyBodySkeleton,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "raw" / "malecns" / "v1.0"
REPORT_ROOT = ROOT / "reports" / "generated"
EXPECTED_ROWS = {
    "body-annotations-male-cns-v1.0-minconf-0.5.feather": 211_577,
    "body-neurotransmitters-male-cns-v1.0.feather": 1_835_518,
    "connectome-weights-male-cns-v1.0-minconf-0.5.feather": 151_856_684,
}


@wp.kernel
def _square_kernel(values: wp.array(dtype=float), out: wp.array(dtype=float)):
    index = wp.tid()
    out[index] = values[index] * values[index]


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def verify_packages() -> None:
    section("Versions Python et paquets")
    print(f"Python       : {sys.version.split()[0]}")
    for package in (
        "flygym",
        "mujoco",
        "neuprint-python",
        "numpy",
        "pandas",
        "pyarrow",
        "scipy",
        "torch",
        "warp-lang",
    ):
        print(f"{package:12} : {version(package)}")


def verify_data() -> None:
    section("Tables MaleCNS")
    for filename, expected_rows in EXPECTED_ROWS.items():
        path = DATA_ROOT / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        dataset = ds.dataset(path, format="ipc")
        rows = dataset.count_rows()
        if rows != expected_rows:
            raise RuntimeError(f"{filename}: {rows} lignes, attendu {expected_rows}")
        sample = dataset.head(3, columns=dataset.schema.names[:3])
        if sample.num_rows != 3:
            raise RuntimeError(f"Lecture echantillon impossible: {filename}")
        print(f"[OK] {filename}: {rows:,} lignes, {len(dataset.schema.names)} colonnes")


def verify_torch() -> None:
    section("PyTorch CUDA")
    print(f"Runtime CUDA : {torch.version.cuda}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA indisponible dans PyTorch")
    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(device)
    values = torch.arange(1, 1_000_001, dtype=torch.float32, device=device)
    result = (values * values).sum()
    torch.cuda.synchronize()
    print(f"GPU          : {props.name}")
    print(f"VRAM         : {props.total_memory / 1024**3:.2f} GiB")
    print(f"Calcul       : {result.item():.6e}")


def verify_warp() -> None:
    section("Warp CUDA")
    wp.init()
    devices = wp.get_cuda_devices()
    if not devices:
        raise RuntimeError("Aucun GPU CUDA visible par Warp")
    device = devices[0]
    source = wp.array(np.arange(1, 1001, dtype=np.float32), device=device)
    output = wp.zeros(1000, dtype=float, device=device)
    wp.launch(_square_kernel, dim=1000, inputs=[source], outputs=[output], device=device)
    wp.synchronize()
    result = output.numpy()
    if not np.isclose(result[-1], 1_000_000.0):
        raise RuntimeError(f"Resultat Warp incorrect: {result[-1]}")
    print(f"GPU          : {device}")
    print(f"Calcul       : dernier={result[-1]:.1f}, somme={result.sum():.1f}")


def verify_flybody() -> None:
    section("FlyBody articule et MuJoCo")
    fly = FlyBody()
    skeleton = FlyBodySkeleton(
        axis_order=FlyBodyAxisOrder.YAW_PITCH_ROLL,
        joint_preset=FlyBodyJointPreset.ALL_BIOLOGICAL,
    )
    joints = fly.add_joints(skeleton)
    actuated = skeleton.get_actuated_dofs_from_preset(FlyBodyActuatedDOFPreset.ALL)
    actuators = fly.add_actuators(
        actuated,
        ActuatorType.MOTOR,
        forcelimited=True,
        forcerange=(-0.01, 0.01),
    )
    model = fly.mjcf_root.compile()
    data = mujoco.MjData(model)
    data.ctrl[:] = np.linspace(-0.001, 0.001, model.nu)
    for _ in range(20):
        mujoco.mj_step(model, data)
    if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
        raise RuntimeError("Etat MuJoCo non fini")

    renderer = mujoco.Renderer(model, height=256, width=256)
    renderer.update_scene(data)
    image = renderer.render()
    renderer.close()

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    render_path = REPORT_ROOT / "install-smoke-flybody.png"
    Image.fromarray(image).save(render_path)
    digest = hashlib.sha256(image.tobytes()).hexdigest()[:16]
    print(f"Joints       : {len(joints)}")
    print(f"Actionneurs  : {len(actuators)}")
    print(f"Modele       : nq={model.nq}, nv={model.nv}, nu={model.nu}, nbody={model.nbody}")
    print(f"Rendu        : {render_path} (sha256 prefix {digest})")


def verify_graphviz() -> None:
    section("Graphviz")
    dot = shutil.which("dot")
    if dot is None:
        fallback = Path(r"C:\Program Files\Graphviz\bin\dot.exe")
        if fallback.is_file():
            dot = str(fallback)
    if dot is None:
        raise RuntimeError("dot.exe introuvable")
    source = ROOT / "drosophila_virtual_fly_architecture_v03.dot"
    output = REPORT_ROOT / "install-smoke-architecture.svg"
    completed = subprocess.run(
        [dot, "-Tsvg", str(source), "-o", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stderr.strip():
        print(completed.stderr.strip())
    print(f"dot.exe      : {dot}")
    print(f"Rendu        : {output}")


def main() -> int:
    print("The Fly Matrix - verification complete de l'installation", flush=True)
    try:
        verify_packages()
        verify_data()
        verify_torch()
        verify_warp()
        verify_flybody()
        verify_graphviz()
    except Exception as exc:
        print(f"\nINSTALLATION_VERIFY_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("\nINSTALLATION_VERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
