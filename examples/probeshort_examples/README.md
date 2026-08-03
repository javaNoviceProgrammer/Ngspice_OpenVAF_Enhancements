# probeshort_examples — Enhancement-406

A flow probe that **silently shorts the branch it was meant to measure**.

A declared `branch (a,b) br` and the node pair `(a,b)` are **different branches**.
That is correct, and the DAE, the E-400 contribution map and the LRM compliance
notes all agree on it. The trap is what follows: probing the flow of a branch
nothing contributes to makes it an **ideal ammeter** — a 0 V source, supported
since E-36 and documented — so contributing through one spelling and probing
through the other drops an ammeter *in parallel with* the real branch and shorts
it.

The consequence is numeric and was silent:

| model | probe spelling | `i(v1)` |
| --- | --- | --- |
| `ok` | `I(a,mid)` — same as the contribution | −0.5 mA |
| `trap` | `I(br)` — a different branch, same nodes | **−1.0 mA** |

Two 1 kΩ sections in series draw 0.5 mA. With the first shorted they draw 1.0 mA,
rc=0, and before this release no diagnostic at all.

```
python3 examples/probeshort_examples/verify_probeshort.py
```

## What the lint does and does not do

`probe_only_branch_short` (**L023**, warn by default) fires only when a probed
branch has **no contribution of its own** *and* another branch spanning the same
node pair **is** contributed to. It reports; it does not change the semantics,
because the ammeter is a real feature a model may want.

`sense_ok` in `probe_short.va` is that feature used deliberately — a sense branch
nothing else drives, where the short *is* the intended circuit. It must stay
silent, and it does. That is the false positive worth avoiding: **six** probe-only
branches across the shipped corpus rely on the idiom, and a naive "warn on any
probe-only branch" rule would flag all of them.

Swept over every `.va` file this repository ships (640 files), L023 fires **zero**
times, so any future firing is signal.

Suppress with `--allow probe_only_branch_short`, or
`(* openvaf_allow="probe_only_branch_short" *)` on the probing statement or any
enclosing scope; `--deny` makes it an error.

## The four controlled sources

`controlled_sources.va` pins the families where a false positive would hurt most.
VCVS and VCCS use *voltage* probes, so neither lint can apply. CCVS and CCCS
**must** probe a branch current, so every ordinary spelling of them is here.

| model | works? | L023 | L017 |
| --- | --- | --- | --- |
| `va_vcvs`, `va_vccs` | ✅ 10.0 / −1.0 | silent | silent |
| `ccvs_shorted`, `ccvs_pair` | ✅ 0.1 V | silent | silent |
| `ccvs_bare` | ✅ 0.1 V | silent | fires |
| `cccs_shorted`, `cccs_pair` | ✅ −100 V | silent | silent |
| `cccs_bare` | ✅ −100 V | silent | fires |
| `cccs_port`, `cccs_portbranch` | — | silent | silent |
| **`cccs_mixed`** | ❌ **DC solve fails** | **fires** | silent |

**L023 fires on exactly one module, and that module is broken.** `cccs_mixed`
drives the node pair with `V(ps,ns) <+ 0` and probes the declared branch with
`I(sense)` — two 0 V sources in parallel across the same nodes. It does not merely
answer wrong; it does not solve.

`ccvs_bare` and `cccs_bare` (a sense branch with no explicit short) **work**, and
draw the advisory `trivial_probe` (L017) saying the probe is what shorts the
branch. That is exactly where the old L017 wording was worst: it told the author
of a working current-controlled source that the probe *"always returns zero"*,
while the model demonstrably delivered `rm · I_sense` and `β · I_sense`.

> The voltage-controlled pair is named `va_vcvs`/`va_vccs` on purpose. ngspice
> registers **built-in** `vcvs`/`vccs`/`ccvs`/`cccs` devices, so an OSDI module of
> the same name is refused at load (*"device is already registered; keeping the
> existing device"*) and the instance line fails with *"incorrect model type!"*.
> openvaf's `reserved_module_name` lint (**L018**) catches this at compile time and
> its help text predicts that exact failure; the verify script asserts the file is
> L018-clean.

| File | What |
| --- | --- |
| `probe_short.va` | `trap` (reported), `ok` (correct spelling), `sense_ok` (deliberate ammeter) |
| `controlled_sources.va` | VCVS / VCCS / CCVS / CCCS in every ordinary spelling, plus the one broken form |
| `verify_probeshort.py` | checks the reports, the numeric consequences, and the suppression controls |
