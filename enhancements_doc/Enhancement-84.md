# Enhancement-84 — the LRM example sweep and its six defect fixes (version11)

This document describes Enhancement-84: every code example in the
Verilog-AMS LRM 2023 PDF extracted, classified, and compiled against
openvaf-r (`lrm_examples/`), and the six compiler defects that sweep
exposed, fixed. The suite is both the test that found the bugs and the
regression net that pins the fixes.

## Part 1 — the sweep (`lrm_examples/`)

The 442-page standard's examples are identified by *font* (LRM code is
typeset in Courier New), not text heuristics, so the extraction is
exhaustive: 231 candidate blocks. `extract_lrm_examples.py` also
normalizes the PDF's typography (en-dashes for minus signs, curly
quotes — the page-114 diode example contains a literal en-dash inside
`limexp(...) − 1`), merges same-baseline column fragments, and joins
blocks across page breaks by construct balance.

`curate_suite.py` holds an explicit per-block disposition table (each
manual entry carries a content fingerprint so a re-extraction that
renumbers blocks fails loudly) and produces:

| Directory | Count | Verified by `verify_lrm.py` as |
|---|---|---|
| `va/` | 37 | compile cleanly |
| `limitations/` | 22 | rejected with the exact pinned diagnostic, no crash |
| `ams/` | 21 | mixed-signal language — out of Verilog-A scope, stored not compiled |
| `findings/` | 6 | micro-repros: fixed defects must compile, open gaps keep their pin |
| `fragments/` | 146 | reference; double as a no-crash fuzz corpus |

Examples stay verbatim wherever possible; unavoidable adaptations are
annotated in-line (`[lrm_examples patch]` one-liners, `[lrm_examples
context]` stubs for modules the LRM references but never defines, such
as `vertNPN` or the Annex E oscillator primitives). Files whose examples
omit port directions — the LRM does this on at least five pages —
compile under `-W port_without_direction` rather than being edited.

Two errata in the standard itself: page 265's `twoclk` declares
`vout_q1b` where the port is named `vout_q2` (a typo), and the
port-direction omissions above.

## Part 2 — the defects (six fixed, two documented)

**F1 — named port branches crashed the compiler.** `branch (<p>)
probe_p;` is plain Verilog-A (LRM 3.7.2), used by the page-62
current-probe example; probing `I(probe_p)` panicked in
`BranchWrite::nodes` (`unreachable!` on `BranchKind::PortFlow`). Fix:
`hir_lower/src/expr.rs` routes a flow probe of a PortFlow-kind named
branch through the same `CurrentKind::Port` param as a direct `I(<p>)`,
so E-29's `build_port_flow_equations` gives it its defining equation.
Runtime-verified in ngspice: the probe reads +5 mA where the source
branch reads −5 mA. Contributing to a port branch (illegal per LRM) now
gets a real diagnostic (`ContributeToPortFlow` in `hir_ty`), with the
declaration site labeled, instead of the same panic.

**F2 — garbage input crashed the parser.** Non-Verilog text (the LRM's
attribute-section pseudo-code, its Annex B keyword table) tripped
`bump_ts` assertions in `port_decl`/`func_arg` (module-head port parsing
reaches `port_decl` for anything that is not a plain name). Fix:
`expect_ts_r` — a diagnostic plus one token of forced progress — at both
sites (`parser/src/grammar/items/module.rs`). All 146 extracted LRM
fragments now compile-attempt without a single panic or hang.
*A first attempt gated elaboration on a clean parse instead — wrong:
generate-for unrolling legitimately operates on parse trees that carry
recoverable errors (that is how E-8/E-67 textual elaboration works), and
the gate broke ten valid suite files. Reverted.*

**F3 — instantiating an undefined module compiled silently.** The E-5
flattener's `expand_instantiation` returned empty text for an unknown
target: a typo'd module name became an invisible open circuit. Fix: a
collected hard error (same channel as E-41's conflict errors) naming the
instance and module. Two tailored variants: when the "module" is a known
discipline, the input was really a name-then-range net declaration
(`electrical out[0:2];` parses as an instantiation!) and the message
says exactly that with the supported spelling; when it names a paramset
whose own target failed to resolve (page 158 targets SPICE's `nmos3`),
the message says the paramset was dropped, not that the name is
undefined. Valid paramset instantiation from VA source (twin module,
E-21) is unaffected — probed explicitly.

**F5 — `$port_connected` failed on unconnected ports of flattened
instances.** Flattening renamed an open port to a synthesized local net
(`clk1__open__vout_qbar`), which then failed hir_ty's port-reference
check — the builtin broke in exactly the case it exists to detect (the
page-265 clock example). Fix: connectivity is decided where it is known
— `render_instance_content` rewrites `$port_connected(<rendered-arg>)`
to a literal `(1)`/`(0)` per instance (`resolve_port_connected`, keyed
by the already-renamed argument). Top-level modules keep the native OSDI
connected-flag path. Nested flattening composes level-by-level.

**F7 — dead analog operators aborted codegen** (found *through* F5: its
`(0)` literals create constant-false branches). A `transition()` inside
`if ((0))` survived const-folding as a detached-but-interned op whose
state setup read optimized-away values: first a `split_tainted` panic on
a layout-detached branch, then, one layer deeper, an "attempted to read
undefined value" abort in LLVM codegen. Two fixes: literal `if`
conditions lower only the taken branch (`hir_lower/src/stmt.rs` — the
dead arm never reaches MIR at all), and `split_tainted` tolerates
detached branch instructions (`mir_opt/src/split_tainted.rs`).

**F8 — openvaf-r exited 0 on hard errors.** The driver's `Err` arm
printed the error chain and fell through to a success exit — every
elaboration failure looked like a successful compile to shell scripts
(the quirk first noticed during E-58). Fix: `exit(DATA_ERROR)`
(`openvaf-driver/src/main.rs`). Combined with F3, this unmasked
thirteen suite files whose original probe "compiles" were silent drops
or error exits — all reclassified with honest pins.

**F4 (open)** — `` `__FILE__``/`` `__LINE__`` predefined macros are not
implemented. **F6 (open)** — part-selects in instance connections
(`adc2 hi (out[3:2], in);`) don't parse. Both pinned in `findings/`.

## Verification

- `lrm_examples/verify_lrm.py`: 7/7 — 37 compiles, 22 limitation pins,
  6 finding pins, manifest/tree consistency.
- F1 runtime check in ngspice (named-port-branch probe vs. source
  branch current, sign-exact).
- Full regression: all version11 verify suites + the 28 openvaf
  integration tests.

## Gotchas recorded

- Elaboration-time textual passes MUST tolerate parse errors (see F2's
  reverted first attempt) — rowan error nodes preserve text, and the
  generate/instantiation renderers rely on that.
- The suite's original probe classified 13 files as "compiling" that
  never did: 7 exited 0 through the F8 hole (generate bails, implicit-
  net conflicts), 6 silently dropped unknown instances through the F3
  hole. A green exit from a tool with F8-class bugs is not evidence.
- `$port_connected` had to be resolved *during* flattening; both
  "fix the validation" and "keep the port" approaches founder on the
  fact that after inlining there is no port left to ask about.
