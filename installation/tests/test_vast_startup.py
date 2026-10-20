"""Exercise first boot, reboot and download failures without GPU or network access."""

import json
import os
from pathlib import Path
import subprocess
import time

import pytest

VAST = Path(__file__).resolve().parents[1] / "vast"


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + content)
    path.chmod(0o755)


@pytest.mark.parametrize("installed,download_failure", [(False, False), (True, False), (False, True)])
def test_boot_lifecycle(tmp_path, installed, download_failure):
    prefix = tmp_path / "installation with spaces"
    tools = tmp_path / "tools"
    executable(tools / "flock", "exit 0\n")
    executable(tools / "apt-get", "exit 0\n")
    installer = tmp_path / "installer-fixture.sh"
    installer.write_text('printf "%s\\n" "$@" > "$SPEECH_INSTALL_PREFIX/install-arguments"\n')
    executable(tools / "curl", '''
if [[ "$DOWNLOAD_FAILURE" == yes ]]; then echo 'fixture download failure' >&2; exit 22; fi
while (($#)); do
    if [[ "$1" == --output ]]; then cp "$INSTALLER_FIXTURE" "$2"; exit 0; fi
    shift
done
exit 2
''')
    if installed:
        run = prefix / "runtime"
        run.mkdir(parents=True)
        (run / "setup-manifest.json").write_text("{}")
        for name in ("native", "runtime", "study"):
            executable(run / "bin" / f"start_{name}.sh", "exit 0\n")
        executable(prefix / "minicpm_study/installation/start.sh",
                   'printf "%s\\n" "$@" > "$SPEECH_INSTALL_PREFIX/start-arguments"\n')
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               SPEECH_INSTALL_PREFIX=str(prefix), INSTALLER_FIXTURE=str(installer),
               DOWNLOAD_FAILURE="yes" if download_failure else "no")
    subprocess.run(["bash", VAST / "onstart.sh"], env=env, check=True, capture_output=True, timeout=5)
    log = prefix / "logs/vast-startup.log"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        output = log.read_text() if log.exists() else ""
        if "MiniCPM Study ready." in output or "Startup failed" in output:
            break
        time.sleep(0.02)
    else:
        pytest.fail("Background startup did not finish")
    if download_failure:
        assert "fixture download failure" in output and "Startup failed" in output
        assert "MiniCPM Study ready." not in output
        assert not (prefix / "install-arguments").exists()
    elif installed:
        assert (prefix / "start-arguments").read_text().strip() == str(prefix / "runtime")
        assert not (prefix / "install-arguments").exists()
    else:
        args = (prefix / "install-arguments").read_text().splitlines()
        assert args[args.index("--prefix") + 1] == str(prefix)
        assert args[args.index("--cuda-home") + 1] == "/usr/local/cuda-12.5"
        assert len(args[args.index("--ref") + 1]) == 40


def test_template_embeds_current_startup_script():
    template = json.loads((VAST / "template.json").read_text())
    assert template["onstart"] == (VAST / "onstart.sh").read_text()
    assert template["private"] is True
    assert template["runtype"] == "ssh"
