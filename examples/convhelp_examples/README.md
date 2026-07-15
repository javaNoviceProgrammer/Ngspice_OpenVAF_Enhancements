# Enhancement-204 — auto-triggering DC convergence aids (`.option convhelp`)

ngspice's operating-point solver already escalates **automatically** through gmin
stepping and source stepping. But the two strongest aids —

- the globalized damped-Newton **line search** ([Enhancement-111](../../enhancements_doc/Enhancement-111.md)), and
- **pseudo-transient continuation** ([Enhancement-127](../../enhancements_doc/Enhancement-127.md)) —

only fired if the user hand-set `.option linesearch` / `.option ptcont`, and nothing
told you *which* aid rescued a hard operating point.

`.option convhelp` turns the whole cascade into one automatic ladder and reports the
aid that succeeded:

```
Newton (+ line search) → gmin step → source step → pseudo-transient → optran
```

- **Line search** is enabled for the operating-point Newton (and its fallback
  homotopies). It reduces to a plain full Newton step whenever the full step already
  reduces the residual, so points that converge easily are unaffected.
- **Pseudo-transient continuation** is tried automatically as a fallback — no
  `.option ptcont` needed.
- When a non-trivial aid produces the point, ngspice prints e.g.
  `Note: DC operating point reached via pseudo-transient continuation.`

It is **off by default** (fully backward compatible) and is turned on by
`.option errpreset=conservative`; an explicit `.option convhelp=0` overrides the
preset.

## Demo

`convhelp_demo.cir` is a deliberately stiff DC problem — a behavioral exponential
branch with no junction limiting, fed from a 100 V / 100 Ω source. Plain Newton
overshoots the huge `exp()` derivative to a **spurious ~70.5 V** root (and here even
the transient-op fallback lands on it). The physical root is

```
1e-14·(exp(V/0.026) − 1) = (100 − V)/100   ⇒   V(1) = 0.837922 V
```

With gmin/source stepping disabled, `.option convhelp` auto-fires pseudo-transient
continuation, reaches the **correct 0.837922 V**, and reports the aid:

```
ngspice -b convhelp_demo.cir
```

## Verify

```
python3 verify_convhelp.py
```

35 checks across both linear solvers (KLU + Sparse 1.3): the option is accepted;
convhelp is **result-neutral and silent** on a battery of normal circuits (diode,
BJT, two-diode, resistor network); on the stiff circuit it reaches the correct root
via auto-fired pseudo-transient continuation and changes the outcome versus plain
Newton; `errpreset=conservative` enables the ladder; and an explicit `convhelp=0`
overrides the preset.
