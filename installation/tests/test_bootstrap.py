"""Exercise the downloadable Bash entry point with local download/GPU fixtures."""

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def archive_bytes(files, compression):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode=f"w:{compression}") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            payload = content.encode()
            member.size = len(payload)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def cuda_fixture(root, version="12.5"):
    (root / "bin").mkdir(parents=True)
    executable(root / "bin/nvcc", f'#!/bin/sh\necho "Cuda compilation tools, release {version}, V{version}"\n')
    for relative in ("include/cuda_runtime.h", "include/cuda.h", "include/cublas_v2.h",
                     "lib/libcudart.so", "lib/libcublas.so"):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("CUDA layout fixture, not a GPU binary")


def test_bootstrap_dry_run_needs_no_checkout_or_gpu_and_makes_no_files(tmp_path):
    result = subprocess.run(["bash", ROOT / "installation/install.sh", "--dry-run", "--prefix", tmp_path / "absent"],
                            capture_output=True, text=True, check=True)
    assert "website=true" in result.stdout
    assert "CUDA 12.5" in result.stdout
    assert not (tmp_path / "absent").exists()


def test_bootstrap_reuses_explicit_toolkit_despite_cuda13_on_path_and_safe_rerun(tmp_path):
    fixture = tmp_path / "source"
    fixture.mkdir()
    (fixture / "installation/internal").mkdir(parents=True)
    shutil.copyfile(ROOT / "installation/internal/cuda_toolkit.py", fixture / "installation/internal/cuda_toolkit.py")
    support = (ROOT / "installation/internal/gpu_setup_support.py").read_text()
    # Simulate a selected Python whose headers differ from the distro default.
    (fixture / "installation/internal/gpu_setup_support.py").write_text(
        'import os, sysconfig\n'
        'sysconfig.get_paths = lambda **kwargs: {"include": os.environ["FIXTURE_PYTHON_INCLUDE"]}\n'
        + support
    )
    (fixture / "installation/internal/setup_cuda125.py").write_text(
        'import json, os, sys\n'
        'open(os.environ["BOOTSTRAP_CALL"], "w").write(json.dumps({"args": sys.argv[1:], '
        '"tmpdir": os.environ["TMPDIR"], "no_cache": os.environ["PIP_NO_CACHE_DIR"]}))\n'
    )
    (fixture / "installation/start.sh").write_text('echo fixture-services-started\n')
    real_git = shutil.which("git")
    subprocess.run([real_git, "init", "-b", "main", fixture], check=True, capture_output=True)
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
        subprocess.run([real_git, "-C", fixture, "config", key, value], check=True)
    subprocess.run([real_git, "-C", fixture, "add", "."], check=True)
    subprocess.run([real_git, "-C", fixture, "commit", "-m", "Fixture checkout"], check=True, capture_output=True)

    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "uname", '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
    executable(tools / "df", '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "/fixture 62914560 10485760 52428800 17% /fixture"\n')
    executable(tools / "nvidia-smi", '#!/bin/sh\necho "580.159.03"\n')
    executable(tools / "apt-get", f'#!{sys.executable}\n'
        'import json, os, pathlib, sys\n'
        'with open(os.environ["FIXTURE_APT_LOG"], "a") as log: log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
        f'if "python{sys.version_info.major}.{sys.version_info.minor}-dev" in sys.argv:\n'
        '    header = pathlib.Path(os.environ["FIXTURE_PYTHON_INCLUDE"]) / "Python.h"\n'
        '    header.parent.mkdir(parents=True, exist_ok=True)\n'
        '    header.write_text("/* fixture headers */")\n')
    executable(tools / "sudo", '#!/bin/sh\nexec "$@"\n')
    executable(tools / "nvcc", '#!/bin/sh\necho "Cuda compilation tools, release 13.0, V13.0"\n')
    executable(tools / "node", '#!/bin/sh\nexit 1\n')
    executable(tools / "npm", '#!/bin/sh\nexit 1\n')
    executable(tools / "git", f'#!{sys.executable}\n'
        'import os, subprocess, sys\na = sys.argv[1:]\n'
        'if "fetch" in a:\n'
        '    i = a.index("origin", a.index("fetch")); a[i:] = [os.environ["FIXTURE_SOURCE"], "main"]\n'
        f'sys.exit(subprocess.call([{real_git!r}, *a]))\n')

    cuda = tmp_path / "existing CUDA 12.5"
    cuda_fixture(cuda)
    node_name = "node-v22.14.0-linux-x64.tar.xz"
    node_archive = tmp_path / node_name
    node_archive.write_bytes(archive_bytes({
        "node-v22.14.0-linux-x64/bin/node": '#!/bin/sh\nexit 0\n',
        "node-v22.14.0-linux-x64/bin/npm": '#!/bin/sh\nexit 0\n',
    }, "xz"))
    checksums = tmp_path / "checksums"
    checksums.write_text(hashlib.sha256(node_archive.read_bytes()).hexdigest() + "  " + node_name + "\n")
    executable(tools / "curl", f'#!{sys.executable}\n'
        'import os, pathlib, shutil, sys\na=sys.argv[1:]; url=a[-1]; output=a[a.index("--output")+1]\n'
        'assert "nodejs.org" in url, "Unexpected installer download: " + url\n'
        'source = "FIXTURE_CHECKSUMS" if url.endswith("SHASUMS256.txt") else "FIXTURE_NODE"\n'
        'shutil.copyfile(os.environ[source], output)\n')
    executable(tools / "sha256sum", f'#!{sys.executable}\n'
        'import hashlib, pathlib, sys\n'
        'digest, filename=sys.stdin.read().strip().split("  ", 1)\n'
        'sys.exit(0 if hashlib.sha256(pathlib.Path(filename).read_bytes()).hexdigest()==digest else 1)\n')
    prefix = tmp_path / "installation with spaces"
    call = tmp_path / "call.json"
    apt_log = tmp_path / "apt.jsonl"
    environment = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
        SPEECH_SETUP_PYTHON=sys.executable, CUDA_HOME=str(tmp_path / "cuda13"),
        FIXTURE_SOURCE=str(fixture),
        FIXTURE_NODE=str(node_archive), FIXTURE_CHECKSUMS=str(checksums), BOOTSTRAP_CALL=str(call),
        FIXTURE_APT_LOG=str(apt_log), FIXTURE_PYTHON_INCLUDE=str(tmp_path / 'selected-python-headers'))
    command = ["bash", ROOT / "installation/install.sh", "--prefix", prefix, "--cuda-home", cuda, "--skip-models"]
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    apt_commands = [json.loads(line) for line in apt_log.read_text().splitlines()]
    assert any('python3-dev' in command for command in apt_commands)
    assert any(f'python{sys.version_info.major}.{sys.version_info.minor}-dev' in command for command in apt_commands)
    recorded = json.loads(call.read_text())
    arguments = recorded["args"]
    assert recorded["tmpdir"] == str(prefix / "tmp")
    assert recorded["no_cache"] == "1"
    assert "--with-platform" in arguments and "--skip-models" in arguments
    assert arguments[arguments.index("--cuda-home") + 1] == str(cuda)
    assert arguments[arguments.index("--root") + 1] == str(prefix / "runtime")
    assert "Installation prepared. Start when ready:" in result.stdout
    assert "fixture-services-started" not in result.stdout
    assert not (prefix / "mamba").exists()
    assert not (prefix / "cuda-12.5").exists()
    assert not (tmp_path / "cuda13").exists()
    generated_lock = prefix / "minicpm_study/generated-lock.json"
    generated_lock.write_text("untracked generated fixture")
    rerun = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert generated_lock.read_text() == "untracked generated fixture"
    full = subprocess.run(command[:-1], env=environment, capture_output=True, text=True)
    assert full.returncode == 0, full.stdout + full.stderr
    assert "fixture-services-started" in full.stdout
    no_start = subprocess.run([*command[:-1], "--no-start"], env=environment, capture_output=True, text=True)
    assert no_start.returncode == 0, no_start.stdout + no_start.stderr
    assert "fixture-services-started" not in no_start.stdout
    changed = prefix / "minicpm_study/installation/internal/setup_cuda125.py"
    changed.write_text(changed.read_text() + "# local user edit\n")
    rejected = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "Save tracked local changes" in rejected.stderr
    assert changed.read_text().endswith("# local user edit\n")


