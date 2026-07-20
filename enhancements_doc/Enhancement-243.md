# Enhancement-243 — unify the `pre_snp` instance line: an explicit `ref` terminal for `-osdi`

Make the netlist instance line **identical** for both `pre_snp` backends by giving
the `-osdi` Verilog-A output the same explicit reference terminal the native
`nport` device (E-242) already has.

## The mismatch

E-242 added `pre_snp -native`, whose device carries an explicit reference terminal:

```
N1  p1 p2 ... pN  ref   mymodel      ; -native  (N+1 terminals)
```

The original `pre_snp -osdi` emitted a Verilog-A module with only the `N` signal
ports, referenced to global ground implicitly:

```
N1  p1 p2 ... pN  mymodel            ; -osdi    (N terminals)
```

So the two backends were *not* drop-in interchangeable — switching a deck between
`-osdi` and `-native` meant adding or removing the `ref` node.

## The change

`snp2va.c` now emits the reference terminal explicitly and takes every branch
relative to it:

```verilog
module m(p1, ..., pN, ref);
    inout p1, ..., pN, ref;
    electrical p1, ..., pN, ref;
    analog begin
        I(p1, ref) <+ ... V(p1, ref) ... V(p2, ref) ...
        ...
    end
endmodule
```

`ref` is a **plain electrical port**, not a `ground`-declared node — the same idiom
a two-terminal resistor uses for its `n` node. That keeps it *connectable*: tie it
to `0` for a ground-referenced Touchstone block, or to any node for a floating /
differential one. (Declaring `ground ref` would make it an internal 0 V node — no
longer a terminal — and would risk the E-116 failure mode where a `ground`-declared
node in no Jacobian entry produced an all-zero, structurally singular KLU row. As a
plain port, `ref` appears in every `I(pi,ref)` stamp, so it is well-posed.)

The instance line is now the same for both backends:

```
N1  p1 p2 ... pN  ref   mymodel
.model mymodel  <the -osdi module | nport(file="...")>
```

## Compatibility

This changes the `-osdi` module interface from `N` to `N+1` terminals, so an
existing `-osdi` deck must add the `ref` node (tie it to `0` to reproduce the old
ground-referenced behavior). The `-native` path and the `.nport` format are
unchanged. The `pre_snp -osdi` example decks (`examples/presnp_examples`) were
updated with the `ref` node.

## Verification

Running the **identical** instance line `N1 p1 p2 0 model` through both backends on
`137mhz_bpf.s2p` matches to **1e-11** across a 400-point AC sweep (ground-referenced
`ref = 0` reproduces the prior result exactly). `examples/presnp_examples` (9 checks:
the 2-/3-/4-/8-port pre_snp-`-osdi` cases, AC + transient + ordering) passes with the
`ref` terminal added; `examples/nport_native_examples` is unchanged.

## Scope

ngspice only — the Verilog-A emitter in `src/frontend/snp2va.c` (`snp2va_convert`);
`pre_snp -native`, the `.nport` device, the vector fit, and the `.osdi` compile path
are all unchanged. `pre_snp -osdi` decks now need the explicit `ref` terminal. Full
regression: 200/200.
