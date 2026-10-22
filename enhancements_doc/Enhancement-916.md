# Enhancement-916: a subcircuit's multiplier reaches a compiled model that owns `m` — a compiled diode, whose grading coefficient is `m`, could not sit in a multiplied subcircuit at all, and a module with an instance parameter `m` had it overwritten and was not multiplied, in silence

**Scope:** F7 and F8 of the
[options-and-convergence hunt of 2026-09-26](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).

ngspice:
- `frontend/inpcom.c` (`inp_fix_subckt_multiplier`: an N line gets the subcircuit's multiplier as
  `_subckt_m=`);
- `spicelib/parser/inpdpar.c` (`INPdevParse` multiplies it into the device's own multiplier).

**ngspice only.**

**Suites:**
- [`subcktmfactor_examples`](../examples/subcktmfactor_examples/) (new): 12 checks per solver, 7 of
  which fail on E-913.
- `osdiplumb` (E-394's multiplier checks): unchanged, 45 of 45.
- `instknobs` [3]: re-pinned, and its rule reversed. E-396 pinned "a model that declares `m`
  owns it": `X1 … m=3` set the model's own `m`, `$mfactor` stayed 1, and a model that declares
  `m` without multiplying by it ran 1×, called the model's bug. F8 is that model. The subcircuit's
  multiplier is now `$mfactor`'s. A model that multiplies by its own `m` still scales once (its
  `m` keeps 1, `$mfactor` is 3), and the other kind scales 3×. 126 of 126.
- The full sweep: 605 of 605.

## What was wrong

A subcircuit called with `m=` has ` m={m}` appended to every device line inside it (E-394 let it
reach N lines). On an N line that `m` lands on whatever the compiled device calls `m`.

**F7: a model that owns `m` is refused.** Every SPICE-derived Verilog-A diode calls its grading
coefficient `m`, a model parameter:

```
.subckt dsub p n
nd1 p n dva
.model dva vadiode(is_=1e-14 n=1.2)
.ends
X1 a 0 dsub m=2
```

```
n.x1.nd1 a 0 x1:dva m=    2.0000000000000000e+00
unknown parameter (m): it is a model parameter of this device -- set it on the .model card, not on the instance line; ...
```

The error was on a line the user wrote no parameter on. `_mfactor=3`, the only spelling such a
device has for its multiplier, was refused on the inner line as a second spelling of the
appended `m`. The built-in diode in the same subcircuit multiplies.

**F8: a module with an instance parameter `m` is not multiplied.**

```
module mmode(p, n);
    (* type="instance" *) parameter integer m = 1 from [1:8];
    analog I(p, n) <+ V(p, n) / 1k + m * 1u;
endmodule
```

Inside `X1 a 0 msub m=2` at 0.5 V it drew 0.502 mA: one device with its own `m` set to 2, where two
devices draw 1.002 mA. ngspice printed nothing; only the compiler's L029 warns the model's author.

## What changed

The two cases differ only in what the model calls `m`, and only the parser, once it knows the
device, can tell. So the expansion no longer decides.

**The expansion** appends the multiplier to an N line under a keyword of its own:

```
n.x1.nd1 a 0 x1:dva _subckt_m=2.0000000000000000e+00
```

**The parser** (`INPdevParse`) recognizes `_subckt_m`. It holds the multiplier the instance
line or the card gives, and after the line writes the product once, through the device's own
multiplier: `_mfactor` on a compiled device, `m` otherwise. An `m=` written on the inner line
stays what the model says it is:
- the multiplier's alias on a resistor module, so `m=3` inside `m=2` is 6×, as before;
- the module's own parameter on `mmode`, so it stays 3 and the device is doubled.

The m=0 note (E-751), the negative-m warning (E-755) and the n-port's "not applied" line see the
one value that is applied, once. Built-in device lines, X lines and the HSPICE path are
unchanged.

| inner line in `X1 … m=2` | E-913 | E-916 |
|---|---|---|
| `nd1 p n dva` (diode owning `m`) | refused | 0.724604 V, the built-in's 0.724603 V |
| `nd1 p n dva _mfactor=3` | refused | six diodes, as the built-in's `m=3` |
| `nx1 p n mm` (module's own `m`) | 0.502 mA | 1.002 mA |
| `nx1 p n mm m=3` | 0.506 mA, its m = 6 | 1.006 mA, its m = 3 |
| `n1 p n rr m=3` (resistor) | 6× | 6× |

## The checks

`subcktmfactor_examples` (new), under both solvers:

| check | what | E-913 |
|---|---|---|
| [1] | a compiled diode owning `m` in m=2 runs, gives the built-in diode's point, and is multiplied | refused |
| [2] | … with `_mfactor=3` on its line: six diodes | refused |
| [3] | a module with its own instance parameter `m`, in m=2: 1.002 mA | 0.502 mA |
| [4] | … with `m=3` on its line: the parameter stays 3, 1.006 mA | its m is 6 |
| [5] | a resistor module with m=3 inside m=2: 6× | passes |
| [6] | nested subcircuits 2 × 3 × 5: 30× | passes |
| [7] | a card's `_mfactor=3` default inside m=2: 6×, 3× at the top level | 2×: the card's 3 is lost |
| [8] | m=0: one note; m=-1: one warning, the multiplier kept | passes |
| [9] | a built-in resistor in m=2, and a subcircuit that declares `m` itself | passes |
| [10] | the small-signal current of the module owning `m` in m=2: 2 mS | 1 mS |

## Limits

- **The keyword** `_subckt_m` appears in `listing` and in messages that quote the expanded line.
  It is the expansion's own and means nothing on a line written by hand at the top level, where
  it multiplies like any other multiplier.
- **The native n-port** still implements no multiplier and says so, as before.
