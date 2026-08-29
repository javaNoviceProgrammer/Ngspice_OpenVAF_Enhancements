# Enhancement-503 — setup reuse for decks containing a built-in semiconductor

Enhancement-471 reuses the matrix between sweep points instead of tearing the
circuit down and rebuilding it. It was offered only to circuits built entirely
from types whose topology is fixed *unconditionally* — the linear elements and
sources — plus OSDI, whose node collapse is re-decided and compared against the
snapshot on every `CKTtemp`. Every other device type refused reuse outright.

That is a per-**type** gate for a per-**parameter** hazard, and it is expensive.
One transistor anywhere in an otherwise linear deck disabled reuse for the whole
circuit:

| sections | with one BJT | all-linear | penalty |
|---|---|---|---|
| 300 | 0.372 s | 0.109 s | 3.46× |
| 600 | 1.101 s | 0.212 s | 5.28× |
| 1200 | 4.504 s | 0.457 s | **10.09×** |

## What is actually at risk

A built-in semiconductor decides its node collapse in `DEVsetup`, from a small
knowable set of parameters and from nothing else:

| type | parameters that build a node | where |
|---|---|---|
| BJT | `rc`, `rb`, `re`, **`rco`** | `bjtsetup.c:430-490` |
| Diode | `rs`, `rsw`, `vp`, `tt` | `diosetup.c:385-432` |
| JFET | `rd`, `rs` | `jfetset.c:130-154` |
| Mos1/2/3/6/9 | `rd`, `rs`, `rsh`, `nrd`, `nrs` | `mosNset.c:137-166` |

Each row was read off the device's own setup routine by auditing **every**
`CKTmkVolt` call and the condition guarding it — not from the parameter
documentation, which does not say which parameters build nodes. `rco` is the one
that is easy to miss, and I did miss it on the first pass: it gates a **fourth**
BJT node (`collector`, behind `collCX`) through its `…Given` flag rather than
through its value. The audit is what caught it.

Sweep any other knob — `bf`, `vto`, a resistor elsewhere, the temperature, a
source — and the topology cannot move.

## The change

The sweep now **declares** the parameters it is varying, as a lowercase,
space-bracketed list, and `CKTdoJob` allows reuse for these types when none of
the declared names is one that builds a node:

```
sections   before     after   recovered
     300   0.369 s   0.162 s     2.28x
     600   1.073 s   0.330 s     3.25x
    1200   4.487 s   0.671 s     6.69x
```

The remaining gap to the all-linear time (0.671 s against 0.443 s at 1200) is the
transistor's own evaluation, which no amount of setup reuse can remove.

## The declaration is what makes it safe — and its absence is what keeps it safe

`sw_request_reuse()` **clears** the declaration rather than leaving whatever the
last caller wrote. A caller that cannot enumerate what it varies therefore
inherits nothing and keeps E-471's original, stricter gate:

- **Monte Carlo** (Enhancement-473) binds its random draws through the deck, so
  it declares nothing and is unchanged.
- A **`.param`** knob declares nothing either, because a deck parameter reaches a
  model parameter through an expression this code cannot see — and could be
  feeding the very `rc` that decides a collapse.

The match is whole-token, so a sweep of `rsh` is not read as a sweep of `rs`.

A type absent from **both** tables is still refused, and the new table grows only
when a type's setup has actually been read — which is the rule Enhancement-471
set for the list it sits beside.

## Where the declaration lives, and why that matters

It is a file-static in `cktdojob.c`, **not** a field on `CKTcircuit`.

The first version put it in the struct. That grew `CKTcircuit` by 256 bytes and
shifted every field after it — and made the `argguard` suite fail about two runs
in three, with its `warn_physics` count coming back 1, 2 or 3 at random for the
same deck.

The logic was not the cause. **256 bytes of padding alone, with none of this
code, reproduces it exactly.** Something else in ngspice reads that struct by a
layout it did not get from the current header. That is a real latent defect, it
is recorded as an open finding, and this enhancement must not be the thing that
makes it reachable. Held outside the struct, the layout is byte-for-byte
unchanged and `argguard` is stable 10 runs out of 10.

## Files

| file | change |
|---|---|
| `src/spicelib/analysis/cktdojob.c` | the verified topology-parameter table, the whole-token match, and `CKTdeclareSweptParams()` |
| `src/include/ngspice/cktdefs.h` | declares the setter (no struct change) |
| `src/frontend/com_sweep.c` | builds the declaration from the knob set; `sw_request_reuse_params()` |
| `src/frontend/com_sweep.h` | declares it |

## Verification

`examples/reusedev_examples/verify_reusedev.py` — 16 checks under both linear
solvers, 8 of which fail on the shipped binary. Every reuse check compares the
swept curve against `.option reusesetup=0` and requires **bit-identical**
results, having first asserted that the curve actually moves.
