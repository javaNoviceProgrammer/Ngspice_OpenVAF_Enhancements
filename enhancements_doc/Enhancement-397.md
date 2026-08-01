# Enhancement-397 — `temp`, `dtemp` and `dt` become readable on an OSDI device

ngspice supplies four instance knobs to every device: the multiplier `m` and the
three temperature knobs `temp`, `dtemp` and `dt`. On an OSDI (Verilog-A) device
the three temperature knobs could be **written and never read back**.

```
ngspice> alter @n1[temp]=75
ngspice> op
ngspice> print @n1[temp]
Error: no such parameter temp.
```

The same query on any built-in answers: `@r1[temp]` → 27, `@r1[dtemp]` → 0. So
this is the familiar shape — *it works for a built-in and silently does not for
an OSDI device* — which is the whole subject of
[Enhancement-394](Enhancement-394.md).

## What was wrong

`osdiinit.c` registered the loader's own three entries with `IF_SET` and no
`IF_ASK`:

```c
dst[0] = (IFparm){"dt",    (int)entry->dt,   IF_REAL | IF_SET, ...};
dst[1] = (IFparm){"dtemp", (int)entry->dt,   IF_REAL | IF_SET, ...};
dst[0] = (IFparm){"temp",  (int)entry->temp, IF_REAL | IF_SET, ...};
```

while a model's own parameters get both flags. Nothing in the source defends the
asymmetry; it reads as an omission rather than a decision.

Three things followed:

- `print @n1[temp]` failed, and `show n1` listed neither of the three — a
  debugging surface with a hole in exactly the place a temperature problem is
  investigated.
- **`sweep` over any of them ended with a spurious error.** The sweep itself
  completed and its data was correct, but ngspice's end-of-run vector
  bookkeeping then tried to resolve `@n1[temp]` and could not, so a *successful*
  operation finished with `Error: no such parameter temp.` A diagnostic that
  fires on success is worse than no diagnostic: it cost this project a wrong
  answer, recorded below.
- The knobs looked as though they only existed when the Verilog-A declared them
  — because declaring one turns it into a *model* parameter, which is askable.
  They are in fact supplied by default for every OSDI device.

## Why it was not a matter of adding a flag

The ids collided. `osdiregistry.c` gave the loader's synthesized knobs

```c
uint32_t dt   = descr->num_params + descr->num_opvars;
uint32_t temp = descr->num_params + descr->num_opvars + 1;
```

and `osdiinit.c` gives [Enhancement-394](Enhancement-394.md)'s synthesized
**terminal currents** the same base — so **`dt`'s id *was* terminal 0's id**, and
`temp`'s was terminal 1's. That was survivable only because the two groups were
disjoint by *direction*: the temperature knobs were set-only and the terminal
currents ask-only, so no lookup ever had to choose between them.

Adding `IF_ASK` on top of that collision would have made `@n1[temp]` return a
terminal current — a wrong number where there had at least been an honest error.

So the synthesized ids move **above** the terminal-current range:

```c
uint32_t dt   = descr->num_params + descr->num_opvars + descr->num_terminals;
uint32_t temp = descr->num_params + descr->num_opvars + descr->num_terminals + 1;
```

which makes the three id spaces disjoint and lets both directions be served.
`OSDIparam` dispatches on `param == entry->dt` explicitly, so the write side
follows with no change.

## What it reports

The built-in convention was measured, not assumed — a resistor answers like
this, and an OSDI device now answers identically:

| netlist | `@…[temp]` | `@…[dtemp]` |
| --- | --- | --- |
| *(nothing)* | 27 — the ambient | 0 |
| `temp=75` | 75 | 0 |
| `dtemp=10` | 27 | 10 |
| `.temp 85` | 85 — follows the ambient | 0 |
| `.temp 85` + `dtemp=10` | 85, **not** 95 | 10 |
| `temp=75 dtemp=10` | 75 | **0** |

So `temp` is the **base** temperature in **degrees Celsius**, following
`.temp`/`.option temp` when the instance does not set it, and it never includes
`dtemp`; `dtemp` and `dt` are the offset, and they are the same parameter under
two spellings.

The **last row is a behaviour change, not only a reporting one.** `temp=`
overrides `dtemp=` — Enhancement-394 established that and prints *"Instance
temperature specified, dtemp ignored"*. But `restemp.c` does not merely say so,
it forces `RESdtemp = 0`. That difference was invisible while `dtemp` could not
be read; the moment it can, leaving the written value in place would report an
offset that has no effect on the device. It is cleared now, so what is reported
is what is used. The device temperature is unchanged: `temp=75 dtemp=10` is
348.15 K before and after.

A model that declares `dtemp` or `temperature` itself is untouched. The loader
routes its entry to that model parameter, whose id is *below* the synthesized
range, so it falls through to the ordinary readable-parameter path — which is
what should serve it. Verified: such a model reads back 25 from `dtemp=25` while
`$temperature` correctly stays at the ambient, because the model owns the offset.

## The wrong answer this cost, recorded

Asked whether `sweep` works with these knobs, this project answered **no**, on
the evidence of `Error: no such parameter temp.` The sweep had in fact completed
correctly and its five points were printed immediately above the message; the
harness reported the first error line it found and hid the table.

The lesson is not "read more carefully". It is that **a diagnostic emitted after
a successful operation will be read as a failure of that operation**, by tools
and people alike, and that is sufficient reason to remove it even when the
underlying data is fine.

## Verification

`examples/instknobs_examples` — **127/127 with this change, 92/127 against the
shipped binary**. Thirty-five checks pin the new behaviour.

Every read-back case is checked twice: against the expected value, and against a
**built-in resistor in the same deck** reporting the same two numbers — the
convention is matched, not invented.

The suite also re-pins what the id move could have broken, which is the part
worth having:

- E-394's **terminal currents** still resolve on a three-terminal device and
  still satisfy KCL to 1e-12, with `@n1[temp]` readable on the same device;
- the two-terminal **bare `i` alias** still resolves;
- a **model-declared `dtemp`** is still read from the model's own parameter;
- the **physics is unmoved** — `temp=75 dtemp=10` is still 348.15 K and
  `dtemp=10` alone is still 310.15 K;
- `sweep` over each of the four knobs yields the right number of points **with
  no diagnostic at all**.

Corpus load sweep: **107 models loaded, 0 failures, 5 warnings** — identical to
what [Enhancement-396](Enhancement-396.md) left, so the id move disturbed
nothing in the industry corpus.

Full regression **321/321**.
