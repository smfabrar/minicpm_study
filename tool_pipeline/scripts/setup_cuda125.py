"""Set up the standalone speech pipeline on Linux x86_64 with CUDA 12.5."""

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PIPELINE_DIR))
from launch_native import DEMO_REVISION, NATIVE_REVISION  # noqa: E402


@dataclass(frozen=True)
class SetupConfiguration:
    root: Path
    reference: Path
    cuda_home: Path
    jobs: int
    architectures: str | None
    install_system_deps: bool
    download_models: bool
    dry_run: bool
    with_platform: bool = False

    @property
    def python(self) -> Path:
        return self.root / "venv/bin/python"

    @property
    def upstream(self) -> Path:
        return self.root / "sources/llama.cpp-omni"

    @property
    def demo(self) -> Path:
        return self.root / "sources/MiniCPM-o-Demo"

    @property
    def patch(self) -> Path:
        return self.reference / "fixtures/realtime-tool-context.patch"


class CommandRunner:
    def __init__(self, environment: dict[str, str]):
        self.environment = environment

    def run(self, command: list[str | Path], *, capture: bool = False) -> str:
        arguments = [str(value) for value in command]
        print("+ " + shlex.join(arguments), flush=True)
        result = subprocess.run(arguments, check=True, env=self.environment, text=True,
                                stdout=subprocess.PIPE if capture else None)
        return result.stdout or ""

    def support(self, config: SetupConfiguration, operation: str, *arguments: str) -> dict:
        output = self.run([config.python, SCRIPT_DIR / "gpu_setup_support.py", operation,
                           *arguments], capture=True)
        lines = output.splitlines()
        for line in reversed(lines):
            if line.startswith("SETUP_RESULT="):
                print("\n".join(lines[:lines.index(line)]), end="")
                return json.loads(line.removeprefix("SETUP_RESULT="))
        raise RuntimeError(f"No setup result returned by {operation}")


class HostPreflight:
    def __init__(self, config: SetupConfiguration, runner: CommandRunner):
        self.config, self.runner = config, runner

    def verify(self) -> dict:
        if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
            raise RuntimeError("This setup targets Linux x86_64 NVIDIA servers")
        if not (3, 11) <= sys.version_info[:2] < (3, 13):
            raise RuntimeError("Run setup using Python 3.11 or 3.12")
        for file in (self.config.patch, self.config.reference / "pyproject.toml",
                     PIPELINE_DIR.parent / "speech_contracts/pyproject.toml"):
            if not file.is_file():
                raise RuntimeError(f"Copy the sibling project directories first; missing {file}")
        nvcc = self.config.cuda_home / "bin/nvcc"
        if not nvcc.is_file():
            raise RuntimeError(f"CUDA toolkit missing: {nvcc}; specify --cuda-home")
        version = self.runner.run([nvcc, "--version"], capture=True)
        if not re.search(r"release 12\.5[,\s]", version):
            raise RuntimeError("nvcc must be CUDA 12.5; nvidia-smi's CUDA label is not a toolkit check")
        output = self.runner.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                                  "--format=csv,noheader,nounits"], capture=True)
        devices = [{"name": row[0].strip(), "driver": row[1].strip(),
                    "memory_mib": int(row[2])} for row in csv.reader(output.splitlines())]
        if not devices:
            raise RuntimeError("No NVIDIA GPU is visible to nvidia-smi")
        for device in devices:
            version_parts = tuple(int(part) for part in device["driver"].split("."))
            if version_parts < (555, 42, 2):
                raise RuntimeError("Use driver >=555.42.02 for this CUDA 12.5 setup; update it separately")
        return {"python": sys.version, "platform": platform.platform(), "nvcc": version,
                "nvidia_devices": devices, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}

    def prerequisites(self) -> None:
        if self.config.install_system_deps:
            if shutil.which("apt-get") is None:
                raise RuntimeError("--install-system-deps supports Debian/Ubuntu apt-get only")
            prefix = [] if os.geteuid() == 0 else ["sudo"]
            self.runner.run([*prefix, "apt-get", "update"])
            self.runner.run([*prefix, "apt-get", "install", "-y", "build-essential", "gcc-12",
                             "g++-12", "git", "ninja-build", "pkg-config", "espeak-ng",
                             "libsndfile1", "ca-certificates"])
        for name in ("git", "gcc-12", "g++-12", "ninja", "espeak-ng"):
            if shutil.which(name) is None:
                raise RuntimeError(f"Missing {name}; install prerequisites or use --install-system-deps")
        if self.config.with_platform:
            frontend = PIPELINE_DIR.parent / "study_platform/frontend"
            if not (frontend / "package.json").is_file():
                raise RuntimeError("--with-platform requires the sibling study_platform directory")
            node_version = self.runner.run(["node", "--version"], capture=True).strip()
            match = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)", node_version)
            if not match or tuple(map(int, match.groups())) < (22, 12, 0):
                raise RuntimeError("--with-platform requires Node 22.12+ and npm; install Node separately")
            if shutil.which("npm") is None:
                raise RuntimeError("--with-platform requires npm")


