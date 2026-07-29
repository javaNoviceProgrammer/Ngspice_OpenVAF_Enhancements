# Enhancement-372 — `unset plots` reported a bogus "Internal Error"

Found by a **plot-lifecycle sequence fuzzer**: random analyses interleaved with
plot-management commands (`destroy`, `setplot`, `unset plots`, `write`/`load`,
`fft`, `linearize`, `remcirc`), run under ASan.

That area was chosen deliberately. It is where
[E-342](Enhancement-342.md) (a borrowed-pointer use-after-free via `unset plots`)
and [E-345](Enhancement-345.md) came from, and
[E-371](Enhancement-371.md) had just added a new allocation and new pointer
arithmetic to it — new ownership code in code with an ownership-bug history is
worth attacking directly.

---

## The finding

It fired in **18 of 120** cases and minimised to a single command, reproducible on
the **shipped** binary:

```
unset plots
```
```
Error: plots is read-only.
cp_remvar: Internal Error: var 112
```

Two separate defects sit in that one line of `cp_remvar()`
(`src/frontend/variable.c`).

### 1. The message printed an ASCII code, not a name

```c
void cp_remvar(char *varname)
...
    fprintf(cp_err, "cp_remvar: Internal Error: var %d\n", *varname);
```

`varname` is a `char *`, so `*varname` dereferences it to its **first character**
and `%d` prints that character's code. `112` is `'p'` — the first letter of
`plots`. `unset curplot` reported `var 99`, which is `'c'`.

The diagnostic has never named the variable it was complaining about. Confirmed by
comparing against the ordinals directly:

| command | printed | first char | ASCII |
| --- | --- | --- | --- |
| `unset plots` | `var 112` | `p` | 112 |
| `unset curplot` | `var 99` | `c` | 99 |

### 2. It was not an internal error

The branch is guarded by `if (*p)`, and `*p` non-NULL only means the variable
**was found** in one of the lists walked just above — which is the normal state
for `plots` and `curplot`. So it fired on **100 %** of ordinary `unset` calls for
them.

An "internal error" that valid user input reaches every single time carries no
signal. It is a false alarm, printed at the user.

## The fix

Drop both spurious prints.

For `US_READONLY`, the `"%s is read-only"` message is already the complete and
correct answer, and nothing is unlinked or freed in that case — which is exactly
right for a read-only variable — so removing the noise changes no behaviour.

For `US_DONTRECORD`, the case's own comment already says *"Do nothing…"*, and its
siblings `curplotname` / `curplottitle` / `curplotdate` were always silent.
`curplot` now matches them instead of being the odd one out.

The remaining `Internal Error` in the same function — `"US val %d", i` — is
**correct** and left alone: `i` really is an `int`, and that default branch is
genuinely unreachable from valid input.

### Checked as a class, not an instance

A grep for the same shape across the frontend — a `%d` conversion fed a
dereferenced `char *` — returns no other occurrence.

## Verification

`examples/unsetvar_examples` needs no sanitizer; the defect is visible in ordinary
output.

```
   fixed:        9/9
   pre-fix:      5/9   unset plots        "Internal Error"
                       unset curplot      "Internal Error"
                       numeric var <N>    still prints 'var 112'
                       fuzzer's sequence  "Internal Error"
```

The four **controls** — `curplotname`, `curplottitle`, `curplotdate`, and an
ordinary set/unset round-trip — pass on **both** binaries. That is what shows the
change is confined to the two affected cases and did not break `unset` itself.

Re-running the fuzzer against the fixed build: **400 iterations, 0 findings**,
with 382/400 cases holding live plots at the end — a real clean result rather than
a harness that stopped doing work. The harness is committed under
`examples/unsetvar_examples/fuzz/` and is not part of the regression sweep.

Regression 295/295.

## What this is not

Not a crash, and not a memory error. It is a diagnostic that misreports its
subject and cries wolf on correct input — worth fixing because a false "Internal
Error" trains users to ignore real ones.

Two process notes recorded so they are not repeated:

- The investigation started by checking whether **E-371** had introduced a leak,
  since it added a `datestring()` allocation to every plot. It had not:
  `killplot()` frees `pl_date`, and peak RSS stayed flat (7152 → 7168 kB) across
  202 → 6060 plots created and destroyed.
- That leak check was first attempted with `ASAN_OPTIONS=detect_leaks=1` and came
  back clean — **meaninglessly**, because macOS/arm64 answers
  *"detect_leaks is not supported on this platform"*. The RSS measurement is what
  actually settled it. A sanitizer that silently does not run is indistinguishable
  from a clean result unless you check.
