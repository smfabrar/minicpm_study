"""Check CUDA development files and identify damaged Conda package payloads."""

import argparse
import json
import subprocess
from pathlib import Path


CUDA_CHANNEL = "nvidia/label/cuda-12.5.1"


def toolkit_paths(root: Path) -> dict:
    root = root.absolute()
    includes = [root / "targets/x86_64-linux/include", root / "include"]
    libraries = [root / "targets/x86_64-linux/lib", root / "lib64", root / "lib"]
    required = {
        "cuda_runtime.h": includes,
        "cuda.h": includes,
        "cublas_v2.h": includes,
        "libcudart.so": libraries,
        "libcublas.so": libraries,
    }
    found = {}
    for name, directories in required.items():
        file = next((directory / name for directory in directories if (directory / name).is_file()), None)
        if file is None:
            raise RuntimeError(
                f"Incomplete CUDA toolkit at {root}: missing {name} (including broken symlinks). "
                "Rerun the updated install.sh with the same --prefix to repair managed CUDA packages."
            )
        found[name] = str(file)
    return found


def missing_package_specs(root: Path) -> list[str]:
    """Only repair installed packages from our pinned NVIDIA CUDA channel."""
    packages = []
    for record in sorted((root / "conda-meta").glob("*.json")):
        package = json.loads(record.read_text())
        origin = str(package.get("channel", "")) + " " + str(package.get("url", ""))
        if CUDA_CHANNEL not in origin:
            continue
        files = package.get("files", [])
        missing = []
        for relative in files:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Invalid installed package path in {record.name}")
            if not (root / path).exists():
                missing.append(relative)
        if missing:
            packages.append(f"{package['name']}={package['version']}={package['build']}")
    return packages


def install_toolkit(root: Path) -> None:
    root = root.absolute()
    installer_root = root.parent
    micromamba = installer_root / "bin/micromamba"
    if not micromamba.is_file():
        raise RuntimeError(f"Managed CUDA installer missing: {micromamba}; run install.sh first")
    repairs = missing_package_specs(root)
    operation = "install" if (root / "conda-meta").is_dir() else "create"
    command = [str(micromamba), "--no-rc", "--root-prefix", str(installer_root / "mamba"),
               operation, "--yes", "--prefix", str(root), "--override-channels",
               "-c", CUDA_CHANNEL, "-c", "conda-forge", "--strict-channel-priority"]
    if repairs:
        print(f"Repairing {len(repairs)} CUDA packages with missing files.", flush=True)
        command.append("--force-reinstall")
    command.extend(["cuda-toolkit=12.5.1", *repairs])
    subprocess.run(command, check=True)
    toolkit_paths(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "missing-packages", "install"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "check":
            toolkit_paths(args.root)
        elif args.operation == "install":
            install_toolkit(args.root)
        else:
            for specification in missing_package_specs(args.root):
                print(specification)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
