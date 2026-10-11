"""Start the already-built pinned MiniCPM backend, official gateway and worker."""
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

NATIVE_REVISION = '873056743b74e1a4ce5dcf7290e2298428e214db'
DEMO_REVISION = '47709a9210dfd71afa76c058e017fc8c4db5c8d2'


def revision(directory: Path) -> str:
    return subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()


@dataclass(frozen=True)
class NativeConfiguration:
    upstream: Path
    demo: Path
    model: Path
    patch: Path
    logs: Path
    backend_port: int
    gateway_port: int
    worker_port: int
    internal_port: int

    def verify(self) -> Path:
        if revision(self.upstream) != NATIVE_REVISION or revision(self.demo) != DEMO_REVISION:
            raise ValueError('Source checkouts do not match the pinned native and Demo revisions')
        subprocess.run(['git', '-C', str(self.upstream), 'apply', '--reverse', '--check', str(self.patch)], check=True)
        server = self.upstream / 'build/bin/llama-omni-server'
        if not server.is_file() or not self.model.is_file():
            raise ValueError('Build llama-omni-server and download the complete GGUF module layout first')
        return server


class NativeStack:
    def __init__(self, config: NativeConfiguration):
        self.config = config
        self.processes: list[subprocess.Popen] = []
        self.handles = []

    def launch(self, name: str, command: list[str], cwd: Path) -> subprocess.Popen:
        log = (self.config.logs / f'{name}.log').open('w')
        self.handles.append(log)
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(process)
        return process

    @staticmethod
    def wait_ready(process: subprocess.Popen, port: int, timeout: int = 600) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Service on port {port} exited; inspect its log')
            try:
                with urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(1)
        raise TimeoutError(f'Service on port {port} did not become ready')

    def start(self) -> None:
        config = self.config
        binary = config.verify()
        config.logs.mkdir(parents=True, exist_ok=False)
        backend = self.launch('backend', [str(binary), '-m', str(config.model), '-ngl', '99', '-c', '4096', '--host', '127.0.0.1', '--port', str(config.backend_port)], config.upstream)
        self.wait_ready(backend, config.backend_port)
        gateway = self.launch('gateway', [sys.executable, 'gateway.py', '--host', '127.0.0.1', '--port', str(config.gateway_port), '--internal-port', str(config.internal_port), '--http'], config.demo)
        self.wait_ready(gateway, config.gateway_port, 120)
        worker = self.launch('worker', [sys.executable, 'worker.py', '--host', '127.0.0.1', '--port', str(config.worker_port), '--gpu-id', '0', '--backend-server-url', f'http://127.0.0.1:{config.backend_port}'], config.demo)
        self.wait_ready(worker, config.worker_port, 120)
        registration = Request(f'http://127.0.0.1:{config.internal_port}/internal/workers/study-gpu', data=json.dumps({'endpoint': f'127.0.0.1:{config.worker_port}', 'gpu_group': 'study-gpu'}).encode(), headers={'Content-Type': 'application/json'}, method='PUT')
        with urlopen(registration, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('Worker registration failed')
        manifest = {'native_revision': revision(config.upstream), 'gateway_revision': revision(config.demo), 'patch_sha256': hashlib.sha256(config.patch.read_bytes()).hexdigest(), 'model': str(config.model), 'context_size': 4096, 'native_url': f'ws://127.0.0.1:{config.gateway_port}/v1/realtime?mode=audio', 'reference_audio': str(config.demo / 'assets/ref_audio/ref_en_dlc_1.wav')}
        (config.logs / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest, indent=2), flush=True)
        while all(process.poll() is None for process in self.processes):
            time.sleep(1)
        raise RuntimeError('A native service exited; inspect logs')

    def close(self) -> None:
        for process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in self.processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for handle in self.handles:
            handle.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--logs', type=Path, required=True)
    parser.add_argument('--backend-port', type=int, default=9060)
    parser.add_argument('--gateway-port', type=int, default=8000)
    parser.add_argument('--worker-port', type=int, default=9061)
    parser.add_argument('--internal-port', type=int, default=9062)
    args = parser.parse_args()
    config = NativeConfiguration(**{key: value.resolve() if isinstance(value, Path) else value for key, value in vars(args).items()})
    stack = NativeStack(config)
    try:
        stack.start()
    except KeyboardInterrupt:
        pass
    finally:
        stack.close()


if __name__ == '__main__':
    main()
