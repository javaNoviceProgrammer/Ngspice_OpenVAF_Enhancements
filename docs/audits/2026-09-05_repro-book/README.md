# Reproduction files — coverage audit of *A Practical Guide to Verilog-A* (2026-09-05)

Every construct-level check in
[`../2026-09-05_practical-guide-verilog-a-coverage.md`](../2026-09-05_practical-guide-verilog-a-coverage.md)
is one of the files here, compiled with the repository's `openvaf-r` (tree at
`aa520ebc`, the locally built `OpenVAF-master-20260610/target/opt/openvaf-r`).
Each file is one construct the book teaches, reduced to a model small enough
that a failure is attributable.

The models are original to this audit and are not the book's listings. The
exceptions are the examples the Accellera Verilog-AMS LRM itself gives, which
the book reprints and which this project already ships in
`examples/lrm_examples/`: value retention (`t21`), the relay and the
`$mfactor`-switched resistor (`t22`), the natures and disciplines (`t08`), the
sample-and-hold and period meter (`t29`), the `spicepnjlim` diode and the
`monitor` (`t30`), the two-file output example (`t31`), the RC line, `nlres`,
`genvarexp` and the `genblk` naming module (`t32*`), the Monte-Carlo
`semicoCMOS` paramset (`t04`), the equation-of-motion and ideal-opamp indirect
contributions (`t20`), and the `$table_model` isoline file format.

* `t*.va` — first round, one book topic per file (chapters 1 to 20).
* `u*.va` — second round, each failing topic split into its constituent constructs.
* `w*.va` — third round, the last ambiguities (generate names, paramset alias,
  override forms, child-net and child-port references, `macromodule`).
* `*.tbl` — the lookup-table and noise-table files the probes read.
* `ret.cir` — runs `t21_retention` in ngspice: the book's value-retention example
  must read 7.0 V.

## Running the set

```
./run_all.sh
./run_all.sh ../../../OpenVAF-master-20260610/target/opt/openvaf-r ../../../ngspice-46/build/src/ngspice
```

`run_all.sh` compiles every probe and prints its exit code and first
diagnostic; `run_all.out` is the listing the audit was written from. An exit
code of 0 is a compile, 65 a diagnostic, 101 a compiler crash. Some refusals
are the correct answer (the book's own mistakes, and documented deviations);
the audit says which.
