"""Control services owned by one installation, including legacy detached launchers."""

import argparse
import fcntl
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

import psutil


class Services:
    names = ("native", "runtime", "study")

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.logs = self.root / "logs"
        self.study_port = int(os.environ.get("SPEECH_STUDY_PORT", "8765"))

    def launcher(self, name):
        return self.root / "bin" / f"start_{name}.sh"

    def processes(self, name):
        """Match exact installation paths; include children and native orphans."""
        found = {}
        for process in psutil.process_iter(["cmdline", "cwd"]):
            try:
                args = process.info["cmdline"] or []
                owned = str(self.launcher(name)) in args
                if name == "native":
                    if any(Path(arg).name == "launch_native.py" for arg in args) and "--logs" in args:
                        index = args.index("--logs") + 1
                        owned |= index < len(args) and Path(args[index]).parent == self.logs
                    backend = self.root / "sources/llama.cpp-omni/build/bin/llama-omni-server"
                    demo = self.root / "sources/MiniCPM-o-Demo"
                    owned |= str(backend) in args
                    owned |= process.info["cwd"] == str(demo) and any(
                        arg in ("gateway.py", "worker.py", str(demo / "gateway.py"), str(demo / "worker.py"))
                        for arg in args
                    )
                else:
                    venv = "venv" if name == "runtime" else "study-venv"
                    owned |= str(self.root / venv / "bin" / f"speech-{name}") in args
                if owned:
                    for child in process.children(recursive=True):
                        found[child.pid] = child
                    found[process.pid] = process
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return list(found.values())

    @staticmethod
    def alive(process):
        try:
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def ports(self, name):
        return {"native": (8000, 9060, 9061, 9062), "runtime": (8766,), "study": (self.study_port,)}[name]

    def ready(self, name, processes):
        if not any(self.alive(p) for p in processes):
            return False
        if name == "native":
            # The launcher writes this only after backend, gateway and worker registration.
            return any(any(self.logs.glob(f"native-*-{p.pid}/manifest.json")) for p in processes)
        port = self.ports(name)[0]
        path = "/health" if name == "runtime" else "/api/health"
        headers = {}
        if name == "runtime" and os.environ.get("SPEECH_RUNTIME_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["SPEECH_RUNTIME_TOKEN"]
        try:
            with urlopen(Request(f"http://127.0.0.1:{port}{path}", headers=headers), timeout=2) as response:
                return response.status == 200
        except OSError:
            return False

    def stop(self, name):
        processes = self.processes(name)
        for method in ("terminate", "kill"):
            for process in processes:
                if self.alive(process):
                    try:
                        getattr(process, method)()
                    except psutil.NoSuchProcess:
                        pass
            deadline = time.monotonic() + (10 if method == "terminate" else 3)
            while any(self.alive(p) for p in processes) and time.monotonic() < deadline:
                time.sleep(0.1)
        if any(self.alive(p) for p in processes):
            raise RuntimeError(f"Could not stop {name}; inspect its processes before continuing.")
        print(f"{name}: stopped", flush=True)

    def start(self, name):
        processes = self.processes(name)
        if processes:
            if self.ready(name, processes):
                print(f"{name}: already running", flush=True)
                return
            raise RuntimeError(f"{name} has existing processes but is not ready. Use restart.sh for this service.")
        for port in self.ports(name):
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError(f"Port {port} is occupied by another process; {name} was not started.")
        log = self.logs / f"{name}-service.log"
        if log.exists():
            log.replace(log.with_suffix(".log.previous"))
        with log.open("wb") as output:
            child = subprocess.Popen(["bash", str(self.launcher(name))], stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                                     close_fds=True)
        print(f"{name}: starting (PID {child.pid}); log: {log}", flush=True)
        deadline = time.monotonic() + (900 if name == "native" else 60)
        next_notice = time.monotonic() + 15
        try:
            while child.poll() is None:
                if self.ready(name, [psutil.Process(child.pid)]):
                    print(f"{name}: ready", flush=True)
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"{name} startup timed out. See {log}")
                if time.monotonic() >= next_notice:
                    print(f"{name}: still starting; see {log}", flush=True)
                    next_notice = time.monotonic() + 15
                time.sleep(0.5)
            tail = log.read_text(errors="replace")[-4000:]
            raise RuntimeError(f"{name} launcher exited ({child.returncode}). See {log}\n{tail}")
        except (Exception, KeyboardInterrupt):
            self.stop(name)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            raise

    def run(self, action, selected):
        names = list(self.names) if selected == "all" else [selected]
        if action in ("stop", "restart"):
            for name in reversed(names):
                self.stop(name)
        if action in ("start", "restart"):
            for name in names:
                if not self.launcher(name).is_file():
                    if selected == "all" and name == "study":
                        continue  # --runtime-only installation
                    raise RuntimeError(f"Missing {self.launcher(name)}. Complete installation, including model downloads.")
                self.start(name)
            if "study" in names and self.launcher("study").is_file():
                print(f"Website on the server: http://127.0.0.1:{self.study_port}", flush=True)
        if action == "status":
            healthy = True
            for name in names:
                processes = self.processes(name)
                if not processes and not self.launcher(name).exists():
                    print(f"{name}: not installed")
                    healthy &= selected == "all" and name == "study"
                    continue
                ready = self.ready(name, processes)
                healthy &= ready
                state = "ready" if ready else ("running, not ready" if processes else "stopped")
                print(f"{name}: {state}; PIDs: {', '.join(str(p.pid) for p in processes) or '-'}")
            return 0 if healthy else 1
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--service", choices=("all", *Services.names), default="all")
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error(f"Installation does not exist: {args.root}")
    services = Services(args.root)
    services.logs.mkdir(exist_ok=True)
    try:
        with (services.logs / "services.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another service command is running. Wait for it to finish.") from None
            return services.run(args.action, args.service)
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
