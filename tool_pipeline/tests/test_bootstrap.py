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


def test_bootstrap_dry_run_needs_no_checkout_or_gpu_and_makes_no_files(tmp_path):
    result = subprocess.run(["bash", ROOT / "install.sh", "--dry-run", "--prefix", tmp_path / "absent"],
                            capture_output=True, text=True, check=True)
    assert "website=true" in result.stdout
    assert "CUDA 12.5" in result.stdout
    assert not (tmp_path / "absent").exists()


def test_bootstrap_download_dispatch_cuda13_and_safe_rerun(tmp_path):
    fixture = tmp_path / "source"
    fixture.mkdir()
    (fixture / "tool_pipeline").mkdir()
    (fixture / "tool_pipeline/setup_cuda125.sh").write_text(
        f'#!/usr/bin/env bash\n"$SPEECH_SETUP_PYTHON" -c '
        + shlex.quote('import json, os, sys; open(os.environ["BOOTSTRAP_CALL"], "w").write(json.dumps(sys.argv[1:]))')
        + ' "$@"\n'
    )
    real_git = shutil.which("git")
    subprocess.run([real_git, "init", "-b", "main", fixture], check=True, capture_output=True)
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
        subprocess.run([real_git, "-C", fixture, "config", key, value], check=True)
    subprocess.run([real_git, "-C", fixture, "add", "."], check=True)
    subprocess.run([real_git, "-C", fixture, "commit", "-m", "Fixture checkout"], check=True, capture_output=True)

    tools = tmp_path / "tools"
    tools.mkdir()
    executable(tools / "uname", '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
    executable(tools / "nvidia-smi", '#!/bin/sh\necho "CPU fixture: NVIDIA driver 580, not a GPU measurement"\n')
    executable(tools / "apt-get", '#!/bin/sh\nexit 0\n')
    executable(tools / "sudo", '#!/bin/sh\nexec "$@"\n')
    executable(tools / "nvcc", '#!/bin/sh\necho "Cuda compilation tools, release 13.0, V13.0"\n')
    executable(tools / "node", '#!/bin/sh\nexit 1\n')
    executable(tools / "npm", '#!/bin/sh\nexit 1\n')
    executable(tools / "git", f'#!{sys.executable}\n'
        'import os, subprocess, sys\na = sys.argv[1:]\n'
        'if "fetch" in a:\n'
        '    i = a.index("origin", a.index("fetch")); a[i:] = [os.environ["FIXTURE_SOURCE"], "main"]\n'
        f'sys.exit(subprocess.call([{real_git!r}, *a]))\n')

    micromamba = f'''#!{sys.executable}
import pathlib, sys
args = sys.argv[1:]
prefix = pathlib.Path(args[args.index('--prefix') + 1])
(prefix / 'bin').mkdir(parents=True, exist_ok=True)
(prefix / 'conda-meta').mkdir(exist_ok=True)
compiler = prefix / 'bin/nvcc'
compiler.write_text('#!/bin/sh\\necho "Cuda compilation tools, release 12.5, V12.5"\\n')
compiler.chmod(0o755)
'''
    micromamba_archive = tmp_path / "micromamba.tar.bz2"
    micromamba_archive.write_bytes(archive_bytes({"bin/micromamba": micromamba}, "bz2"))
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
        'source = "FIXTURE_MICROMAMBA" if "micro.mamba" in url else '
        '("FIXTURE_CHECKSUMS" if url.endswith("SHASUMS256.txt") else "FIXTURE_NODE")\n'
        'shutil.copyfile(os.environ[source], output)\n')
    executable(tools / "sha256sum", f'#!{sys.executable}\n'
        'import hashlib, pathlib, sys\n'
        'digest, filename=sys.stdin.read().strip().split("  ", 1)\n'
        'sys.exit(0 if hashlib.sha256(pathlib.Path(filename).read_bytes()).hexdigest()==digest else 1)\n')
    prefix = tmp_path / "installation with spaces"
    call = tmp_path / "call.json"
    environment = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
        SPEECH_SETUP_PYTHON=sys.executable, CUDA_HOME=str(tmp_path / "cuda13"),
        FIXTURE_SOURCE=str(fixture), FIXTURE_MICROMAMBA=str(micromamba_archive),
        FIXTURE_NODE=str(node_archive), FIXTURE_CHECKSUMS=str(checksums), BOOTSTRAP_CALL=str(call))
    command = ["bash", ROOT / "install.sh", "--prefix", prefix, "--skip-models"]
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = json.loads(call.read_text())
    assert "--with-platform" in arguments and "--skip-models" in arguments
    assert arguments[arguments.index("--cuda-home") + 1] == str(prefix / "cuda-12.5")
    assert arguments[arguments.index("--root") + 1] == str(prefix / "runtime")
    assert "SPEECH_STUDY_PORT=8080" in result.stdout
    assert not (tmp_path / "cuda13").exists()
    generated_lock = prefix / "minicpm_study/generated-lock.json"
    generated_lock.write_text("untracked generated fixture")
    rerun = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert generated_lock.read_text() == "untracked generated fixture"
    changed = prefix / "minicpm_study/tool_pipeline/setup_cuda125.sh"
    changed.write_text(changed.read_text() + "# local user edit\n")
    rejected = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "Save tracked local changes" in rejected.stderr
    assert changed.read_text().endswith("# local user edit\n")
