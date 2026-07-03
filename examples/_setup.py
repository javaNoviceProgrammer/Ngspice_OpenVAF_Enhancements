"""Locate the `openvaf-r` and `ngspice` binaries for the example scripts.

Python counterpart of the `*_examples/_setup.sh` shell helper: it resolves the
two toolchain binaries for the current machine using the committed, CI-built
`bin/<os>/<arch>/` matrix. As a convenience for local development it first
prefers a locally-built binary (`OpenVAF-master-20260610/target/release/…`,
`ngspice-46/build/src/…`) if one exists, and otherwise falls back to `bin/`.

Usage from an example script (which lives in `examples/<name>_examples/`):

    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds this file)
    from _setup import VAF as OPENVAF, NG as NGSPICE

Exposes module-level `VAF` (openvaf-r) and `NG` (ngspice) absolute paths.
"""
import os
import platform

# This file lives in `examples/`; the repo root (which holds
# `OpenVAF-master-20260610/`, `ngspice-46/`, and `bin/`) is one level up.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXE = ".exe" if platform.system() == "Windows" else ""


def _bin_subdir():
    """`<os>/<arch>` under bin/ for the current machine (matches _setup.sh)."""
    system = platform.system()
    machine = platform.machine().lower()
    is_arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return os.path.join("macos", "apple-silicon" if is_arm else "intel")
    if system == "Linux":
        return os.path.join("linux", "arm" if is_arm else "intel")
    if system == "Windows":
        return os.path.join("windows", "intel")
    raise RuntimeError(f"Unsupported platform: {system} / {machine}")


def _resolve(local_parts, name):
    """Prefer a local build if present, else the bin/<os>/<arch>/ prebuilt."""
    local = os.path.join(_ROOT, *local_parts) + _EXE
    if os.path.isfile(local):
        return local
    return os.path.join(_ROOT, "bin", _bin_subdir(), name + _EXE)


VAF = _resolve(("OpenVAF-master-20260610", "target", "release", "openvaf-r"), "openvaf-r")
NG = _resolve(("ngspice-46", "build", "src", "ngspice"), "ngspice")
