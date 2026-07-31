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

**A `@name[param]` string built in C must be lower-cased, and fails silently if it
is not.** The rule is solid; getting to it took two wrong explanations, so this
records what was actually measured rather than what seemed likely.

**The parser rejects uppercase.** A/B at a single call site, same context, same
instant:

```
LPAB raw=<@RL[resistance]> len=0   lower=<@rl[resistance]> len=1
LPDBG expr=<@RL[resistance]> pn=NULL
```

`ft_getpnames_from_string("@RL[resistance]", TRUE)` returns `NULL`; the lower-cased
form returns a length-1 vector.

**It fails inside `PPparse`, before `checkvalid`** — instrumenting the two branches
showed `PPparse FAILED`. That is why nothing was reported: the failure path is

```c
if (PPparse((char **) &sz, &pn) != 0)
    return (struct pnode *) NULL;      /* no diagnostic */
```

so `if_getparam` — which *would* have printed `Error: no such device or model
name` — is never reached. `checkvalid` does warn on a zero-length vector, and it
was confirmed not to fire here.

**Typing the same text works, because the command never sees uppercase.**
Instrumenting `com_print`'s wordlist:

```
PRWL <@rl[resistance]>          <- what com_print receives
GPN  <@rl[resistance]> check=1  <- what reaches the parser
```

You type `@RL[resistance]`; the wordlist already holds `@rl[resistance]`. The fold
happens *before command dispatch*, which is why `print`, `alter`, `show` and
`sweep` all accept uppercase — none of them passes it on. A string a command
builds internally from its own argument words bypasses that fold entirely, which
is exactly what this code did.

**Not established:** where the pre-dispatch fold lives. It is not `com_print`, not
`ft_getpnames_quotes`, not a command-table flag (`co_spiceonly`/`co_major` are the
only booleans), and not a blanket fold of `.control` lines — unquoted
`echo UNQUOTED MixedCaseWORD` preserves case, while
`set myvar = MixedCaseVALUE; echo $myvar` yields `mixedcasevalue`. That
distinction is unresolved, and is left stated rather than guessed at.

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
