# Enhancement-342 — ownership of the synthetic user-variable list

`cp_usrvars()` synthesizes five variables on demand — `$plots`, `$curplot`,
`$curplottitle`, `$curplotname`, `$curplotdate` — and returns them as a list
that its **callers free**. `cp_getvar()`, `cp_remvar()` and `cp_vprint()` all
end with `free_struct_variable(uv1)`.

That arrangement only works if every node in the list is genuinely owned by the
list. Two places assumed it was. Neither is.

Both defects are reachable from ordinary input, and both are fixed here.

---

## [A] A borrowed node was relinked and then freed — SIGSEGV

`cp_enqvar()` does not always allocate. Its contract is stated in its own header
comment: `tbfreed` is set to 1 when the variable was malloc'd there and may
safely be freed, and to 0 when a live plot- or circuit-environment variable is
returned instead.

```c
/* frontend/options.c */
if (plot_cur) {
    for (vv = plot_cur->pl_env; vv; vv = vv->va_next) {
        if (eq(vv->va_name, word)) {
            *tbfreed = 0;          /* BORROWED — points into the live list */
            return vv;
        }
    }
    *tbfreed = 1;                  /* everything below is freshly allocated */
    ...
```

`cp_usrvars()` declared `int tbfreed`, passed `&tbfreed` to all five calls, and
**never read it**:

```c
if ((tv = cp_enqvar("plots", &tbfreed)) != NULL) {
    tv->va_next = v;               /* rewrites a link in somebody's live list */
    v = tv;
}
```

So a borrowed node did two wrong things at once. `tv->va_next = v` overwrote the
live list's own link, orphaning everything after that node; and the caller's
`free_struct_variable(uv1)` then freed a node that was still owned and still
reachable from `plot_cur->pl_env`.

### Why the name collision is not hypothetical

`pl_env` is written by a **rawfile `Option:` line**:

```c
/* frontend/rawfile.c:483 */
} else if (ciprefix("option:", buf)) {
    ...
    curpl->pl_env = cp_setparse(wl);
```

A rawfile carrying `Option: plots = 1` therefore puts a variable named `plots`
into the plot environment. The next `cp_getvar()` — and every command issues
one — freed it, and the one after that read freed memory.

All five names crash. A control name is unaffected:

| rawfile `Option:` name | before | after |
|---|---|---|
| `plots` | SIGSEGV (139) | clean |
| `curplot` | SIGSEGV (139) | clean |
| `curplotname` | SIGSEGV (139) | clean |
| `curplottitle` | SIGSEGV (139) | clean |
| `curplotdate` | SIGSEGV (139) | clean |
| any other name | clean | clean |

ASan gives the whole chain — allocation, free and use are three different
functions, which is why this survived ordinary review:

```
==65545==ERROR: AddressSanitizer: heap-use-after-free
READ of size 8
    #0 cp_enqvar             options.c:74      <- walks pl_env, reads a freed node
    #1 cp_usrvars            options.c:205
    #2 cp_getvar             variable.c:687
freed by thread T0 here:
    #1 free_struct_variable  variable.c:571    <- cp_getvar tears down the list
    #2 cp_getvar             variable.c
allocated by thread T0 here:
    #2 cp_setparse           variable.c:536
    #3 raw_read              rawfile.c:483     <- the Option: line
```

### The fix

Respect the flag. When `cp_enqvar()` reports that it did not allocate, take a
copy instead of splicing the borrowed node:

```c
for (i = 0; i < NUMELEMS(names); i++) {
    int tbfreed = 0;
    struct variable *tv = cp_enqvar(names[i], &tbfreed);
    if (tv == NULL)
        continue;
    if (!tbfreed)               /* borrowed -- must not be relinked or freed */
        tv = var_copy(tv);
    tv->va_next = v;
    v = tv;
}
```

The five near-identical `if` blocks became a loop over a `names[]` array at the
same time. That is not cosmetic: it makes it impossible to apply the ownership
rule to four of the five sites.

