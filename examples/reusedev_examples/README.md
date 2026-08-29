# Enhancement-503 — setup reuse for decks containing a built-in semiconductor

```
python3 verify_reusedev.py
```

16 checks, both linear solvers. 8 of them fail without the fix.

## What was wrong

[Enhancement-471](../../enhancements_doc/Enhancement-471.md) reuses the matrix
between sweep points instead of tearing the circuit down and rebuilding it. It
was offered only to circuits built entirely from types whose topology is fixed
*unconditionally* — the linear elements and sources — plus OSDI, whose node
collapse is re-decided and compared on every `CKTtemp`.

Any other device type refused reuse outright. **One transistor anywhere in an
otherwise linear deck disabled it**, and the cost grew with the deck:

| sections | with the BJT (before) | all-linear | penalty |
|---|---|---|---|
| 300 | 0.372 s | 0.109 s | 3.46× |
| 600 | 1.101 s | 0.212 s | 5.28× |
| 1200 | 4.504 s | 0.457 s | 10.09× |

That is a per-**type** gate for a per-**parameter** hazard.

## What is actually at risk

A built-in semiconductor decides its node collapse in `DEVsetup`, from a small
knowable set of parameters and from nothing else:

| type | parameters that build a node |
|---|---|
| BJT | `rc`, `rb`, `re`, **`rco`** |
| Diode | `rs`, `rsw`, `vp`, `tt` |
| JFET | `rd`, `rs` |
| Mos1/2/3/6/9 | `rd`, `rs`, `rsh`, `nrd`, `nrs` |

Each row was read off the device's own setup routine by auditing **every**
`CKTmkVolt` call and the condition guarding it — not from the parameter
documentation, which does not say which parameters build nodes. `rco` is the one
that is easy to miss: it gates a fourth BJT node through its `…Given` flag rather
than through its value.

Sweep any other knob and the topology cannot move. So the sweep now **declares**
what it is varying, and the gate allows reuse for these types when none of the
declared parameters is one that builds a node:

| sections | before | after | recovered |
|---|---|---|---|
| 300 | 0.369 s | 0.162 s | **2.28×** |
| 600 | 1.073 s | 0.330 s | **3.25×** |
| 1200 | 4.487 s | 0.671 s | **6.69×** |

## The declaration is what makes it safe — and its absence is what keeps it safe

`sw_request_reuse()` **clears** the declaration. A caller that cannot enumerate
what it varies inherits nothing and keeps E-471's original, stricter gate:

- **Monte Carlo** binds its draws through the deck, so it declares nothing.
- A **`.param`** knob declares nothing either, because a deck parameter reaches a
  model parameter through an expression this code cannot see — and could be
  feeding the very `rc` that decides a collapse.

The match is whole-token (`" rc rb "`), so a sweep of `rsh` is not read as a
sweep of `rs`.

## What this suite is really checking

That the answers did not move. Reuse that changes a number is not an
optimisation, it is a bug — E-471's own notes record a naive version that
silently froze a node collapse and drew a flat curve. Every check compares the
swept curve against the same sweep under `.option reusesetup=0` and requires
**bit-identical** results, after first asserting that the curve actually *moves*:
a comparison of two flat lines proves nothing.

## A note on where the declaration lives

It is a file-static in `cktdojob.c`, not a field on `CKTcircuit`. The first
version put it in the struct, which grew it by 256 bytes and shifted every field
after it — and that alone, with none of this logic, made the `argguard` suite's
`warn_physics` count vary between 1, 2 and 3 for the same deck. Padding by itself
reproduces it. Something else in ngspice reads that struct by a layout it did not
get from the current header; that is a real latent defect, it is recorded as one,
and this enhancement should not be the thing that makes it reachable.
