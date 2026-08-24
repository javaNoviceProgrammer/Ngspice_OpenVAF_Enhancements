# Enhancement-476 — the simulator reports only what it actually has

```
python3 verify_reportguard.py
```

31 checks, both linear solvers.

## The shape

Four defects from bug-hunt round 45. Each one is the simulator's account of
itself disagreeing with what it does, and none of them raised an error.

| | before | after |
|---|---|---|
| `@n1[op_id]` with no operating point | `0.0` — a plausible number | refused, naming the variable |
| `onoise_total_<dev>` for an OSDI device | listed by `display`, unreadable | reads back |
| `alter @n1[dtemp]=20` on a model-scope `dtemp` | accepted, discarded, silent | refused, naming `altermod` |
| `$simparam("temp")` | warned "this simulator does not provide" | silent; it has been served since E-434 |

## Why 0.0 was the dangerous answer

An operating-point variable lives in the instance block, which is `calloc`'d.
Before anything evaluates, every opvar reads a clean **0.0** — and 0.0 is a
perfectly ordinary current, voltage or conductance. Nothing distinguished it
from a computed result, so a script reading `@n1[op_id]` after a failed run got
a number rather than an error, while `i(v1)` in the same `print` correctly said
*"vector ... is not available"*.

ngspice already had the right rule elsewhere: `param_forall()` in
`src/frontend/device.c` will not even ask for an ask-only parameter unless
`ckt->CKTrhsOld` exists, which is why `show` never displayed a fabricated
opvar. The direct `@dev[opvar]` read was the one path without that guard.

**Parameters are deliberately not gated** — they are inputs, readable the moment
the deck is parsed, and every suite that reads one before running depends on it.

## The one-character defect

```c
NOISE_ADD_OUTVAR(ckt, data, "onoise_%s%s",       GENname, "");   /* N_DENS   */
NOISE_ADD_OUTVAR(ckt, data, "onoise_total_%s%s", GENname, " ");  /* INT_NOIZ */
```

The second suffix is a **space**, so the stored name was `onoise_total_n1␣`.
`display` pads the name column, so the blank was invisible; every read matched
the name literally and missed. Its own sibling eleven lines above was already
right, and every built-in passes a names array whose element 0 is `""` — which
is why `onoise_total_r9` worked and only OSDI's did not.

Check `[15]` does not test those two vectors. It reads whatever `display`
advertises and requires **all** of it to be printable, so the next name built
this way fails the suite on its own.

## Two lists that must be one

`$simparam("temp")` warned that the name is unserved and added a note saying an
unresolvable name is fatal at run time. Both claims were false: E-434 added
`temp` to ngspice's `sim_params[]`, and the call returns the ambient
temperature. The compiler's `SIMPARAM_NAMES` had not been updated, and the
warning's own copy of the list — a *third* place — had drifted with it.

The lists are now one `pub(crate) const` that the diagnostic is built from, and
checks `[24]`–`[27]` read **both** the Rust array and the C array out of the
sources and require them to be equal, then compile a model that reads every
name with no default and run it. A future divergence fails here rather than in
a user's build log.

## What must NOT be "fixed"

- **`@n1[dtemp]` still reads the model's own parameter** when the model declares
  one. That routing is Enhancement-397's design and the industry corpus (PSP,
  MEXTRAM, VBIC, HiSIM, BSIM all declare `dtemp`) depends on it. Only the
  instance-scope *write* is refused — `[19]` pins the read, `[20]`/`[21]` pin
  that an instance-scope `dtemp` still writes through.
- **`$simparam` matching is case-sensitive**; `$simparam("TNOM")` is fatal.
  `[29]` pins it. Round 45 briefly reported this as an inconsistency. It was
  not: macOS has a **case-insensitive filesystem**, so two probe models written
  to `sr_TNOM.osdi` and `sr_tnom.osdi` were literally the same file (same
  inode), and the second overwrote the first. Filenames that differ only in
  case cannot be used to hold different models on this platform.
- **An opvar stays readable after a later analysis fails**, once one has
  succeeded. Those values are a real evaluation, and a built-in keeps its last
  state the same way. `[9]` pins it.

## Noted and deliberately left alone

`@n1[mul]` reads **0.0** before any analysis, not its declared default of 1.0:
OSDI parameter defaults are applied during setup, and the instance block is
zeroed until then. This is the same family as the opvar defect, but it predates
this enhancement — the shipped binary behaves identically — and correcting it
means applying parameter defaults before setup, which is a different change with
its own evidence. `[7]` records the current behaviour so a future change to it
is a deliberate one; `[7b]` pins that the declared default does arrive.
