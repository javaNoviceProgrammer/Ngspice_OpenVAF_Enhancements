# Enhancement-390 — eight defects from a one-hour bug hunt

A timed hunt against `openvaf-r` at [E-389](Enhancement-389.md) produced nine
findings. Eight were real and are fixed here; the ninth was my own test error and
is recorded at the end so it isn't chased again.

Three of the eight were in E-389's own new code, which is the argument for
hunting your most recent work first.

## 1. A `case` inside a `do-while` compiled into an infinite loop

The headline, and pre-existing.

```verilog
do begin
    case (k) 0: x = x + 1.0; default: x = x + 2.0; endcase
    k = k + 1;
end while (k < 3);
```

**Two symptoms, decided by what encloses it.** On its own, this compiled cleanly
and the resulting `.osdi` **hung ngspice forever** at the operating point with no
diagnostic. Nested in a `for`, `while` or `repeat`, it **crashed the compiler** at
`mir_opt/dead_code_aggressive.rs:112` — an `unwrap()` on `None`, the same site
[E-324](Enhancement-324.md) hit.

**The mechanism.** `lower_case` opened each arm with `ensured_sealed()`, which
seals *the current block*. On the first arm that block still belongs to the
**caller** — and when a `case` is the first statement of a `do-while` body, the
caller's block is the loop's body head, which must stay unsealed until the back
edge is added. Sealing it early completed its phis against the entry edge alone,
so a variable updated inside the loop read back as its pre-loop value. `while (k
< 3)` folded to a constant true, and the optimised MIR came out as

```
block2:
    jmp block2
```

a literal unconditional self-loop, with the contribution block unreachable. That
also explains every boundary observed while isolating it: wrapping the `case` in
an `if` avoids the bug (the `if` opens a block first, so the blanket seal lands on
*that*), one-pass `do{…}while(0)` is fine (no back edge is needed), and a `case`
inside a *function* called from a do-while fails identically (it inlines into the
body head).

Both `ensured_sealed()` calls are removed. Every block `lower_case` creates is
sealed explicitly — `body_head`, `next_block` per
[E-291](Enhancement-291.md), and `end` — so the blanket call was never
load-bearing.

**This is the [E-375](Enhancement-375.md) pattern a third time.** The 2026-07-26
binary *crashed* on this construct; [E-363](Enhancement-363.md) fixed the panic,
and what it emitted afterwards looped forever. A compile crash is loud; a
simulator that never returns just looks slow.

## 2. An ANSI function argument with a type but no direction returned 0

`f(real x)` compiled, accepted one argument, and discarded it. The argument was
neither input nor output, so nothing was copied in and the body read 0 —
`f(3.0)` returned **0 instead of 6**, silently. Verilog defaults a function
argument to `input`, and it now does here. The separated and combined forms both
reject a direction-less argument outright; only E-389's ANSI path could produce
one.

## 3. `analog` blocks inside `generate` were silently discarded

```verilog
generate for (i = 0; i < 3; i = i + 1) begin : b
    analog I(p,n) <+ 1e-3;
end endgenerate
```

contributed **nothing**, with zero diagnostics — as did `generate if`. The
generate-block grammar had no case for `analog`, so it fell into the catch-all
and raised a parse error — which was then *swallowed*, because elaboration
re-renders the generate region from its syntax tree ([E-67](Enhancement-67.md));
the malformed node rendered to nothing.

`analog` blocks are module items, so the grammar now accepts them. Two comments
in the tree asserted the opposite — *"LRM: no `analog` blocks may appear inside"*,
from [E-8](Enhancement-8.md) — and that reading is wrong. The 2023 LRM's own
grammar has

```
module_or_generate_item ::= … | { attribute_instance } analog_construct
```

so an analog block is exactly as legal inside a generate as an instantiation is.
Both comments are corrected. Generate has always worked for instantiation (three
children give exactly 3×), so only analog blocks vanished. A syntax error inside
one is now reported too.

## 4. `disable` with an unresolvable name was a silent no-op

A typo'd label, a variable name, even the module name: lowering resolved the name
against the enclosing named blocks and, on a miss, *"degraded to a no-op"* by
design. The statement did nothing and execution carried on — so a loop meant to
exit early ran to completion. A spelling mistake changed the answer.

Resolution is now checked during validation, where diagnostics exist, against the
same enclosing-block stack lowering uses.

## 5–7. `$table_model` — three ways the two data forms disagreed

The compile-time forms **sort** and **de-duplicate** their breakpoints; the
runtime array form ([E-389](Enhancement-389.md)) did neither. Identical data gave
different answers — descending data returned 0.5 / 2.5 / 5.5 from a literal and
−0.5 / 1.5 / 2.5 from arrays. A duplicated or never-assigned abscissa produced a
zero-width segment whose slope divided by zero, and the NaN surfaced only as
`Timestep too small; cause unrecorded`. And the cubic control code `"3"` was
ignored on the runtime path, which always interpolated linearly: `"3L"` gave
0.35 from a literal and 0.5 from arrays.

All three are fixed **in kind rather than diagnosed**:

- the runtime table is sorted and de-duplicated by an unrolled compare-and-swap
  network (quadratic, so capped at 64 knots — beyond that the LRM's ascending
  requirement governs, exactly as before);
- every division is guarded, so a degenerate grid yields a finite result;
- the natural cubic spline is solved in MIR by an **unrolled Thomas algorithm**.
  The knot *count* is known at compile time even when the knots are not, so the
  elimination and back-substitution are straight-line code over runtime values.
  Its extrapolation mirrors the compile-time spline exactly — continuing the end
  *tangent*, not extending the cubic. That distinction is invisible inside the
  grid and shows up only outside it.

## 8. An unusable data file was a silent zero

A mistyped filename, an unreadable file, an empty one, or a single column of
numbers: the reader returned an empty table and the device contributed zero, with
nothing reported. The file is read during lowering, which has no diagnostic
channel, so the check runs when the report is built — the first point with both
the root file (to resolve a relative path) and the VFS in hand. A readable file
that fits either documented shape reports nothing.

This immediately caught a real instance: `examples/lrm_examples/va/lrm_p274_1.va`
references `sample.dat`, **a file that was never in the repository**. It had been
"compiling" only because of the defect being fixed here. The data file it always
needed is now supplied.

## Verification

`examples/vafcaseloop_examples` — **45/45**, of which 15 are the accept half.
Those matter more than the reproducers: change 1 alters block sealing, which
every model containing a `case` goes through, and change 3 adds a keyword to a
grammar. Both are the kind of change that breaks *working* models.

**Output-preserving on the whole corpus: 124/124 `.osdi` byte-identical** by
sha256, compiled to the same output path. Since the emitted objects are identical
to the previous compiler's, runtime correctness is unchanged by construction.

Regression 313/313 → **314/314**.

## Not a defect — recorded so it isn't chased again

A ninth finding, "paramset cannot override any parameter", was **my own test
error**. A `paramset` overrides a target parameter with `.g = <expr>;`; I had
written `parameter real g = 5e-3;`, which *redeclares* the target's parameter and
is correctly rejected. With the right syntax it works exactly as documented —
`.g = 5e-3;` on a 1 mS target gives 5 mS, and a paramset-local parameter feeding
an override expression works too.
