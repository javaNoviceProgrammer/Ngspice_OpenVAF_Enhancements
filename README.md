# ngspice_openvaf
Using Claude Code AI to enhance the ngspice and openvaf frameworks.

## Enhancement-1: implement absdelay for Verilog-A/OSDI
June-2026: The implementation is based on extra internal nodes (extra signals). More precisely, implemented via the synthetic-node DAE approach in OpenVAF + ngspice.
- Verified for DC sim, AC sim, and Transition sim.
- Verified for both SPARSE and KLU solvers.
- binaries generated for: ngspice (release 46) and openvaf-r (release 20260610)
  
Benchmarks for DC, AC, Transient:
![Benchmark](./absdelay_examples/benchmark/results/benchmark.png)

## Builds

[![Build binaries](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml/badge.svg)](https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements/actions/workflows/build-binaries.yml)

CI builds `ngspice` and `openvaf-r` natively on each platform (no
cross-compilation; each build links its own LLVM 18) and commits the results
into `bin/`:

| Runner | Output |
|---|---|
| `ubuntu-latest` | `bin/linux/intel/` |
| `ubuntu-24.04-arm` | `bin/linux/arm/` |
| `macos-13` | `bin/macos/intel/` |
| `macos-14` | `bin/macos/apple-silicon/` |
| `windows-latest` | `bin/windows/intel/` (best-effort) |

Runs on push to `main` (source changes) or manually via the **Actions → Build
binaries → Run workflow** button. See `.github/workflows/build-binaries.yml`.

