# Enhancement-408 — three ways a bracketed name missed what it pointed at

Everything here lives in the same short path: a name written in a deck, and the
object it is supposed to denote. Three separate places got it wrong, and none of
them said so.

## 1. A leading zero silently split a node in two

`n[1]`, `n[01]` and `n[001]` were three **distinct nodes** — `print all` listed
all three — while the vector lookup canonicalised the index before resolving it.
So a deck that drove them at 1 V, 2 V and 3 V answered:

| probe | before | after |
| --- | --- | --- |
| `v(n[1])` | 1.0 | *singular matrix* |
| `v(n[01])` | **1.0** | *singular matrix* |
| `v(n[001])` | **1.0** | *singular matrix* |

The new answer is the right one: that deck asserts three different voltages on
one node, and it should be reported, not answered confidently with the first of
them.

The sharper case has a single node and no ambiguity at all:

```
v0 m[02] 0 dc 2
r0 m[02] 0 1k
```

| probe | before | after |
| --- | --- | --- |
| `v(m[2])` | *(no such vector)* | 2.0 |
| `v(m[02])` | *(no such vector)* | 2.0 |

The netlist built `m[02]`; the lookup only ever asked for `m[2]`. **The node was
unreachable by every spelling, including its own.**

This is bracket-specific — plain `n01` and `n1` are unrelated names and still
are — and it is settled by Enhancement-221's own header, which states that *"the
scalar names produced use the same bracket form, so a bus `a[0:1]` and an
explicit `a[0]` denote the same node."* If `a[0:1]` produces `a[0]`, then `a[00]`
has to mean `a[0]` too. The netlist now canonicalises the index, so one integer
is one node, and the negative form `m[-01]` canonicalises with it.

## 2. `@dev[param]` could not name any bracketed parameter

`show nd1 : all` lists a bus device's terminal currents `i_a[0]..i_a[3]`
(Enhancement-394) and its array parameter elements `ap[0]..ap[2]`, with correct
values, and the instance line can **set** `ap[0]=5e-3`. But every accessor
truncated the name at the **inner** `]`:

```
Error: no such parameter i_a[0.
```

Read failed, `alter` failed silently (the current it should have changed stayed
put), and a `dc` sweep of it was a **fatal error**. There was no workaround: the
name the simulator prints was not a name it accepts back.

Four independent places each split `@dev[param]` on the first `]`, and all four
had to change, because each serves a different command:

| file | serves |
| --- | --- |
| `frontend/parse.c` (`PPlex`) | lexes the token at all — without this the rest never sees it |
| `frontend/vectors.c` (`vec_get`) | `print`, `let` |
| `frontend/device.c` (`com_alter`) | `alter` |
| `spicelib/analysis/dctrcurv.c` | `.dc @inst[param]` sweeps (Enhancement-62) |

Measured, on a device whose `a[3]` branch carries `4e-3 + ap[0] + gs`:

| | before | after |
| --- | --- | --- |
| `print @nd1[i_a[0]]` | *no such parameter* | 1.0e−03 |
| `print @nd1[i_a[3]]` | *no such parameter* | 6.0e−03 |
| `alter @nd1[ap[0]]=5e-3` | −6.0e−03 *(unchanged)* | −1.0e−02 |
| `dc @nd1[ap[0]] 1e-3 3e-3 1e-3` | **Fatal error** | −6, −7, −8 mA |

**The Enhancement-269 wildcard alias depends on the old truncation.** `@*[[gs]]`
works *because* the outer parse stops at the first `]` and hands `[gs` to the
matcher. Depth tracking applied unconditionally retargets it in silence — so a
name that begins with `[` deliberately keeps the original split. All four
wildcard spellings are pinned to their measured behaviour:

| form | `i(v3)` | |
| --- | --- | --- |
| `alter @#*[gs]=2e-3` | −7.0e−03 | the instance wildcard |
| `alter @*[[gs]]=2e-3` | −7.0e−03 | E-269's alias for it |
| `alter @*[gs]=2e-3` | −6.0e−03 | warns, suggests `@#*[gs]` |
| `alter @#*[[gs]]=2e-3` | −6.0e−03 | warns, *no loaded instance has parameter `[gs`* |

All four are unchanged, and the suite's own `wildparam` example still passes.

## 3. A bus range expanded everywhere except where you read the answer

`[lo:hi]` expanded on OSDI instance lines, R/C node lists, subcircuit calls and
subcircuit port lists — but not on the cards that **name** nodes rather than
connect them:

| card | before | after |
| --- | --- | --- |
| `.print dc v(a[0:3])` | card produced nothing | four columns |
| `.save v(a[0:3])` | *no data saved for Transient analysis* | saved |
| `.plot tran v(a[0:3])` | *can't parse `a[0:3]`* | plotted |
| `.ic v(a[0:1])=0.25` | *IC on non-existent node, ignored* | applied to both |
| `.nodeset v(a[0:1])=0.25` | *Nodeset on non-existent node, ignored* | applied to both |

The four expanded `.print` columns are the four dividers — 0.5, 1/3, 0.2, 1/9 —
checked against the resistor values, not merely against each other.

`inp_expand_buses` skipped these cards by design: its guard admits element lines
and `.subckt`, because those carry **bare** node fields, and its token test
rejects anything parenthesised for the same reason. An output card writes
`v(a[0:3])`, so it needs the wrapper-aware form — one copy of the **whole
token** per index, which is also what carries the `=value` on an IC card. The
spaced spelling `.ic v(a[0:1]) = 0.25` works too: the `= value` is absorbed into
the token so every expanded node keeps it.

## Deliberately left alone

* **A token naming two ranges**, `v(a[0:1],b[0:1])`, has no unambiguous
  expansion — pairing the two elementwise is a guess — so it stays literal and
  is still reported.
* **One unparseable probe voids its whole `.print` card.** Measured on the fixed
  binary: `.print dc v(nosuchnode) v(in)` prints nothing at all, in either probe
  order, while the warning says only that the bad token was *"ignored"*; a
  separate `.print dc v(in)` card beside it survives. So the blast radius is
  exactly one card. This is general `.print` behaviour for any unresolvable
  probe, it is not reached by the bus case any more, and changing it would alter
  error handling for every deck in the suite — wider than the evidence here.

## Verification

* **`examples/busname_examples`, 30/30**, covering all three findings, both
  directions of the wildcard trap, and the two cases that must still be
  rejected.
* **Full regression 325/325**, including Enhancement-221's and -224's own bus
  examples and Enhancement-268/269's `wildparam`.
* The compiler is untouched — this release is entirely ngspice-side.

## Found by

A bug hunt over the vector-node feature. Two of the three findings had already
been contradicted by the simulator's own output before they were understood:
`print all` listed a node no probe could read, and `show` listed a parameter no
accessor would accept.