`var_copy()` is new, and is written as the deliberate **dual of
`free_struct_variable()`** — it deep-copies exactly what that function frees
(the name, a `CP_STRING` payload, and a `CP_LIST`'s elements recursively), so a
copy can be handed to any caller that frees its list. A shallow copy would have
moved the bug rather than fixing it, since `free_struct_variable()` recurses
into `va_vlist`.

The second borrowed path in `cp_enqvar()` — `ft_curckt->ci_vars`, fed by a deck
`.option` line — is *not* reachable for these five names today, because when
`plot_cur` is set (it always is once any plot exists) all five return from
inside the `plot_cur` block. Measured, not assumed: a deck `.option plots=1`
does not crash on either binary. The fix is keyed on the ownership flag rather
than on which list the pointer came from, so it covers that path regardless of
whether a future change makes it reachable.

---

## [B] A still-linked variable was freed anyway — SIGABRT

Found while fuzzing the fix for [A], and **independent of it**: no file, no
rawfile, nothing but a `.control` block.

```
unset plots           ->  abort (SIGABRT, 134)
unset curplot         ->  abort
unset curplotname     ->  abort
unset curplottitle    ->  abort
unset curplotdate     ->  abort
unset anythingelse    ->  fine
```

`cp_remvar()` searches four lists for the name — `variables`, `uv1`,
`plot_cur->pl_env`, `ft_curckt->ci_vars` — then calls `cp_usrset()` and ends
unconditionally with:

```c
v->va_next = NULL;
free_struct_variable(v);

free_struct_variable(uv1);
```

But only the `US_OK` arm ever unlinks `v` from the list it was found in. For
`plots` `cp_usrset()` returns `US_READONLY`, and for the four `curplot*` names
it returns `US_DONTRECORD`; both arms leave the node exactly where it was —
inside `uv1`. The first `free_struct_variable(v)` freed it, and the trailing
`free_struct_variable(uv1)` walked the list and freed it a second time. Double
free, and malloc aborts.

The same shape is a latent corruption for the other lists: a variable found in
`variables`, `pl_env` or `ci_vars` and *not* unlinked was freed while those
lists still pointed at it.

### The fix

Track whether the variable is actually ours to free, and free it only then:

```c
bool free_v = FALSE;
...
if (!v) {
    v = var_alloc_num(copy(varname), 0, NULL);
    free_v = TRUE;              /* no list owns this one */
}
...
case US_OK:
    if (*p) {
        *p = v->va_next;
        free_v = TRUE;          /* unlinked from its list, so ours now */
    }
    break;
...
if (free_v) {
    v->va_next = NULL;
    free_struct_variable(v);
}
free_struct_variable(uv1);
```

The refusal itself is unchanged and still visible — `unset plots` reports
`Error: plots is read-only.` It simply no longer aborts on the way out.

---

## Verification

**The fixes.** Both vectors, before and after, on the shipped binary versus the
built one: 5/5 SIGSEGV → clean for [A], 5/5 SIGABRT → clean for [B], with the
control names unchanged in every case.

**Behaviour preserved.** `$plots` still tracks the real plot list
(`const op1 op2` after two `op` runs), `$curplot`/`$curplottitle`/`$curplotdate`
still report correctly, `unset plots` still reports read-only, and an ordinary
`set`/`unset` round-trip is byte-identical to the old binary — including the
pre-existing incidental messages, which were diffed rather than eyeballed.

**Fuzz.** 640 combinations — 5 reserved names × 8 `Option:` value shapes (absent,
integer, real, bare word, list, quoted string, empty `=`, malformed `= = =`) ×
16 follow-up command sequences (reading each synthetic variable, `setplot`,
`display`, `destroy all`, `let`, `set`, `unset` of each name, re-`load`) — each
run twice, once on the plain binary and once under ASan. All clean.

**No leak from the copy.** `var_copy()` allocates, so the copy path was hammered
20,000 times through `cp_usrvars()` and peak RSS compared against the control
run: 7.1 MB versus 7.2 MB. (LeakSanitizer is unavailable on this host, so this
was measured rather than asserted.)

**Regression.** Full suite, 274/274 OK.

**Example.** `examples/usrvarown_examples/` — 6 checks covering both vectors,
the preserved read-only refusal, the read-back values, ordinary variables, and
the committed reproducer deck.

---

## How it was found

Not by fuzzing `unset` or rawfiles. It came out of explaining an unrelated
finding: Enhancement-341 recorded, with measurements, that a long `sweep` scales
quadratically because `cp_getvar()` calls `cp_usrvars()` once per analysis and
`$plots` copies the whole plot list each time.

Tracing that cost through `cp_enqvar()` surfaced the `tbfreed` out-parameter,
and the question "what happens when this returns 0?" had an answer nobody had
asked for. Fuzzing the resulting fix then turned up [B] in the same cluster.

The performance finding in Enhancement-341 remains open and is unaffected by
this change — copying a borrowed node is strictly rarer than the synthesis path
that dominates that cost.
