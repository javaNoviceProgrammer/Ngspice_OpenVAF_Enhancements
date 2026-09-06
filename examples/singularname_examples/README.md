# singularname_examples — Enhancement-570: "check node" names the vacuous equation

`verify_singularname.py` pins, under **both** linear solvers, that the
"singular matrix: check node X" report names the node whose matrix row is all
zero — the node nothing conducts to in this analysis — rather than the column at
which the factorization's own elimination order happened to run out of pivots.
For a rank-deficient block that column is any of the block's columns, so a BSIM4
whose gate hung on a Verilog-A capacitor was "check node g" under Sparse and
"check node d" under KLU.

`SMPgetError` now scans the loaded matrix for an all-zero row (else column) before
falling back to the factorization's pivot; the scan runs only after a singular
factorization, and a zero line survives elimination intact under both solvers.

Run it:

```
python3 verify_singularname.py
```

The suite compiles `va_cap.va` and `va_vcvs.va` itself and uses the benchmark
BSIM4. It covers the capacitor-coupled and open BSIM4 gate, the built-in MOS1
gate, a CMOS inverter chain with its input open, a capacitor-only node, a
Verilog-A probed port, the two no-zero-line fallbacks (parallel sources, an
inductor loop), and the AC path.
