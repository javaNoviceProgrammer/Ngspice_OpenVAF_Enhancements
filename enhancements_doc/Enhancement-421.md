# Enhancement-421 — the same mistake, reported through one door and not the other

A round-27 hunt over openvaf-r produced five findings. Three of them share a
shape this project keeps rediscovering: **a check exists, it is correct, and it
was never applied to the sibling spelling.** Enhancement-399 rejects a `from`
range no value can satisfy; the identical emptiness written as `exclude` went
straight through. Enhancement-396 and -399 check the names handed to `$limit`
and `analysis()`, and Enhancement-420 just added `ac_stim`; `$simparam` — the
only one of the four whose bad name is *fatal* — was still unchecked.

The round-12 lesson, in the report for that release, was **"when auditing
validation, enumerate EVERY supply path"**. This is that lesson applied twice
more: every way of spelling an empty range, and every builtin that resolves a
string against a fixed table.

## An `exclude` that swallows the whole range

```verilog
parameter real x = 1.0 from [0:10] exclude [0:10];
```

compiled clean, and the parameter is **unsettable**. Every value a netlist
supplies is rejected with `Parameter x is out of bounds!` and the analysis
aborts; only the default reads, because Enhancement-56 exempts defaults from
range checking by design.

That is *exactly* the end state Enhancement-399 reports for `from [3:1]`. It
looked at `from` and never at `exclude`.

It is reached by ordinary routes, not only the exact-cover one — an exclude
**wider** than the range it guards (`from [1:2] exclude [0:10]`, a copy-paste),
or two excludes that happen to tile it.

The check is a small interval sweep over literal bounds, and **the inclusivity of
each endpoint is the whole difficulty**:

| declaration | settable | verdict |
|---|---|---|
| `from [0:10] exclude [0:10]` | nothing | rejected |
| `from (0:10) exclude [0:10]` | nothing | rejected |
| `from [0:10] exclude (0:10)` | exactly `0` and `10` | **accepted** |
| `from [0:10] exclude [0:10)` | exactly `10` | **accepted** |
| `from [0:10] exclude [0:5] exclude [5:10]` | nothing | rejected |
| `from [0:10] exclude [0:5] exclude [6:10]` | `(5, 6)` | **accepted** |

The third row is not a curiosity: it is the reason the sweep tracks *positions*
rather than values, since "just past an open endpoint" is not a float.

## An inverted `exclude` excludes nothing

```verilog
parameter real x = 1.0 from [0:10] exclude [3:1];
```

The author wrote "keep 1 through 3 out" with the bounds the wrong way round.
Nothing is excluded and nothing is said, so every value in the band the
declaration appears to forbid is accepted. `from [3:1]` with those same bounds
has been a compile error since Enhancement-399.

**This is the more insidious of the two.** The cover case fails loudly at run
time; this one never fails at all — it silently permits exactly what the model
meant to forbid. `exclude (3:1)` and `exclude (1:1)` are the same defect;
`exclude [1:1]`, both bounds closed, is a legitimate point exclusion and still
compiles.

### Scope, stated rather than discovered later

* **`inf` does not fold**, so `from [0:inf) exclude [0:inf)` is untouched —
  exactly as Enhancement-399 leaves `from (0:inf)`.
* One unfoldable bound anywhere in the exclusion set and the cover question is
  unanswerable, so nothing is said.
* Several `from` clauses are a **union**; the cover check skips them.
* **The sweep is real-valued.** On an *integer* parameter, `from [0:2] exclude 0
  exclude 1 exclude 2` genuinely is a full cover and is **not** reported.
  Under-reporting is the safe direction and the evidence was real-valued; the
  example suite pins this deliberately so the gap is known rather than
  accidental.

## `$simparam` was the only sibling that kills the run

| construct | compile time | run time |
|---|---|---|
| `analysis("nosuch")` | warns, L021 (E-399) | branch merely dead |
| `$limit(.., "nosuchlim", ..)` | warns, L020 (E-396) | load merely refused |
| `ac_stim("nosuch")` | warns, L021 (E-420) | source merely inactive |
| **`$simparam("nosuchknob")`** | **silent** | **`EVAL_RET_FLAG_FATAL` — the analysis dies** |
| **`$simparam$str("nosuchstr")`** | **silent** | **fatal** |

