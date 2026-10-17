# Installation investigation — 2026-10-17

Status: source audit and supplied-log analysis complete; server cache diagnosis pending.
This document proposes changes. It does not claim an installer fix or GPU validation.

## Objective

Provide repeatable installation and recovery on rented NVIDIA GPU machines, with a
clear compatibility check before expensive downloads or compilation. Preserve the
separate study backend and tool pipeline. Unsupported machines should receive a
specific explanation before installation changes their environment.

## What the evidence establishes

1. The original CUDA prefix was incomplete. `nvcc` reported 12.5.82 and Conda
   listed development packages, but `targets/x86_64-linux` and `cuda_runtime.h`
   were absent. The listed `libcudart.so` filenames do not prove usable libraries:
   they may be dangling symlinks. CMake therefore could not find the development
   runtime it needed.
2. The repair failed inside micromamba while linking
   `cuda-cccl_linux-64-12.5.39-0.tar.bz2`. It could not obtain an extracted package
   directory that its cache validator accepted. Compilation had not started.
3. The installer previously accepted the compiler version as evidence of a
   complete toolkit. Commit `6451af4` added file validation, but its repair still
   operates in the existing environment and reuses micromamba's configured caches.
   `--force-reinstall` is not a guarantee of a new download into a clean cache.
4. The supplied RTX 3060 / driver 580 environment is not explained by an
   insufficient driver for this CUDA 12.5 profile. Newer NVIDIA drivers support
   older CUDA applications through backward compatibility.

The initiating cause of missing package files is **not yet established**. Possible
causes include interrupted extraction, missing cache payloads, filesystem limits,
or package-manager cache validation bugs. These require different remedies.

Mamba upstream reported the same linking failure in issue #4322 and merged a
stale-negative-cache fix in #4328. That is a relevant lead, not proof that this
server encountered the same bug. Its micromamba version and cache contents have
not been inspected. Direct SSH from this development environment is blocked.

Sources:

