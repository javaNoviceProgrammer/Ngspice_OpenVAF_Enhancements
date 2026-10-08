# Enhancement-801: `pz` names a missing or wrong keyword, with the syntax — `pz 1 0 1 0 pol` was "no such parameter on this device or parameter is missing"

**Scope:** D7 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `spicelib/parser/inp2dot.c`: `dot_pz` reads and checks the two words after the four nodes
  before applying them.

`examples/osdislips_examples/` (section [7], ten checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (7 of the 10
in [7] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

`pz` (and `.pz`) takes four nodes, then the transfer type (`vol` or `cur`) and the analysis
(`pol`, `zer` or `pz`). Each word was handed to the analysis's parameter table as read. A missing
word arrived as an empty name, so every slip gave the same line:

```
pz 1 0 1 0 pol
Error: no such parameter on this device or parameter is missing
in   .pz 1 0 1 0 pol
```

The same line came for `pz 1 0 1 0 vol`, for `pz 1 0 1 0`, and for `pole` written for `pol` (which
also printed a stray `pole` line). None of them named the keyword or the syntax. A third word was
ignored.

## The change

`dot_pz` reads up to three words and checks them before applying any. One message per case, each
ending with the syntax `(pz in1 in2 out1 out2 vol|cur pol|zer|pz)`:

| written | message |
|---|---|
| `pol` | the transfer type (`vol` or `cur`) is missing, with what each one means |
| `vol` | the analysis (`pol`, `zer` or `pz`) is missing |
| nothing | both keywords are missing |
| `vol pole`, `vol pz extra` | 'pole' / 'extra' is not a pole-zero keyword |
| `vol cur` | two transfer types are given |
| `vol pz pol` | 'pol' follows both keywords |

Either order stays accepted (`pz vol` as well as `vol pz`), as it was.

## The checks

osdislips [7]:

- the seven slips above, each named with the syntax, and the old line absent;
- `vol pz` and `pz vol` find the RC pole at -1e6;
- `cur pol` is accepted and runs.

## Limits

- `pz 1 0 2 0 cur pol` on the suite's RC, with a voltage source holding the input node, returns
  a zero vector on the E-795 binaries and now alike. That is the analysis, not the card, and it is
  unchanged.
