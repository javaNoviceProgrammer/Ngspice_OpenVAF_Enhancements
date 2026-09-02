# Enhancement-540: a scan in the analog body segfaulted the simulator

**Scope:** `$sscanf`/`$fscanf` lower to a three-call sequence whose dependency
lives in runtime globals rather than in the IR. The init/eval splitter could
therefore hoist half of it, leaving a field scanner running with an
uninitialised cursor — a **NULL dereference that killed ngspice** on legal
Verilog-A. One predicate keeps the sequence together.

**Suites:** [`examples/scanbody_examples/`](../examples/scanbody_examples/) is
new (**5 checks**, both solvers). Against the pre-fix compiler it scores
**1/5**, catching the crash as `exit=-11`. Full sweep **452/452 ALL OK**.
**openvaf-r change only** — no ngspice change.

## The crash

A file descriptor opened in `@(initial_step)` and scanned in the analog body:

```verilog
analog begin
  @(initial_step) fd = $fopen("data.txt", "r");
  n = $fscanf(fd, "%g", g);
  I(a,b) <+ V(a,b) * g * 1e-3;
end
```

```
EXC_BAD_ACCESS (code=1, address=0x0)
frame #0: scanbody.osdi`osdi_scan_real + 40      ; ldrb w8, [x19]
```

Found by a bug hunt over ngspice + OSDI
([`docs/bug_hunts/`](../docs/bug_hunts/2026-09-02_ngspice-osdi-general.md)),
which bounded it before diagnosing it: every neighbouring construct is fine —
`$fgetc`, `$ungetc`, `$ftell`, `$feof`, `$ferror`, `$rewind`, `$fseek` and
`$fgets` all run clean in the analog body with the same descriptor, `$sscanf`
on a literal is fine, and the whole thing works when the descriptor never
crosses out of the body. Two facts from that table pointed straight at the
cause: the **manual** equivalent (`$fgets` into a string, then `$sscanf` on it)
crashes identically — so it is not `$fscanf`'s fused lowering — and the
`@(initial_step)` **crossing** is what makes the difference.

## The root cause: an invariant the IR does not express

`$sscanf`/`$fscanf` lower to **`ScanBegin` → `Scan*` → `ScanCount`**. That
sequence is a protocol: `ScanBegin` sets the runtime's cursor over the input
string, each `Scan*` consumes a field from it, `ScanCount` reports the tally.
The three communicate **through globals in `stdlib.c`**, not through MIR
values, so nothing in the dataflow says they belong together.

`sim_back`'s init/eval splitter copies every instruction that is **not**
operating-point dependent into the instance-setup function, so a model pays for
parameter-only work once instead of per evaluation. `Scan*` takes a single
fallback constant and `ScanCount` takes nothing, so both looked freely
hoistable — while `ScanBegin` was pinned in eval by the descriptor it depends
on. Setup then ran a field scanner with `osdi_scan_cursor` never initialised.

The MIR shows it plainly. Before the fix, the instance-setup function is:

```
Optimized instance setup MIR of manual
function %_init(v22) {
    inst0 = fn %scan_Real(1) -> 1
    inst1 = fn %scanf_count(0) -> 1
    ...
@000d   v16 = call inst0(v3)      <- a field scanner
@0015   v17 = call inst1()        <- and the tally
```

— a scanner and a count with **no `scanf_begin` anywhere in the function**. The
give-away across the whole dump was the asymmetry: two `scan_*`, two
`scanf_count`, but only **one** `scanf_begin`.

## The fix

`CallBackKind::op_dependent()` is the predicate that pins an instruction into
the eval function, and there was already precedent for using it this way —
noise callbacks are force-marked so they cannot drift out of eval. The three
scan callbacks join them:

```rust
| CallBackKind::ScanBegin
| CallBackKind::Scan(_)
| CallBackKind::ScanCount
```

They are not operating-point dependent in any physical sense; they are listed
there because that predicate is the mechanism which keeps them together, and
together is the only place the sequence is defined. After the fix the dump has
exactly one of each, in eval.

The predicate's other consumer was checked first: `osdi/src/metadata.rs` reads
`ParamKind::op_dependent`, a different type, so the change cannot reach it.

## Verified as correct, not merely non-crashing

A build that hoisted the scanner and silently used the **fallback** value would
also stop crashing, so the answer is what the checks assert. The fixture reads
`2.0` from its data file, making the device a 500 Ω conductance against the
deck's 1 kΩ series resistor:

```
v(mid) = 0.333333333    ( = 500/1500 exactly )
```

Both spellings — `$fscanf`, and the manual `$fgets` + `$sscanf` — agree to the
last digit.

## The cost, stated plainly

Pinning the scans into eval also pins any `$fdisplay` whose arguments depend on
them, and instance-setup's deferred writes flush before eval's. A model that
**mixes scans with other output in one block** therefore sees its lines
interleaved differently. `stringio_examples`' committed output records exactly
that: the six prints are written in source order, and `sscanf=` and `fscanf=`
now appear last instead of third and fifth. **Every value is byte-identical** —
only position moved — and the suite passes either way because it parses by key.

This is not a new class of behaviour: any print whose arguments are
eval-dependent already lands in eval, so mixed blocks already reorder. What
changed is that scans now fall on that side of the line. It is a real loss of
source-order fidelity all the same, and the golden file is updated rather than
quietly regenerated.

**The better fix, not taken here.** The honest repair is to stop hiding the
dependency: give `ScanBegin` a return token that each `Scan*`/`ScanCount` takes
as an argument, so the dataflow ties them and the splitter hoists all-or-none
on its own. That would fix the crash *and* keep the sequence hoistable when it
can hoist entirely, restoring source order in the mixed case. It costs a
signature change, threading the token through `lower_scanf`, and an extra
parameter in the OSDI binding and the runtime — a change to a working path,
weighed against a crash that is already fixed. Recorded as the next step rather
than pretended away.
