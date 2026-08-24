# Enhancement-476 — the simulator reports only what it actually has

Four defects from bug-hunt round 45. They are one shape: the simulator's account
of itself did not match what it does. It handed back a number it had never
computed, named a vector it could not produce, accepted a write it never
performed, and warned that a name was unserved while serving it. None of them
raised an error.

## 1. An operating-point variable answered when there was no operating point

```
op simulation(s) aborted
print @n1[op_r]   ->  0.000000000000e+00
print i(v1)       ->  "vector i(v1) is not available or has zero length"
```

The opvar storage lives in the `calloc`'d instance block, so before anything
evaluates it reads a clean **0.0** — and 0.0 is a perfectly ordinary current,
voltage or conductance. The same number came back with no analysis run at all,
and after a `$fatal` killed an evaluation part-way. The vector path in the very
same `print` was honest about it, and the equivalent built-in read produced
nothing, so OSDI was the only channel manufacturing a plausible result.

ngspice already had the rule. `param_forall()` in `src/frontend/device.c` will
not ask for an ask-only parameter unless `ckt->CKTrhsOld` exists:

```c
if ((plist[i].dataType & IF_ASK)
    && !(plist[i].dataType & IF_REDUNDANT)
    && ((plist[i].dataType & IF_SET) || dg->ckt->CKTrhsOld)
```

which is why `show` never displayed a fabricated opvar. The direct
`@dev[opvar]` read was the one path without that guard, and it now has one:
`eval()` in `osdiload.c` — the single funnel every evaluation passes through —
records that the instance has produced values, and `OSDIask` refuses an opvar
until it has. The bit is gated on `$fatal`, because an evaluation that raised
one was abandoned part-way and the variables assigned before that line are not
an answer.

`E_NOTFOUND` rather than `E_BADPARM`: the parameter exists, it just has no value
yet. `doask()` in `spiceif.c` recognises that one code and lets the handler's own
message stand rather than adding a second, vaguer line.

**Parameters are deliberately not gated.** They are inputs, readable as soon as
the deck is parsed, and that is what `@n1[r]` and every suite that reads a
parameter before running relies on.

## 2. Every OSDI device's integrated noise total was advertised and unreachable

```
display  ->  onoise_total_n1 : voltage, real, 1 long
print onoise_total_n1  ->  "vector onoise_total_n1 is not available"
```

```c
NOISE_ADD_OUTVAR(ckt, data, "onoise_%s%s",       GENname, "");   /* N_DENS   */
NOISE_ADD_OUTVAR(ckt, data, "onoise_total_%s%s", GENname, " ");  /* INT_NOIZ */
```

`tprintf` produced `onoise_total_n1␣` — with a trailing blank. `display` pads
the name column so the blank is invisible; every read matches the name literally
and misses. Its own sibling eleven lines above already passed `""`, and every
built-in passes a names array whose element 0 is `""`, which is why
`onoise_total_r9` read back and only OSDI's did not. The per-source children
(`onoise_total_n1_shot`) and the grand `onoise_total` were unaffected, so a
noise run looked complete and only the per-device attribution was missing —
exactly the number a contributor ranking is built from.

These were the only two occurrences of `" "` in the whole `src/osdi/` tree.

## 3. An instance-scope write to a routed model parameter was discarded in silence

`alter @n1[dtemp]=20` on a model that declares `dtemp` itself was accepted,
changed nothing, printed nothing, and left `@n1[dtemp]` reporting the old value.

Enhancement-397 routes ngspice's own `dt`/`dtemp`/`temp` knobs onto the model's
parameter when the model declares one — deliberate, because the industry corpus
(PSP, MEXTRAM, VBIC, HiSIM, BSIM) all declare `dtemp` and the model's own
parameter must win. The routing also places the name in the **instance**
parameter table, so `alter` found it, fell into the loader's temperature branch
and stored the value in `inst->dt`, which nothing reads once the model owns the
name.

Every other model-scope parameter reaching that setter already returned
`E_BADPARM` — `alter @n1[r]` has always been refused honestly. Only the two
routed names were silent. A routed id is a real declared parameter, so
`param < num_params` separates it from the ids the loader synthesizes above the
parameter, opvar and terminal ranges, and it is now refused with the wording
Enhancement-467 uses for the same mistake:

```
Error: 'dtemp' is a MODEL parameter of model 'sm'; `alter` sets instance
parameters. Use `altermod sm dtemp=...` instead.
```

The message has to be issued from `OSDIparam` because `doset()` discards the
setter's return code at the `alter` call site.

A model declaring `dtemp` as an **instance** parameter — the spelling the corpus
actually uses — never reaches that branch and is unaffected. `altermod` and the
netlist `.model` card both continue to reach the physics, and the *read* still
routes to the model's parameter, which is Enhancement-397's design.

## 4. The compiler warned about a name the simulator serves

`$simparam("temp")` produced

```
warning[L025]: $simparam names the simulator parameter "temp", which this
               simulator does not provide
  = an unresolvable name is FATAL at run time
```

Both claims were false. Enhancement-434 added `temp` to ngspice's
`sim_params[]` precisely so a model ported from Spectre could ask for the
simulation temperature, and the call returns the ambient — 27 °C, or 40 under
`.option temp=40`. The compiler's `SIMPARAM_NAMES` was not updated with it, and
the note printed beside the warning held a **third** hand-written copy of the
list that had drifted the same way.

The list whose doc-comment says it is *"taken from `src/osdi/osdiload.c`"* is
now a module-level `pub(crate) const` that the diagnostic is built from, so the
message can no longer disagree with the check. `temp` is added; nothing else
changes.

## What this deliberately does not change

- **`@n1[dtemp]` still reads the model's own parameter.** Only the write is
  refused.
- **`$simparam` matching stays case-sensitive** — `$simparam("TNOM")` is fatal.
  Round 45 reported this as an inconsistency and was wrong: macOS has a
  case-insensitive filesystem, so two probe models written to `sr_TNOM.osdi` and
  `sr_tnom.osdi` were the same file by inode and the second overwrote the first.
  With distinct filenames the behaviour is uniform.
- **An opvar stays readable after a later analysis fails**, once one has
  succeeded. Those values are a real evaluation, and a built-in keeps its last
  state the same way.

**Noted and left open:** `@n1[mul]` reads 0.0 before any analysis rather than
its declared default of 1.0, because OSDI parameter defaults are applied during
setup. That is the same family as §1 and predates this enhancement — the shipped
binary does it too — but correcting it means applying defaults before setup,
which is a different change needing its own evidence. Check `[7]` records the
present behaviour so a future change to it is a deliberate one.

## Verification

`examples/reportguard_examples/verify_reportguard.py` — **31/31**, both solvers.

Against the shipped pre-fix binaries the same suite scores **17/31**, and every
one of the fourteen failures is one of the four defects above.

The invariant behind §1 and §2 is *advertised == deliverable*. Check `[15]`
therefore does not name the two broken vectors: it reads whatever `display`
advertises for the noise plot and requires all of it to be printable, so the
next name built with a stray suffix fails on its own. Checks `[24]`–`[27]` do
the same for the simparam channel, reading the Rust array and the C array out of
the sources, requiring them to be equal, then compiling and running a model that
reads every served name with no default.

Full regression, both solvers. ngspice and openvaf-r.
