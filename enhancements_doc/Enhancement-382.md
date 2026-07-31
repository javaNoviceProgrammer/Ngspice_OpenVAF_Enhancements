# Enhancement-382 — `loadpull` left the user's tuner at its last swept point

`loadpull` sweeps the R, L and C of the user's own matching network across the
Smith chart. When it finished it left them wherever the last grid point happened
to put them. The old code said so itself:

```c
/* restore something sane on the load (last set values are fine) */
```

— a comment with no code under it. The last set values are not a result, merely
where the loop stopped:

| | before | after `loadpull` |
| --- | --- | --- |
| `RL` | 50 Ω | **84.83 Ω** |
| `LL` | 1e-15 H | **1.34e-8 H** |

Any following analysis then ran against the wrong network. On the test deck an
`.ac` moved from **0.4789 to 0.6765 — a 41% error**, silently.

## The same class as E-381

[Enhancement-381](Enhancement-381.md) was `stb` handing its probe sources back
**zeroed** rather than restored. This is the same mistake in different words: both
commands borrow parts of the user's circuit, drive them, and then guess at what
"putting them back" means — one guessed zero, the other guessed "wherever we
stopped".

`sweep` already had it right: [Enhancement-350](Enhancement-350.md) captures each
swept parameter's nominal value and puts it back at cleanup. This follows that
precedent — read the tuner's R/L/C before the sweep, write them back after.

Two neighbours were checked and are **not** defects: `optimize` leaves the best
point because that is its deliverable, and `aging` writes back the accumulated
dose because that is the whole command.

## A trap worth recording

The fix did not work twice before it worked, and the reason is worth keeping:

**A C-built query string bypasses the frontend's case-folding, and the validating
parser fails it without a diagnostic.** Two separate mechanisms, and it is worth
separating them because neither is what it first looks like:

*Why the name was wrong.* ngspice lowercases command text before evaluating it
(`inpcom.c`, `*s = tolower_c(*s)`), so typing `print @RL[resistance]` works fine —
it is folded to `@rl[...]` before the lookup ever sees it. But this code built the
string in C from the command-line word list, where `rname` is still `RL`:

```c
snprintf(cmd, sizeof cmd, "@%s[resistance]", rname);   /* rname == "RL" */
pv = lp_eval(cmd, &rl_len);
```

That string never passes through the frontend folding, so it no longer matches the
stored instance name. The fix lower-cases it — matching what the frontend would
have produced, not working around a case-sensitive lookup.

*Why it was silent.* A missing device normally does report itself
(`print @nosuchdev[resistance]` → `Error: no such device or model name nosuchdev`).
That diagnostic comes from `if_getparam`, which is **never reached** here.
`lp_eval` calls `ft_getpnames_from_string(expr, TRUE)`, and that `TRUE` is a
*validate* flag:

```c
if (check && !checkvalid(pn)) {
    vec_free_x(pn->pn_value);
    free_pnode(pn);
    return (struct pnode *) NULL;      /* no diagnostic */
}
```

Validation fails, `NULL` comes back, `lp_eval`'s `if (pn)` body never runs, and it
returns a zero-length result. `have_tuner` stayed 0 and the restore was skipped.

The first attempt blamed placement instead (reading before `loadpull`'s priming
transient). That was a red herring, and only instrumenting the actual code path —
printing whether the block was reached and what the read returned — settled which
of the two was at fault. Same lesson as
[Enhancement-380](Enhancement-380.md), where an implemented-but-ineffective fix
was caught only because it was instrumented.

## Verification

`examples/lprestore_examples` — 7 checks.

```
   fixed:     7/7
   pre-fix:   3/7
```

The four failures are the defect: R and L left moved, the 41% `.ac` shift, and
source-pull mode leaving its own tuner at 70.69 Ω. The three that pass on **both**
binaries are the accept half — `loadpull` still reports a peak Pout (3.9576 dBm,
identical across the fix), running it twice still reports the same optimum, and
`CL` was already unchanged because the last grid point happened not to move it.
`examples/loadpull_examples` passes 4/4 unchanged.

Regression 305/305 → 306/306.
