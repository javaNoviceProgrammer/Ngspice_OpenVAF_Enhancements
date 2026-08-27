# Enhancement-491 — an unbounded number used as a length, and four wrong ones

```
python3 verify_numguard.py
```

68 checks, a few seconds. **18/68** against the pre-fix binary — **50**
checks discriminate.

## What it is

Round 51 found ten defects sharing one shape: **a number the deck supplies, used
without being measured against what it was about to control.**

## The crashes

`set numdgt=<n>` is the user's print precision, and nothing bounded it.
`printnum()` formatted with `sprintf(buf, "%.*e", cp_numdgt, num)` into caller
buffers of `BSIZE_SP` (512); `evtprint.c` formatted into a `char[100]`. `%.*e`
needs `n + 9` bytes, and both thresholds land exactly there:

| command | buffer | crashes at | signal |
|---|---|---|---|
| `print`, `.print` card | 512 | **510** | SIGABRT |
| `eprint` | 100 | **94** | SIGTRAP |

Both from a plain batch deck, no interactivity. `numdgt=94` is an ordinary
"give me lots of digits" value.

The function's **own comment recorded the hazard** and did not bound it:

> *"It can cause buffer overruns. The size of buf is unknown, so cp_numdgt can be
> large enough to cause sprintf() to write past the end of the array."*

The safe DSTRING sibling `printnum_ds()` sits directly below and cannot
overflow — which is exactly why `fourier`, `wrdata`, `write`, `display` and
`diff` were unaffected while only the `print` family crashed.

## The wrong numbers

`PTdivide` added `PTfudge_factor` to **every** divisor, and that factor is
`gmin * 1e-20` — so it was not even a fixed perturbation:

| | default | `gmin=1e-6` | `gmin=1e-3` | `gmin=1e-2` |
|---|---|---|---|---|
| `1/boltz` error | 7e-10 | 0.07% | **42%** | **88%** |

`.option gmin=1e-3` is a routine convergence aid and 1.38e-23 is Boltzmann's
constant.

B-source trig reduced with `x − (int)(x/2π)·2π`, undefined above 2³¹·2π:

| x | B-source | numparam | Verilog-A | libm |
|---|---|---|---|---|
| 1e20 | **+0.99932** | −0.645251 | −0.645251 | −0.645251 |

Both other evaluators were already right, making the B-source the **sole
outlier** — the divergence E-399 forbids.

## The controls

Roughly half the suite pins what must **not** move, because this change touches
every `print` in the simulator and every B-source expression:

* `numdgt` of 6, 12 and 17 still produce 7, 13 and 18 significant digits.
* `1/0` is still a large finite number, so a solve that used to continue still
  does.
* `sin`/`cos`/`tan` at ordinary magnitudes are unchanged.
* An unfiltered `sens`, and a `sens` filter that matches, behave as before.
* Interval measurements keep [E-468](../../enhancements_doc/Enhancement-468.md)'s
  behaviour.
* A valid `s_xfer` transfer function is untouched.
* `.func` still resolves to the last definition, and shadowing a builtin keeps
  [E-467](../../enhancements_doc/Enhancement-467.md)'s own warning.

## The model

`numguard.va` holds one module, `vsin`, whose only job is to be the third leg of
the cross-evaluator comparison: ngspice computes expressions in the B-source
parse tree, in the numparam preprocessor, and in a compiled Verilog-A model, and
`sin(1e20)` must now be the same number in all three.