class EnvironmentInstaller:
    def __init__(self, config: SetupConfiguration, runner: CommandRunner):
        self.config, self.runner = config, runner

    def install(self) -> None:
        config = self.config
        if not config.python.exists():
            self.runner.run([sys.executable, "-m", "venv", config.root / "venv"])
        self.runner.run([config.python, "-m", "pip", "install", "--upgrade", "pip", "setuptools",
                         "wheel", "cmake>=3.24,<4"])
        self.runner.run([config.python, "-m", "pip", "install", "torch==2.6.0+cu124",
                         "torchaudio==2.6.0+cu124", "--index-url",
                         "https://download.pytorch.org/whl/cu124"])
        self.runner.run([config.python, "-m", "pip", "install", "-c",
                         SCRIPT_DIR / "constraints-cuda125.txt", "-e",
                         PIPELINE_DIR.parent / "speech_contracts", "-e", config.reference,
                         "-e", f"{PIPELINE_DIR}[models]", "-r", SCRIPT_DIR / "requirements-gateway.txt"])
        self.runner.run([config.python, "-m", "pip", "install", "-c",
                         SCRIPT_DIR / "constraints-cuda125.txt",
                         "https://github.com/explosion/spacy-models/releases/download/"
                         "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"])
        self.runner.run([config.python, "-m", "pip", "check"])