The severity ordering was exactly inverted: the three that warned degrade
benignly, and the two that said nothing are the only ones that abort. New lint
**L025 `unknown_simparam`**, a warning like its siblings because the name set is
simulator-defined and another OSDI consumer may serve more.

### The list is ngspice's, and that is the entire point

ngspice serves 14 numeric names and 2 string ones (`src/osdi/osdiload.c`,
`sim_params` / `sim_params_str`). The LRM's list is a different set, and
validating against it would have been worse than not validating at all:

* The LRM names `minr`, `imelt`, `shrink`, `imax`, `rthresh`. **ngspice serves
  none of them** — a model using one dies.
* For `$simparam$str` the two sets **do not intersect at all**: the LRM says
  `cwd`, `module`, `instance`, `path`; ngspice serves `analysis_name` and
  `simulator`.

So an LRM-derived check would have warned on precisely the names that work and
stayed silent on the ones that abort.

**`$simparam(name, default)` is deliberately not warned.** Returning the default
for a name this simulator does not serve is what that form is *for*, and is how a
model stays portable across simulators — so the diagnostic points at it by name.
`$simparam$str` has no such form (a single one-argument signature), so every
unresolvable name there is fatal and every one is reported.

### A misreading, corrected

The hunt first reported this as "the compiler blesses names the simulator kills",
on the strength of a `known` list in `validation/body.rs` that names `minr`,
`imelt`, `shrink`, `imax` and `rthresh`. **That list does not claim those names
exist** — it means "does not vary between iterations", and it drives
`const_simparam` versus `variant_const_simparam` (L015) in a constant context
only. The finding is stated above without it. The runtime cross-table is what
carries the claim, and it stands on its own.

## Two smaller things

**More than one `default` arm in a case statement was accepted.** IEEE
1364-2005 §9.5 makes it illegal. The behaviour was never wrong — the first
`default` runs — which is why it is worth saying: the second arm is unreachable
code that looks like it does something. Checked in `syntax/src/validation.rs`,
where the `default` tokens are, so the report points at the offending arm and
back at the one that wins. A duplicate case *item* is legal in Verilog and stays
accepted.

**Two garbled diagnostic strings.** L015's help said "para**ma**eters" and closed
a double quote with an apostrophe (`"gmin'`); an argument-type error read "typed
mismatch invalid function arguments" — two sentences run together with a typo in
the first.

## Verification

* **`examples/rangeguard_examples` — 72/72.** Roughly half is the accept half,
  and the endpoint-inclusivity boundaries are pinned as *behaviour*, not just as
  silence: `from [0:10] exclude (0:10)` is compiled and then driven through
  ngspice to confirm `x=0` and `x=10` are accepted while `x=5` is rejected.
* **The runtime claim is measured.** The L025 note says an unresolvable
  `$simparam` is fatal rather than zero; the suite runs one and asserts the
  analysis aborts. The lint is also exercised as a lint — `-A unknown_simparam`
  silences it, `-E` makes it an error.
* **124-model VA_TEST industry corpus, compiled with the previous shipped binary
  and this one: exactly one difference, and it is the typo fix.** 34 of those
  models use `exclude`; not one changed verdict, and no `$simparam` name in the
  corpus trips L025. This is the differential that mattered — compact models use
  ranges heavily, so an over-eager cover check would have shown up here.
* 40-model `integration_tests/` corpus: **0** changed diagnostics.
* `cargo test --features llvm18` **210/210**, no snapshot moved.
* **Full regression 338/338**, both solvers.

## Found by

A round-27 hunt over openvaf-r, run against the shipped binary. It also verified
a large surface clean and that is worth recording: `aliasparam` end to end
(self-cycle, duplicate, unknown target, name clash, alias-of-a-variable all
already diagnosed; the aliased parameter's range enforced *through* the alias);
`case`/`casex`/`casez` don't-care semantics including `?` correctly rejected in a
plain `case`; every loop bound; **file I/O against invalid, closed, negative and
INT_MAX descriptors with no crash anywhere**; `$param_given` through model,
instance and alias; multi-dimensional arrays including runtime indices and
descending ranges; and `$table_model` control-string validation.

Three of the hunt's own claims were withdrawn on evidence rather than reported:
the `known`-list misreading above, `$simparam_str` "not found in scope" (the LRM
spelling is `$simparam$str`), and a genuine `"$simpara$str"` typo in
`syntax/src/name.rs` that turns out to be **dead code** — its only consumer,
`is_known_sysfun`, has no callers anywhere in the tree.