def test_small_install_volume_is_rejected_before_downloads_or_system_changes(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "uname", '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
    executable(tools / "df", '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "/small 10485760 10485610 150 100% /workspace"\n')
    prefix = tmp_path / "must not be created"
    result = subprocess.run(["bash", ROOT / "installation/install.sh", "--prefix", prefix],
                            env=dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
                                     SPEECH_INSTALL_MIN_FREE_GIB="30"),
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "Not enough disk space" in result.stderr
    assert "30 GiB" in result.stdout
    assert not prefix.exists()


@pytest.mark.parametrize("damage,expected", [
    ("version", "must be CUDA 12.5"),
    ("compiler", "Missing"),
    ("header", "missing cuda_runtime.h"),
    ("library", "missing libcudart.so"),
    ("driver", "below the required"),
])
def test_invalid_host_stops_before_installing_or_downloading(tmp_path, damage, expected):
    tools = tmp_path / "tools"
    tools.mkdir()
    marker = tmp_path / "unexpected-mutation"
    executable(tools / "uname", '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
    executable(tools / "df", '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "/fixture 99999999 0 99999999 0% /fixture"\n')
    driver = "550.54.15" if damage == "driver" else "580.159.03"
    executable(tools / "nvidia-smi", f'#!/bin/sh\necho "{driver}"\n')
    for name in ("apt-get", "curl", "git", "micromamba"):
        executable(tools / name, f'#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 1\n')
    cuda = tmp_path / "toolkit"
    cuda_fixture(cuda, "13.0" if damage == "version" else "12.5")
    if damage == "compiler":
        (cuda / "bin/nvcc").unlink()
    elif damage == "header":
        (cuda / "include/cuda_runtime.h").unlink()
    elif damage == "library":
        (cuda / "lib/libcudart.so").unlink()
        (cuda / "lib/libcudart.so").symlink_to("missing-library")
    prefix = tmp_path / "installation"
    result = subprocess.run(["bash", ROOT / "installation/install.sh", "--prefix", prefix, "--cuda-home", cuda],
                            env=dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}"),
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert expected in result.stderr
    assert not marker.exists()
    assert not prefix.exists()