class NativeBuilder:
    def __init__(self, config: SetupConfiguration, runner: CommandRunner):
        self.config, self.runner = config, runner

    def checkout(self, path: Path, repository: str, revision: str) -> None:
        if not path.exists() or (path.is_dir() and not any(path.iterdir())):
            # Dedicated directories only; never reset or clean an existing checkout.
            path.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run(["git", "init", path])
        if not (path / ".git").exists():
            raise RuntimeError(f"{path} is not a source checkout; use a new --root")
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                              capture_output=True, text=True, env=self.runner.environment)
        if head.returncode == 0:
            if head.stdout.strip() != revision:
                raise RuntimeError(f"{path} has a different revision; use a new --root")
        else:
            origin = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                                    capture_output=True, text=True, env=self.runner.environment)
            if origin.returncode:
                status = self.runner.run(["git", "-C", path, "status", "--porcelain"], capture=True)
                if status.strip():
                    raise RuntimeError(f"Uninitialized checkout contains files: {path}; use a new --root")
                self.runner.run(["git", "-C", path, "remote", "add", "origin", repository])
            elif origin.stdout.strip() != repository:
                raise RuntimeError(f"Unexpected source remote in {path}; use a new --root")
            self.runner.run(["git", "-C", path, "fetch", "--depth", "1", "origin", revision])
            self.runner.run(["git", "-C", path, "checkout", "--detach", revision])
        actual = self.runner.run(["git", "-C", path, "rev-parse", "HEAD"], capture=True).strip()
        if actual != revision:
            raise RuntimeError(f"Unexpected source revision in {path}")

    def build(self, architectures: str) -> list[str]:
        config = self.config
        self.checkout(config.upstream, "https://github.com/tc-mb/llama.cpp-omni.git", NATIVE_REVISION)
        self.checkout(config.demo, "https://github.com/OpenBMB/MiniCPM-o-Demo.git", DEMO_REVISION)
        applied = subprocess.run(["git", "-C", str(config.upstream), "apply", "--reverse",
                                  "--check", str(config.patch)], capture_output=True,
                                 env=self.runner.environment)
        if applied.returncode:
            self.runner.run(["git", "-C", config.upstream, "apply", "--check", config.patch])
            self.runner.run(["git", "-C", config.upstream, "apply", config.patch])
        self.verify_changes(config.upstream, NATIVE_REVISION, config.patch)
        self.verify_changes(config.demo, DEMO_REVISION)
        options = ["-DCMAKE_BUILD_TYPE=Release", "-DGGML_CUDA=ON", "-DGGML_CUDA_NO_VMM=ON",
                   "-DGGML_NATIVE=OFF", f"-DCMAKE_CUDA_ARCHITECTURES={architectures}",
                   f"-DCMAKE_CUDA_COMPILER={config.cuda_home / 'bin/nvcc'}",
                   "-DCMAKE_C_COMPILER=gcc-12", "-DCMAKE_CXX_COMPILER=g++-12",
                   "-DCMAKE_CUDA_HOST_COMPILER=g++-12", "-DLLAMA_CURL=OFF", "-DLLAMA_OPENSSL=OFF",
                   "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF"]
        cmake = config.root / "venv/bin/cmake"
        self.runner.run([cmake, "-S", config.upstream, "-B", config.upstream / "build", "-G",
                         "Ninja", *options])
        self.runner.run([cmake, "--build", config.upstream / "build", "--target",
                         "llama-omni-server", "--parallel", str(config.jobs)])
        if not (config.demo / "assets/ref_audio/ref_en_dlc_1.wav").is_file():
            raise RuntimeError("The official Demo reference WAV is missing")
        return options

    def verify_changes(self, path: Path, revision: str, patch: Path | None = None) -> None:
        # Compare against the pinned tree plus our patch using a temporary index.
        # The actual checkout/index are never reset or rewritten.
        with tempfile.TemporaryDirectory(prefix="speech-source-check-") as directory:
            environment = {**self.runner.environment, "GIT_INDEX_FILE": str(Path(directory) / "index")}
            commands = [["git", "-C", str(path), "read-tree", revision]]
            if patch is not None:
                commands.append(["git", "-C", str(path), "apply", "--cached", str(patch)])
            commands.append(["git", "-C", str(path), "diff", "--exit-code"])
            for command in commands:
                result = subprocess.run(command, env=environment, capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(f"Unexpected tracked source changes in {path}; use a new --root")


class StudyInstaller:
    def __init__(self, config: SetupConfiguration, runner: CommandRunner):
        self.config, self.runner = config, runner

    def install(self) -> None:
        config = self.config
        python = config.root / "study-venv/bin/python"
        if not python.exists():
            self.runner.run([sys.executable, "-m", "venv", config.root / "study-venv"])
        self.runner.run([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        study = PIPELINE_DIR.parent / "study_platform"
        self.runner.run([python, "-m", "pip", "install", "-e",
                         PIPELINE_DIR.parent / "speech_contracts", "-e", study])
        self.runner.run([python, "-m", "pip", "check"])
        frontend = study / "frontend"
        install_command = "ci" if (frontend / "package-lock.json").is_file() else "install"
        self.runner.run(["npm", "--prefix", frontend, install_command])
        self.runner.run(["npm", "--prefix", frontend, "run", "build"])


def select_architectures(configured: str | None, devices: list[dict], supported: str) -> str:
    values = configured.split(";") if configured else sorted({d["architecture"] for d in devices})
    if not values or any(not re.fullmatch(r"[0-9]+", value) for value in values):
        raise ValueError("CUDA architectures must be integer SM versions, e.g. '80;86'")
    available = set(re.findall(r"sm_([0-9]+)", supported))
    if any(value not in available for value in values):
        raise ValueError(f"CUDA 12.5 cannot compile architectures {values}; supported: {sorted(available)}")
    required = {device["architecture"] for device in devices}
    if not required.issubset(values):
        raise ValueError(f"Architecture selection must include visible GPUs: {sorted(required)}")
    return ";".join(values)


class LaunchFiles:
    def __init__(self, config: SetupConfiguration, runner: CommandRunner):
        self.config, self.runner = config, runner

    def write(self, probe: dict, models: dict | None) -> None:
        config = self.config
        (config.root / "bin").mkdir(exist_ok=True)
        (config.root / "logs").mkdir(exist_ok=True)
        library_paths = ":".join(probe["library_paths"])
        activation = (f"source {shlex.quote(str(config.root / 'venv/bin/activate'))}\n"
                      f"export CUDA_HOME={shlex.quote(str(config.cuda_home))}\n"
                      f"export HF_HOME={shlex.quote(str(config.root / 'models/cache'))}\n"
                      f"export LD_LIBRARY_PATH={shlex.quote(library_paths)}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}\n")
        (config.root / "activate.sh").write_text("# Source this file in bash.\n" + activation)
        self.script("start_runtime.sh", [config.root / "venv/bin/speech-runtime", "--host",
                    "127.0.0.1", "--port", "8766", "--data", config.root / "data/runtime"])
        if config.with_platform:
            study_command = shlex.join([str(config.root / "study-venv/bin/speech-study"),
                                        "--data", str(config.root / "data/platform")])
            frontend = PIPELINE_DIR.parent / "study_platform/frontend/dist"
            path = config.root / "bin/start_study.sh"
            path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
                            f"export SPEECH_STUDY_FRONTEND={shlex.quote(str(frontend))}\n"
                            'export SPEECH_RUNTIME_URL="${SPEECH_RUNTIME_URL:-http://127.0.0.1:8766}"\n'
                            f'exec {study_command} --port "${{SPEECH_STUDY_PORT:-8765}}"\n')
            path.chmod(0o755)
        if models is None:
            return
        native_args = [config.python, PIPELINE_DIR / "launch_native.py", "--upstream",
                       config.upstream, "--demo", config.demo, "--model",
                       Path(models["native"]["path"]) / "MiniCPM-o-4_5-Q4_K_M.gguf",
                       "--patch", config.patch]
        self.script("start_native.sh", native_args, native=True)
        restart = config.root / "bin/restart_native.sh"
        restart.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexec bash " + shlex.join([
            str(PIPELINE_DIR / "restart_native.sh"), str(config.root),
        ]) + "\n")
        restart.chmod(0o755)
        settings = self.runner.support(config, "settings", "--models", json.dumps(models),
                                       "--demo", str(config.demo), "--patch", str(config.patch),
                                       "--device-count", str(len(probe["devices"])))
        (config.root / "run-settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    def script(self, name: str, arguments: list[str | Path], native: bool = False) -> None:
        config = self.config
        content = ("#!/usr/bin/env bash\nset -euo pipefail\n"
                   f"source {shlex.quote(str(config.root / 'activate.sh'))}\n")
        if native:
            content += (f"logs={shlex.quote(str(config.root / 'logs'))}/native-$(date -u +%Y%m%dT%H%M%S)-$$\n")
        content += "exec " + shlex.join([str(argument) for argument in arguments])
        content += ' --logs "$logs"' if native else ""
        path = config.root / "bin" / name
        path.write_text(content + "\n")
        path.chmod(0o755)


def dry_run(config: SetupConfiguration) -> None:
    print(f"Dry run only; no files, packages or services will be changed. Root: {config.root}")
    print("1. Verify Linux x86_64, Python 3.11/3.12, driver >=555.42.02 and nvcc 12.5.")
    print("2. " + ("Install apt prerequisites." if config.install_system_deps else "Check system prerequisites."))
    print("3. Create an isolated venv; install Torch 2.6.0 cu124 and constrained pipeline/gateway dependencies.")
    print(f"4. Exercise CUDA and detect GPU architectures ({config.architectures or 'automatic'}).")
    print(f"5. Check out native {NATIVE_REVISION} and Demo {DEMO_REVISION}; apply the reference patch.")
    print(f"6. Build llama-omni-server with CUDA 12.5/GCC 12, Ninja and {config.jobs} parallel jobs.")
    print("7. Verify imports, cuBLAS/cuDNN libraries and gateway/worker commands.")
    print("8. " + ("Download pinned MiniCPM/Granite/Whisper/Kokoro snapshots and write run-settings.json."
                       if config.download_models else "Skip weight downloads and native launch/settings generation."))
    print("9. Write activation/launch scripts, pip freeze and setup-manifest.json; start services separately.")
    if config.with_platform:
        print("10. Check Node 22.12+/npm, install the study backend in a separate venv, and build the frontend.")


def setup(config: SetupConfiguration) -> None:
    if config.dry_run:
        dry_run(config)
        return
    environment = dict(os.environ)
    environment.update(CUDA_HOME=str(config.cuda_home), HF_HOME=str(config.root / "models/cache"),
                       PIP_NO_CACHE_DIR="1", TMPDIR=str(config.root / "tmp"))
    environment["PATH"] = f"{config.cuda_home / 'bin'}:{environment.get('PATH', '')}"
    runner = CommandRunner(environment)
    preflight = HostPreflight(config, runner)
    host = preflight.verify()
    preflight.prerequisites()
    config.root.mkdir(parents=True, exist_ok=True)
    (config.root / "tmp").mkdir(exist_ok=True)
    EnvironmentInstaller(config, runner).install()
    probe = runner.support(config, "probe")
    supported = runner.run([config.cuda_home / "bin/nvcc", "--list-gpu-code"], capture=True)
    architectures = select_architectures(config.architectures, probe["devices"], supported)
    options = NativeBuilder(config, runner).build(architectures)
    environment["LD_LIBRARY_PATH"] = ":".join(probe["library_paths"] +
                                              ([environment["LD_LIBRARY_PATH"]] if environment.get("LD_LIBRARY_PATH") else []))
    verified = runner.support(config, "verify")
    for script in ("gateway.py", "worker.py"):
        # The scripts use cwd-relative assets/configuration.
        command = [str(config.python), script, "--help"]
        subprocess.run(command, cwd=config.demo, env=environment, check=True, stdout=subprocess.DEVNULL)
    models = runner.support(config, "download", "--root", str(config.root / "models")) if config.download_models else None
    if config.with_platform:
        StudyInstaller(config, runner).install()
    LaunchFiles(config, runner).write(probe, models)
    frozen = runner.run([config.python, "-m", "pip", "freeze"], capture=True)
    (config.root / "requirements-resolved.txt").write_text(frozen)
    manifest = {"completed_at": datetime.now(timezone.utc).isoformat(), "host": host,
                "gpu_probe": probe, "dependencies": verified, "models": models,
                "native_revision": NATIVE_REVISION, "gateway_revision": DEMO_REVISION,
                "patch_sha256": hashlib.sha256(config.patch.read_bytes()).hexdigest(),
                "architectures": architectures, "build_options": options}
    if config.with_platform:
        study_python = config.root / "study-venv/bin/python"
        (config.root / "study-requirements-resolved.txt").write_text(
            runner.run([study_python, "-m", "pip", "freeze"], capture=True))
    (config.root / "setup-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Setup complete. Launch scripts: {config.root / 'bin'}")
    print("CUDA allocation and dependency checks passed; model inference is not benchmarked by setup.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PIPELINE_DIR / ".gpu",
                        help="Dedicated setup directory (default: tool_pipeline/.gpu)")
    nested_reference = PIPELINE_DIR.parent / "minicpm_tool"
    default_reference = (
        nested_reference if nested_reference.is_dir() else PIPELINE_DIR.parent.parent / "minicpm_tool"
    )
    parser.add_argument("--reference", type=Path, default=default_reference,
                        help="minicpm_tool checkout; default: sibling of the minicpm_study repository")
    parser.add_argument("--cuda-home", type=Path, default=Path("/usr/local/cuda-12.5"))
    parser.add_argument("--jobs", type=int, default=2, help="Parallel native compilation jobs")
    parser.add_argument("--architectures", help="SM versions separated by semicolons; default: detect visible GPUs")
    parser.add_argument("--install-system-deps", action="store_true", help="Install Ubuntu/Debian apt prerequisites")
    parser.add_argument("--skip-models", action="store_true", help="Build/install only; do not download model weights")
    parser.add_argument("--dry-run", action="store_true", help="Describe steps without touching the machine")
    parser.add_argument("--with-platform", action="store_true",
                        help="Also install the separate study backend and build its frontend (Node 22.12+)")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    config = SetupConfiguration(args.root.resolve(), args.reference.resolve(), args.cuda_home.resolve(),
                                args.jobs, args.architectures, args.install_system_deps,
                                not args.skip_models, args.dry_run, args.with_platform)
    try:
        setup(config)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Setup failed: {exc}\nFix the reported prerequisite and rerun with the same --root.\n")


if __name__ == "__main__":
    main()
