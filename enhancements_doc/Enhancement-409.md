# Enhancement-409 — the sweep knob that could not be read, so nothing was put back

```
sweep @*[wavelength_nm] 1300 1600 10 -analysis ac -output ...
```

runs correctly, prints every point, and then says:

```
Error: no such device or model name
PPerror: syntax error in line segment
   @*[wavelength_nm]
near
      wavelength_nm]
```

The name looks mangled, which is what makes the message alarming — but nothing is
wrong with the parameter. The expression lexer's `specials` set contains `*`, so
`@*[p]` can never lex as a single token: the parser stops at the `*` and reports
the text left over, trailing `]` and all.

**The message was the harmless part.** It was the visible end of a state
restoration failure.

## What was actually broken

Enhancement-385 gave `sweep` the courtesy of putting an `alter`/`altermod` knob
back when it finishes, so a following analysis does not silently run against the
last swept point. It reads the nominal through `sw_read_knob()`, which parses the
knob name as an expression — the call that cannot succeed for a wildcard. The
read reported failure, and E-385's deliberate **all-or-nothing** rule then
skipped restoring *everything*:

| sweep | after it finishes |
| --- | --- |
| `@dev1[wavelength]` (concrete) | 2.0 → 2.0 |
| `@*[wavelength]` (model wildcard) | 2.0 → **3.0**, 9.0 → **3.0** |
| `@#*[scale]` (instance wildcard) | 1.0 → **3.0** |
| `@*[[scale]]` (E-269 alias) | 1.0 → **3.0** |

and with a second knob it spread to knobs that were never the problem:

| sweep | result |
| --- | --- |
| `@dev1[…] -vs @dev2[…]` | both restored |
| `@dev1[…] -vs @#*[scale]` | **`@dev1` also left at 3.0** — a knob that restores perfectly alone |

So one wildcard silently left the whole circuit at its last swept point.

## Why one number could not fix it

A wildcard sets **every** matching model (or instance) to one value, but the
values it overwrites can all differ — two `.model` cards of the same type
routinely carry different numbers. The example here starts `dev1` at
`wavelength=2` and `dev2` at `wavelength=9` precisely so that a single-nominal
"restore" cannot pass: undoing the change needs **one reading per target**.

`if_saveparam_wildcard()` / `if_restoreparam_wildcard()` (`spiceif.c`) walk
exactly the same targets in exactly the same order as the existing
`if_setparam_wildcard{,_instance}` — same device-type loop, same model and
instance chains, selected by the same `parmlookup(..., inout=set)` predicate — so
index *i* of the saved array names the same target on the way out as on the way
in. Reading uses the parameter's **askable** twin and the same `doask`/`doset`
pair a plain `alter`/`altermod` uses.

Saving stays all-or-nothing, for the reason E-385 gives: a parameter that is
settable but not askable, or one that is not a plain number (a vector-valued
parameter cannot be rebuilt from a single reading), refuses the whole capture
rather than leaving a half-restored circuit. And the replay is pinned to the
circuit the readings came from — if a `.param` co-knob re-sourced the deck, every
model is already back at its deck value and the saved readings no longer apply.

`sw_read_knob()` now recognises the three wildcard spellings and returns without
parsing, which is what removes the diagnostic.

## Why it survived the audit that exists for exactly this

Enhancement-385 shipped a class oracle, `staterestore_examples/audit/audit_state.py`,
whose job is to catch commands that do not put state back. It reports `sweep`
**clean** — on the defective binary too. Its sweep case is `@r1[resistance]`, a
**concrete** knob, and no wildcard form was ever exercised. The audit is
unchanged and still passes 31/31 commands with the same four known offenders
(`hb`, `pz`, `sens`, `sens_ac`) on both binaries; the wildcard forms are pinned in
the new example instead.

## Verification

* **`examples/wildrestore_examples` 24/24** — and **14/24 on the pre-409 binary**,
  so the example genuinely detects the defect rather than describing it.
* All three wildcard spellings restore, with **differing** nominals per target,
  and both `-vs` orders restore the concrete co-knob too.
* The sweep still sweeps: `i1` follows −1/(λ·1k) at the three points, so
  restoration was added without changing what the sweep does.
* A wildcard matching nothing is still reported and disturbs nothing.
* `sweepwild` (E-268/-269), `wildparam` (E-284) and `staterestore` (E-385) all
  pass unchanged.
* **Full regression 326/326.** The compiler is untouched — this release is
  entirely ngspice-side.

## Found by

A user report: *"the sweep seemed to run fine but I got a parser error at the end
saying `wavelength_nm]` is not found."* The reported name carrying a stray `]` is
what identified it as a tokenizer artifact rather than a lookup failure. The
error itself was cosmetic; chasing it found the restore gap behind it, which had
no symptom at all.
