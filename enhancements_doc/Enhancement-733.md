# Enhancement-733: the model wildcard `alter @*[p]` names the instances it could not reach — E-284's hint ("no loaded model has parameter 'r', but a loaded instance does -- use the instance wildcard '@#*[r]'") was printed only when no model took the value, so with a built-in resistor in the deck, whose model has an `r` of its own, `alter @*[r]=2k` set that default, counted one and said nothing while the OSDI instances kept their `r`; whenever the wildcard set something, the instances whose parameter is instance-level only are now counted by device type and named, with the instance wildcard for them

**Scope:** D3 of the
[ngspice + OSDI hunt of 2026-09-25, evening](../docs/bug_hunts/2026-09-25_ngspice-osdi-plumbing-hierarchy-and-runs.md).
**ngspice only.** `src/frontend/device.c` (`alter_set`, the model-wildcard branch),
`src/frontend/spiceif.c` (`if_hasparam_wildcard_instance_only`),
`src/include/ngspice/fteext.h`.
[`examples/wildparam_examples/`](../examples/wildparam_examples/) (checks [8]–[12], 14;
`rinst.va`). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `wildparam` 14 of 14 (12 of 14 on the E-730 binaries); `sweepwild`,
`wildrestore`, `mcpolicy`, `dcxsweep`, `busname`, `sweeptemp`, `saveused` unchanged; no
new build warnings; full sweep, run alone.

## What was wrong

Two OSDI instances `N1`, `N2` with the instance parameter `r=1k`, `alter @*[r]=2k`, `op`:

| deck | what the alter says | `@n1[r]` after |
|---|---|---|
| `N1`, `N2` (no built-in) | `Warning: no loaded model has parameter 'r', but a loaded instance does -- use the instance wildcard '@#*[r]'.` | 1k |
| `N1`, `N2` and `R9 a 0 1k` | nothing | 1k |

`@*[p]` is the model wildcard ([E-268](Enhancement-268.md)), `@#*[p]` the instance one
([E-269](Enhancement-269.md)), and [E-284](Enhancement-284.md)'s hint steers from one to
the other — but only from the branch that runs when *no* model took the value. The
built-in resistor's model has a parameter `r` ("Resistor model default value", the
resistance an instance without one gets), so `if_setparam_wildcard` found a model with
`r`, set it (`R9` has its own value and does not follow), returned 1, and the hint's branch
was never entered. The user's instances kept their `r` and nothing said so.

## What changed

**What the model wildcard cannot reach is counted.** `if_hasparam_wildcard_instance_only`
walks the device types with instances in the circuit and counts, for every type whose
model table has no settable `p` but whose instance table has one, its instances — the ones
no model card can carry `p` to — and collects the type names. It only probes.

**And named.** When the model wildcard set at least one model and that count is positive,
`alter_set` prints

```
Warning: the model wildcard '@*[r]' set 1 model, but 3 instances (Vsource, res) carry 'r' as an instance parameter only, which it cannot reach -- use the instance wildcard '@#*[r]' for them.
```

The count is honest about what `@#*[r]` would touch: the voltage source's `r` (a PWL
repeat time) is an instance parameter, so `V1` is in it, and the instance wildcard sets
it too, as it always did. `altermod @*[r]=2k` reaches the same branch and says the same.
When no model took the value the E-284 hint is printed as before, and when nothing is left
behind nothing is printed.

## Verification

`wildparam` [8]–[12] (`rinst`, a resistor whose `r` is an instance parameter, two of them
beside `R9 a 0 1k`): `alter @*[r]=2k` names "set 1 model", the instances it could not reach,
the type `rinst` and `@#*[r]`, and `@n1[r]`, `@n2[r]` stay 1k with `i(v1)` −3 mA (fails on
E-730: silent); `alter @#*[r]=2k` sets both and `R9` too, its `r` being the alias of
`resistance` — 2k, 2k, 2k, −1.5 mA — with no such line; `altermod @*[r]=2k` draws the same
line (fails on E-730); without the built-in, [2]'s message is unchanged.

By hand: the hunt's [AA1] decks on both binaries; `sweep @*[r] lin 2 1k 2k` (untouched:
both points −3 mA, no line); a deck of built-in resistors alone.

## What this does not do

- The model wildcard still sets the built-in's model default, and `R9` with its own value
  still does not follow it; nothing says so (the "N follow it, M keep their own" line is
  the OSDI `altermod`'s, [E-599](Enhancement-599.md)).
- `sweep @*[r]` goes through com_sweep.c's own wildcard path and reports nothing about
  instances; unchanged.
- `@#*[r]` reaches every instance with an `r`, built-in or not — `R9`'s is the alias of
  `resistance`, `V1`'s the repeat time. That is E-269's semantics and is what the new line
  points at; the type names in the line are there so the reader knows what it will touch.
