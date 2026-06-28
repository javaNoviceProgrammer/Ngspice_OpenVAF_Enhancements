# ngspice_openvaf
Using Claude Code AI to enhance the ngspice and openvaf frameworks.

## Enhancement: implement absdelay for Verilog-A/OSDI
June-2026: The implementation is based on extra internal nodes (extra signals). More precisely, implemented via the synthetic-node DAE approach in OpenVAF + ngspice.
- Verified for DC sim, AC sim, and Transition sim.
- Verified for both SPARSE and KLU solvers.
- binaries generated for: ngspice (release 46) and openvaf-r (release 20260610)
Benchmarks for DC, AC, Transient:
![Benchmark](./absdelay_examples/benchmark/results/benchmark.png)

