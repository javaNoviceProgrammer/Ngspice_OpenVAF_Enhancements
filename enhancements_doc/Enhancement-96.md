# Enhancement-96 — module-level `generate for` without `generate`/`endgenerate` (version11)

A parser fix: a `generate for`/`if`/`case` written at module scope **without**
the optional `generate`/`endgenerate` keywords is now parsed and elaborated.
The LRM makes those keywords optional, and the nested form already supported
it — only the top module scope did not.

## The bug

```verilog
module m(bus);
   inout [0:3] bus; electrical [0:3] bus;
   ground gnd; electrical gnd;
   genvar i;
   for (i = 0; i < 4; i = i + 1) begin       // no `generate` wrapper
      gcell c (bus[i], gnd);
   end
endmodule
```

`module_items` handled a `generate … endgenerate` region but had **no arm for
a bare `for`/`if`/`case`**, so the loop fell through to error recovery. In two
module shapes the failure surfaced as `unexpected token 'for'`:

- a module with a **header bus port**, and
- a module with **no analog block**.

Worse, when an `analog` block followed the loop, error recovery could resync
on it and **silently drop** the entire generate-for (its instances vanished
from the flattened netlist), and some shapes even hit a compiler panic. The
`generate`-wrapped form (`generate for … endgenerate`) always worked, which
masked how common the bare form is (the LRM's own page-169 example uses it).

## The fix

`parser/src/grammar/items/module.rs` — `module_items` now has `FOR_KW`,
`IF_KW`, and `CASE_KW` arms that call `generate_for_tail`/`generate_if_tail`/
`generate_case_tail` with `top = false` (no `endgenerate` of their own),
producing the same `GENERATE_FOR`/`GENERATE_IF`/`GENERATE_CASE` nodes the
nested and `generate`-wrapped forms produce. The existing generate elaboration
(Enhancement-8/67) then unrolls them unchanged. One arm each; the
`generate`-wrapped form is untouched.

## Verification

`baregenerate_examples` (4/4, ngspice runtime pins): two modules using a bare
module-level generate-for —

- `busgen` (header **bus port**, **no analog block**): each bus bit is tied to
  ground through a conductance scaled by the bit index; the four branch
  currents come out distinct and index-scaled, proving the loop was **applied,
  not dropped**;
- `divgen` (**no analog block**): four parallel two-section dividers give
  `i(vp) = −2 mA` (it would be 0 if the loop had been dropped).

Full regression: 87 verify suites + 28 integration tests; parser/hir snapshot
tests and the Enhancement-8/67 `generate` suite unchanged. Three LRM examples
that used the bare form (p169_1/p169_2 `for`, p172_1 `if`) now parse and are
re-pinned from the old `unexpected token` / bit-select errors to their honest
generate-elaboration diagnostic (the loop bound / condition depends on a
parameter — the Enhancement-67 scope boundary).
