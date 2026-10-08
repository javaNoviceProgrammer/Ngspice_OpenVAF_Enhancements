# Enhancement-804: a parameter set twice on a `.model` card names the value used — the last, for an instance-parameter default too (the first used to win)

**Scope:** D10 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `spicelib/parser/inpgmod.c`: `inp_warn_dup_param` names the model and the rule; a repeated
  instance-parameter default replaces the value already listed.

`examples/osdislips_examples/` (section [10], four checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (3 of the 4
in [10] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

```
.model dpm dp g=1m g=2m
Warning: dp: parameter 'g' is set more than once on this model card; only one value takes effect -- remove one.
```

The 2m ran, and the message did not say so. The same slip on an instance line has always said
"the last value is used".

E-395 left the winner out on purpose, because a card's two kinds of parameter disagreed:

- a model parameter is written straight through, so the last value on the card won;
- an instance-parameter default is pushed onto the model's defaults list, and the list is
  replayed in reverse when an instance is parsed, so the first value won.

`.model dpm dp k=2 k=3` ran with 2. `showmod` listed both entries. `altermod dpm k=5` edited the
entry nearer the head of the list, which is the one the replay overwrites.

## The change

A repeated instance-parameter default replaces the value already on the list. The list holds one
entry per parameter, and the last value on the card wins, as it does for a model parameter. The
message can state the rule, and names the model rather than the device type:

```
Warning: .model dpm: parameter 'g' is set more than once on this card; the last value is used.
```

E-517's alias case (a name and its `aliasparam` both set) stays an error, as LRM 3.4.7 requires.

## The checks

osdislips [10]:

- `g=1m g=2m`: the message, and 2 mA;
- `k=2 k=3` on the card: the message, and 3 mA (2 mA on the E-795 binaries);
- one `k` entry in `showmod`, which `altermod dpm k=5` moves (5 mA);
- the instance line's own message and result, unchanged.

## Limits

- A deck that repeated an instance-parameter default on a card and relied on the first value now
  gets the last. The warning names the parameter on every load.
