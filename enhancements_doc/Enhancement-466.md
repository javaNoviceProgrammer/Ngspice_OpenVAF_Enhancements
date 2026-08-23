# Enhancement-466 — `.option autoadapt` is quiet by default

Enhancement-463 reported per **node**: a line for every adapter it injected, and
another for every node that did not qualify. On a deck with many shared bus nodes
that buried the run's own output. The reporting is now opt-in:

```
.option autoadapt          inject adapters, say nothing
.option autoadapt=debug    inject adapters and report each one
```

**Errors are never silenced.** A missing or wrong-shaped adapter model, a name
collision, the same node on both ports of one device, `autoadapt` without
`autobus` — each means the option cannot do what the deck asked for, and a deck
that asked for an adapter and did not get one must not run on in silence. Only
the two *informational* classes moved behind `=debug`: the per-split note, and
the per-node "did not qualify" notices.

## The off-words did not work

Found while making the value mean something. Enhancement-463 never looked at the
value, only at its presence, so **every spelling that means off turned the
feature on**:

| written | E-463 | now |
|---|---|---|
| `.option autoadapt=0` | adapter injected | off |
| `.option autoadapt=false` | adapter injected | off |
| `.option autoadapt=no` | adapter injected | off |
| `.option autoadapt=off` | adapter injected | off |
| `.option noautoadapt` | off | off |

Measured: each of the four moved `v(a[0])` from 0.7560976 to 0.7590361 — the deck
silently gained an adapter its author had just switched off.

This is the **fourth** appearance of that defect in a sibling option.
Enhancement-450 found `savecurrents=0` and `nosavecurrents` both turning it on,
Enhancement-451 found `nocshunt=` moving a node by six orders of magnitude while
printing "unknown option", Enhancement-454 found `autobus=0` meaning on at the
top level and off inside a subcircuit. The word list is the one they share,
`e454_value_is_off`. A new boolean-ish option in this code base should be assumed
to have this bug until its off-words are tested.

An unrecognised value — `.option autoadapt=bogus` — is reported once and then
proceeds quietly, the same shape Enhancement-462 gave an unknown `autobus` style.

## Verification

`examples/adaptquiet_examples/verify_adaptquiet.py` — **22/22**, both solvers.
Every check tests the **value** as well as the text, because "quiet" has to mean
the messages stopped and not that the adapters did: the bare option prints
nothing yet still reads 0.7590361, `=debug` reports and reads the same, the four
off-words and `noautoadapt` all read 0.7560976, the on-words adapt quietly, an
unknown value warns but still adapts, and each error class still speaks while
quiet. Enhancement-463's own suite now asks for `=debug` where it inspects what
the feature did — 26/26 unchanged otherwise.

Full regression **380/380**, both solvers. ngspice-only.
