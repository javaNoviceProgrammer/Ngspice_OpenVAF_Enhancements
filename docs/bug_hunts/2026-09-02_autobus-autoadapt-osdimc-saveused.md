# Bug hunt — `autobus`, `autoadapt`, `osdimc`, `saveused`

**Date:** 2026-09-02 · **Commit under test:** `e90082de` · **Binaries:**
`ngspice-46/build/src/ngspice` and `OpenVAF-master-20260610/target/opt/openvaf-r`
as committed.

**Result: two confirmed bugs, both in `saveused`, both under-save.** The other
three features did not yield a finding — but see
[Coverage, honestly](#coverage-honestly) before reading that as a clean bill.
The three non-findings are not equally strong, and one of them is weak.

All seven suites for these features were green before the hunt and stayed green
throughout: `autobus`, `autobuskicad`, `autobusopt`, `autoadapt`, `adaptquiet`,
`osdimc`, `saveused` — both solvers. Neither bug below is caught by any of them.

---

## F1 — an implicit-all `write` is silently pruned

**Feature:** `saveused` ([E-469](../../enhancements_doc/Enhancement-469.md)) ·
**Class:** correctness, under-save · **Status:** confirmed, reproducible

`write file.raw` with no vector arguments means *write everything*. `saveused`
stands aside on an **explicit** `all` argument but does not recognise the
argument-less form as the same request, so the raw file is pruned to whatever
some other line happened to name.

The trigger is an interaction — the `write` alone is fine:

```spice
* F1
.option saveused
v1 in 0 dc 2
r1 in a2 1k
r2 a2 a3 1k
r3 a3 out 1k
r4 out 0 1k
.control
op
print v(out)          $ remove this line and the bug disappears
write f1.raw
quit
.endc
.end
```

Measured, same deck, same option, only the `print` line differing:

| control block | `No. Variables` in the raw |
|---|---|
| `write w_only.raw` alone | **5** — `in`, `v(a2)`, `v(a3)`, `v(out)`, `i(v1)`. Correct. |
| `print v(out)` + `write w_print.raw` | **2** — `out` and a spurious `v(all)` |

Adding a one-line sanity `print` silently strips four of the five vectors out of
a raw file written for offline post-processing.

**Cause.** In `dotcards.c`, `ft_saveused()` stands aside when
`saw_all || !any_out || !saves`:

- `write <file>` is an output command, so `any_out` is set — but
  `e469_scan_bare()` skips its first argument as the filename and finds no
  further tokens, so it contributes **zero** inferred vectors and never sets
  `saw_all` (which only fires on a literal `all` token);
- `print v(out)` makes `saves` non-empty.

So none of the three stand-aside conditions holds, and the run prunes to
`{out}`. With the `print` removed, `saves` is empty and the third condition
saves the deck by accident.

**Why the suite misses it.** `verify_saveused.py` check [4] covers
`wrdata _su_out.txt all` — the *explicit* `all`. The implicit form is never
exercised.

**Note, not part of the finding.** The spurious `v(all)` vector is a separate,
pre-existing `write`-on-a-restricted-plot artifact: it appears identically with
a hand-written `.save out` and no `saveused` at all.

---

## F2 — a bare node name in a `let` expression is under-saved

**Feature:** `saveused` ([E-469](../../enhancements_doc/Enhancement-469.md)) ·
**Class:** correctness, under-save · **Status:** confirmed, reproducible ·
**Severity:** lower than F1 — the bare-name idiom is less common than an
implicit-all `write`

ngspice stores a node voltage as a vector named after the node, so `a2` and
`v(a2)` reach the same data and both are legal in an expression. `saveused`
only recognises the second spelling.

```spice
.control
op
let y = a2 + a3       $ bare node names
print y
.endc
```

| deck | result |
|---|---|
| no `saveused` | `y = 2.500000e+00` |
| `saveused`, written `let y = v(a2) + v(a3)` | `y = 2.500000e+00` |
| `saveused`, written `let y = a2 + a3` | **fails** |

The failure:

```
Warning from checkvalid: vector a2 is not available or has zero length.
Error: RHS "a2 + a3" invalid
Error: no data saved for D.C. Operating point analysis; analysis not run
```

**Cause.** Two scanners, and a bare name in a `let` falls between them:

- `e469_scan_refs()` runs over **every** line but only recognises `v(...)`,
  `i(...)` and `@dev[param]`;
- `e469_scan_bare()` does collect plain node names, but runs **only** on output
  commands — and `let` is not one.

So the node is never registered and is pruned.

**Is it a bug or a documented limit?** The design comment scopes bare-name
collection deliberately: *"plus the plain node names given to the output
commands"*. On that reading this is in-scope-by-omission rather than an
oversight. It is recorded here anyway because the observable effect — a working
deck breaking — is precisely the outcome the same comment says the feature must
avoid: *"Under-saving turns a performance option into a correctness bug."*
Bare vectors are a real idiom, particularly for branch currents (`v1#branch`).

---

## What did not yield a finding

### osdimc — draw engine excellent, policy layer untested

Measured over **4000 trials** on `smcres.va` (`.option osdimc mcseed=7`), first
row discarded as the nominal baseline:

| parameter | declared | measured mean | measured σ | verdict |
|---|---|---|---|---|
| `r` | gauss σ=25, nominal 1000 | 999.69 | 24.985 | ✅ |
| `g` | uniform half-width 2e-4 | 9.9699e-4 | 1.1537e-4 (exact: 1.1547e-4) | ✅ |
| `k` | `std_rel` 0.05 × 2.0 → σ=0.1 | 1.9995 | 0.098223 | ✅ |
| `u` | gauss σ=5, nominal from **default** | 49.865 | 4.9393 | ✅ |
| `dr` | instance gauss σ=10 | 0.025 | 9.8812 | ✅ |

`g`'s observed range was `[8.00029e-4, 1.19995e-3]` against the exact interval
`[8e-4, 1.2e-3]`. Structural claims also hold: re-running seed 7 is
bit-identical, seed 42 differs, `(* type="instance" *)` parameters draw
independently per device, and independence survives subcircuit hierarchy
(`x1.n1[dr]` ≠ `x2.n1[dr]`, both varying per trial).

**This tests the draw engine only.** See the coverage section — the trial-policy
layer was not touched at all.

### autobus — main path holds

Token-count behaviour on `bustwo` (3 ports / 6 terminals):

| tokens | behaviour |
|---|---|
| 3 (= port count) | expands each port to its bits ✅ |
| 6 (= terminal count) | full form, no expansion ✅ |
| 4 or 5 (between) | **refused**, with an error that does the arithmetic: *"Model 'bustwo' has 6 terminals in 3 ports, and the line writes 4 node tokens…"* |
| 1 or 2 (< port count) | falls through to positional binding — the short-line `$port_connected` idiom |

The last row is a deliberate boundary, not a defect: `autobus` is opt-in
*because* a short line already means the `$port_connected` idiom, and
`inp2n.c`'s expansion only engages at `numnodes == np` or in the E-490 mixed
branch (`np < numnodes < terms`). Worth noting only that a below-port-count
line gets the generic unconnected-terminal warning rather than an
autobus-specific one, where the mixed case gets a precise message.

### autoadapt — the most genuinely exercised of the three

Every refusal was clean and specific:

- unequal widths → *"bus node 'b' is 4 bits on n1 but 2 bits on n2; not adapted."*
- adapter width mismatch → *"bus node 'b' is 2 bits but the adapter model 'amod' has 4-bit ports; not adapted."*
- self-loop, three-port, not-exactly-twice → all already covered by the suite and re-confirmed

Beyond the suite: a three-device chain `N1—b—N2—d—N3` adapts **both** shared
nodes with distinct adapter instances (`n_adapt1_`, `n_adapt2_`), and token
matching is exact rather than substring — a node `bb` alongside a shared `b`
does not perturb `b`'s occurrence count.

---

## Coverage, honestly

The three non-findings above are **not equally earned**, and the correlation in
this hunt is worth stating plainly: **bugs were found in exactly the one feature
whose implementation was read line-by-line first.** That is evidence about where
the search was deepest, not about where the bugs are.

What was **not** exercised:

| feature | untested surface |
|---|---|
| **osdimc** | The entire **trial-policy layer** — `osdimc_hold_depth` nesting, `OSDImcPreserveTrial`, `OSDImcInterruptReset`, `OSDImcTrialCheckpoint`/`Rewind`, `osdimc_scale_for`. That is [E-535](../../enhancements_doc/Enhancement-535.md)–[E-538](../../enhancements_doc/Enhancement-538.md), 34 checks in `mcpolicy_examples`, and the newest and most intricate half of the feature. The source was never read. |
| **autobus** | `e449_expand_bus_port` in `subckt.c:1376` — a **separate code path** for subcircuit port expansion, which `inp2n.c:183` explicitly flags as not covered by the path that was tested. Also `autobus=kicad` spelling, the `0`/ground token case, explicit `[0:2]` range tokens. |
| **autoadapt** | The node-list filter (`adapt_listed`), debug-vs-quiet reporting modes, and any interaction with `osdimc`. |
| **saveused** | Interaction with `osdimc` and with the loop commands; `meas` reference collection beyond a spot check. |

Accurate one-line summary:

> `saveused` has two confirmed under-save bugs; `autoadapt` survived a real
> adversarial pass; `autobus` survived a partial one (one of its two code
> paths); `osdimc`'s draw engine is excellent and its policy layer is untested.

The two gaps most likely to repay further work are **osdimc's trial-policy
layer** and **autobus's subcircuit path**.

---

## Related finding from the same session

Not part of this hunt, recorded for the trail: `%l`/`%L` (LRM 9.4.4, the
library.cell format specifier) expands to the literal placeholder `__.__` —
`hir_lower/src/fmt.rs` carries `// TODO support properly`, three lines below the
`%m` code that [E-539](../../enhancements_doc/Enhancement-539.md) had just
rewritten, and the compliance document omitted it from the supported list rather
than recording it as a gap. Measured: `m=[n1] l=[__.__] L=[__.__]`. Now recorded
in [the compliance tracker](../compliance/OpenVAF_Verilog-A_LRM_Compliance.md);
not implemented, because what a library.cell name should mean in a SPICE netlist
flow is a design decision rather than a fix.