- [Mamba cache failure report](https://github.com/mamba-org/mamba/issues/4322)
- [Mamba cache validation fix](https://github.com/mamba-org/mamba/pull/4328)
- [Mamba linking/cache recovery implementation](https://github.com/mamba-org/mamba/blob/main/libmamba/src/core/transaction.cpp)
- [NVIDIA CUDA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

## Confirmed installer weaknesses

| Area | Current behavior | Required improvement |
| --- | --- | --- |
| Reproducibility | `install.sh` downloads latest micromamba and Node 22; Python dependencies include version ranges; model commits are resolved on first installation | Version each release with exact artifacts, hashes, package locks, model revisions, native revisions, and patch hash |
| Validation order | Full toolkit installation happens before the detailed driver check; GPU architecture detection follows Python installation | Inspect host, visible devices, driver, architecture, permissions, disk and inode availability first |
| Cache recovery | Repair reuses existing cache configuration and mutates the partially installed prefix | Inspect and record cache state; use a dedicated cache; quarantine invalid artifacts and permit one bounded refetch; preserve a usable installation |
| Completion | Some stages use directory/package presence as reuse evidence | Verify each stage's outputs and inputs before marking it complete; do not skip a stage just because its directory exists |
| Resource use | Full CUDA toolkit and source build on every fresh machine; fixed fresh-install disk floor | Ship prebuilt artifacts where possible; estimate remaining peak download, extraction, build, and model space per filesystem; bound jobs by available memory and CPU quota |
| Diagnostics | Completion manifest is written at the end; failures can precede useful provenance | Write an initial environment report and append stage logs/results, including exact tool versions, commands, cache locations, and failed validation |
| Readiness | Existing checks exercise Torch and imports, but do not validate full model inference | Report installation, service startup, and end-to-end inference readiness as separate states |

Relevant source: `install.sh`, `tool_pipeline/scripts/cuda_toolkit.py`,
`tool_pipeline/scripts/setup_cuda125.py`, and
`tool_pipeline/scripts/gpu_setup_support.py`.

## Compatibility contract

“Any NVIDIA GPU with CUDA” is too broad. Compatibility depends on GPU architecture,
driver, OS/CPU architecture, runtime libraries, and memory. A GPU can be visible to
`nvidia-smi` while an application's compiled kernels or libraries cannot run on it.

Start with a validated Linux x86_64 profile for the RTX 3060 and the current
MiniCPM pipeline. Expand the support matrix only after testing additional GPU
families. Keep the current driver floor explicit until lower versions have been
validated. Treat VRAM requirements as model/configuration measurements, not merely
as installation requirements.

Newer architectures need their own tested stack when the current compiler and
wheels do not support them. For example, native Blackwell compilation requires a
newer toolkit than the project's 12.5 profile. CUDA 12.8 introduced Blackwell
support; changing only the detected CMake architecture is insufficient.

Sources:

- [CUDA 12.5 host platform requirements](https://docs.nvidia.com/cuda/archive/12.5.1/cuda-installation-guide-linux/index.html)
- [NVIDIA Blackwell compatibility guidance](https://docs.nvidia.com/cuda/archive/12.8.2/blackwell-compatibility-guide/index.html)

## Recommended deployment design

### Primary: versioned application image for rented machines

Build an application image from a pinned NVIDIA CUDA base-image digest. Install
locked Python dependencies, compile the patched native server for the declared
GPU architectures, and build the frontend during release creation. Publish the
image by immutable digest only after GPU smoke tests pass.

For Vast, select the application image when creating the instance. This avoids
depending on nested Docker being available inside an existing rented container.
On a conventional Docker host, the NVIDIA Container Toolkit must expose the GPU.
The host still supplies the compatible NVIDIA driver.

Store model downloads, recordings, SQLite data, and logs in a separate persistent
directory. Resolve model revisions in the release manifest, verify their complete
layout, and resume interrupted downloads. Start the three existing services with
explicit ports and process supervision, and report each service's health.

The downloaded shell entry point remains a small compatibility checker and
launcher. It selects a supported release and produces an actionable failure if
the required runtime is unavailable. It must not silently switch to an untested
installation method.

Reference: [NVIDIA container runtime prerequisites](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

### Secondary: native installation on explicitly supported Ubuntu releases

Keep one documented native path for users who cannot use the image. Install a
versioned, verified NVIDIA toolkit through a supported toolkit-only mechanism;
do not replace the machine's driver. Use the same application dependency locks
and model manifest as the image.

If micromamba remains in this path, pin its tested binary and checksum, specify
the cache location explicitly, and validate real extraction/reinstallation in
Linux integration tests. An unverified retry with a new cache is not sufficient
evidence that the current failure has been fixed.

Install releases into their final versioned directories, verify them there, and
atomically switch a launcher pointer after success. Do not rename an installed
Python/Conda environment as a promotion mechanism: embedded paths may break.
Use an installation lock to prevent concurrent mutation. Resume completed stages
only when their manifest inputs and validated outputs still match.

## Verification before claiming reliability

- Linux integration checks: first installation, unchanged rerun, interrupted
  download, corrupted archive/extracted cache, insufficient disk/inodes, and
  simultaneous installer invocation.
- GPU checks: actual CUDA operation, native model initialization, short Kokoro
  synthesis, Whisper transcription, Granite call, and one short B0/B1/B2 run with
  expected artifacts and context acknowledgements where applicable.
- Release reproducibility: rebuild from locked inputs, record artifacts and
  hashes, and test a clean machine for every claimed GPU profile.
- Recovery: keep the previous successful release usable after a failed update;
  preserve study data and provide the failed stage's report.

CPU mocks are useful for installer control flow. They cannot establish real
micromamba extraction, CUDA compilation, GPU compatibility, or model readiness.

## Immediate evidence needed from this server

Run these read-only commands on the GPU server:

```bash
base=/workspace/minicpm-study-install
"$base/bin/micromamba" --version
"$base/bin/micromamba" --no-rc --root-prefix "$base/mamba" info
printenv CONDA_PKGS_DIRS MAMBA_PKGS_DIRS CONDA_SUBDIR
df -h "$base"
df -i "$base"
```

Then inspect the actual cache locations reported by micromamba for the failed
CCCL archive, extracted payload, and package metadata. Compare checksums and file
manifests before changing or deleting them. Earlier warnings from the failed
transaction are also useful: they can identify the exact missing cache file.

This establishes whether recovery needs a verified redownload, a package-manager
version correction, filesystem remediation, or a fresh toolkit installation.
