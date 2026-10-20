"""Validate an existing CUDA development toolkit without changing it."""

import argparse
from pathlib import Path


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
                "Use nvidia/cuda:12.5.1-devel-ubuntu24.04 or provide a complete toolkit with --cuda-home. "
                "See docs/SETUP.md; automatic CUDA installation and repair are not supported."
            )
        found[name] = str(file)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check",))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        toolkit_paths(args.root)
    except (RuntimeError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
