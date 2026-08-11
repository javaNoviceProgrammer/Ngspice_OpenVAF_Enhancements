# Enhancement-437 — a swept model wildcard is put back, and a `.temp` with no value

Two silent wrong answers, found by a bug hunt the day Enhancement-436 shipped.
Both are cases where the code that *should* have caught the problem already
existed and simply was not reached.

## 1. `sweep @*:rmod[res]` left every model it moved

```
sweep @*:rmod[res] 1k 3k 1k -analysis op -output v(a)

    Error: no such device or model name          <- spurious, sweep works anyway
    PPerror: syntax error in line segment
       @*:rmod[res]

    print @rmod[res]     ->  3000                <- and never put back
    print @x1:rmod[res]  ->  3000
```

Enhancement-436 gave `@*:rmod[param]` a **set** path. It never gave it the
**capture-and-replay** path that Enhancement-409 built for `@*[param]`, so the
sweep ran correctly and then walked away leaving all three matched models at the
last swept value. The next analysis in the session silently used a 3 k circuit.

That is precisely the defect E-409 exists to fix — *"a wildcard knob was never
put back"* — reappearing for a newer spelling of the same idea, because the new
spelling did not route into E-409's machinery.

### One omission, two symptoms

`sw_wildcard_knob()` in `com_sweep.c` is the gate. It recognises `@*[p]`,
`@#*[p]` and `@*[[p]]`, and it is consulted in exactly two places:

* `sw_read_knob()` — to *not* read a wildcard as a scalar. `*` is in the lexer's
  `specials` set, so `PPparse` cannot lex the name and emits a stray-`]` pair.
  E-409 added this guard for exactly that reason; the comment there quotes the
  same two lines that `@*:rmod[res]` printed.
* the nominal capture — to save per target, since a wildcard has no single
  readable value.

`@*:rmod[res]` matched neither, so it fell through to the scalar reader (the
spurious diagnostic) and had nothing captured (the missing restore). Teaching
that one function the new form fixes both.

### Filtered replay, not a broader one

The capture and replay must walk **exactly** the targets that
`if_setparam_wildcard_model_named()` walks, in the same order, or index *i* on
the way out names a different model than on the way in — and the decoy model
would be restored to a value that was never its own.

So the new `if_saveparam_wildcard_model_named()` and
`if_restoreparam_wildcard_model_named()` in `spiceif.c` reuse E-409's
`wild_ask_scalar` / `wild_set_scalar` and the same all-or-nothing rule (a
set-only parameter refuses the whole capture), differing from
`if_{save,restore}param_wildcard` only by the `eq(model_leaf(nm), leaf)` filter.
The verification pins this directly: an unrelated `omod` is moved to 7000 first,
and after a `sweep @*:rmod[res]` it must **still read 7000**.

## 2. A `.temp` card with no value ran the circuit at 0 °C

```
.temp                       <- value forgotten

Doing analysis at TEMP = 0.000000 and TNOM = 27.000000
```

`rc=0`, nothing on stderr but that routine line. A two-resistor divider with
`tc1=0.01` answers **0.5780 instead of 0.5000 — 15.6 % wrong, silently.** No
Verilog-A involved; this is plain ngspice, and every temperature-dependent
device in the deck is affected.

The cause is one missing case in `inp.c`: `strtod("")` returns `0.0` *and*
leaves the end pointer at the start of the string, so the trailing-garbage test
that correctly rejects `.temp abc` saw a clean parse and let 0 °C through.

### Why this is a lone gap and not a class

Its own sibling already refuses the identical mistake — `.options temp=` prints
`temp equals what?.` and keeps 27 °C — and so do `.temp abc`, `.temp -273.15`
and `.temp -300` (the last two via Enhancement-426's absolute-zero guard). The
missing-value case was the only silent one on the whole surface: **the
more-wrong input was the quieter one.**

Probing all fourteen value-taking dot cards settles the scope:

| | missing value | |
|---|---|---|
| `.tnom`, `.include`, `.lib` | abort, `rc=1` | |
| `.four`, `.print`, `.plot` | diagnosed | |
| `.ic`, `.nodeset`, `.width`, `.save`, `.options`, `.param`, `.global` | silent but **inert** — an empty card is a legitimate no-op | |
| **`.temp`** | **silent and changes the answer** | the only one |

So `.temp` is fixed alone. It now emits a message naming the actual mistake,
distinct from the existing bad-number message, and keeps the 27 °C default —
matching what `.options temp=` already did.

## Deliberately not changed

* **`.temp 1e9` is still accepted.** Enhancement-426 drew its line at absolute
  zero because that is *physically impossible*; an absurdly high temperature is
  merely *implausible*, and an arbitrary ceiling would be a policy invention
  with no evidence of harm behind it. Garbage in, garbage out is the correct
  behaviour here.
* **`@(initial_step)` fires once per `sens` re-solve** (11 times for the probe
  deck, once in every other analysis). `sens` genuinely re-solves the operating
  point per perturbed parameter, and each re-solve *is* an initial step;
  suppressing that would misreport what the analysis does.
* **`tran ... uic` still omits the `t=0` row.** Long-standing general ngspice
  behaviour, reproducible with no Verilog-A anywhere, and emitting the row would
  change the row count of every `uic` transient — a wide behavioural change on
  thin evidence.

One further hunt finding was **withdrawn**: a malformed `optimize` command looked
undiagnosed, but it does report `optimize: param 'r1' needs hi > lo` and leaves
the knob untouched. The `Error: incomplete or empty netlist` seen alongside it is
batch mode's generic *nothing-ran* note, and stdout/stderr ordering had hidden
the real message.

## Where it lives

* `com_sweep.c` — `sw_wildcard_knob()` learns `@*:name[param]` / `@*.name[param]`
  and reports the leaf name; the capture and the replay call the named variants
  when a leaf is present.
* `spiceif.c` — `if_saveparam_wildcard_model_named()`,
  `if_restoreparam_wildcard_model_named()` and the static
  `if_hasparam_wildcard_model_named()` that sizes the capture.
* `inp.c` — the `.temp` card's missing-value case.

## Verification

* **`examples/modelwild_examples` — 21/21**, up from 16. Both spellings are
  checked for restoration *and* for the absence of the spurious diagnostic; the
  three spellings that already restored (`@*[res]`, `@x1:rmod[res]`,
  `@rmod[res]`) are re-checked as no-regression controls; the swept curve is
  pinned to `0.5, 0.3333, 0.25` so the fix cannot be hiding an answer change;
  and the leaf-filter alignment is checked with the moved decoy described above.
* **`examples/sweepguard_examples` — 43/43**, up from 35. The `.temp` checks
  include a **positive control** — `.temp 125` must still set 125 °C and move
  the answer — because a fix that simply ignored the card would satisfy every
  negative check.
* Both suites were run against the **unfixed** binary as negative controls:
  exactly the defect-specific checks fail (5 in `modelwild`, 3 in `sweepguard`)
  while every control check passes either way.
* **Full regression 347/347**, both solvers — including `wildrestore`, E-409's
  own suite, which is what a change to the wildcard restore path would disturb.

## Found by

Round 36 of the ngspice + OSDI bug hunt, run against the binary shipped that
same day. Two of its three findings were in Enhancement-436's brand-new code —
a reminder that a freshly added name form is worth hunting immediately, and that
"the guard already exists" is not the same as "the guard is reached".
