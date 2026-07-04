# implicitnet_examples — implicit nets in instance connections (Enhancement-41)

Demonstrates **implicit nets** — undeclared interconnect identifiers in
module-instance port connections — using **the committed** `openvaf-r` and
`ngspice-46`.

## What was broken

Every internal wiring node between instances had to be declared manually:

```verilog
res2 r1(in, mid);    // error: 'mid' was not found in the current scope
res2 r2(mid, out);
```

Per the LRM's structural-connection semantics `mid` is an **implicit scalar
net**. The Verilog-A appendix excludes the `` `default_discipline`` directive,
so Enhancement-41 derives the implicit net's discipline **from the connected
port** (what discipline resolution yields for compatible ports), keeps the
directive ignored, errors on conflicting-discipline connections, and leaves
undeclared identifiers in `V()`/`I()` access as errors (implicit declaration is
structural-only).

Implemented in the Enhancement-5 elaboration pass: the implicit net is a local
of the module its instantiation appears in, so nested implicit nets are
alpha-renamed per instance — two flattened instances of the same submodule never
accidentally share one net.

## Run

```
python3 verify_implicitnet.py
```

Checks (ALL PASS): compiles (used to error); DC resistance exactly 4 kΩ through
an implicit `mid` joining two submodules that each carry their **own** implicit
internal `w` (a cross-instance short would read 2 kΩ); positional and named
forms; conflicting disciplines rejected with a clear message; `V(ghost, c)`
still a clean scope error.
