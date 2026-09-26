# Enhancement-731: the OSDI loader's case-collision check reads the module's own declarations only — an operating-point variable named `temp`, `m` or `dt` drew, beside E-505's correct "the simulator's own instance parameter wins the lookup", a second warning that the *instance parameter* "is declared more than once differing only in case", against a parameter the model never declared and with no case difference to find; the loader's own rows (`temp`, `dt`/`dtemp`, the `m` spelling of `$mfactor`, the terminal currents) are outside the check now

**Scope:** D1 of the
[ngspice + OSDI hunt of 2026-09-25, evening](../docs/bug_hunts/2026-09-25_ngspice-osdi-plumbing-hierarchy-and-runs.md).
**ngspice only.** `src/osdi/osdiinit.c` (`osdi_create_spicedev` hands
`osdi_warn_case_collisions` the rows `write_param_info` wrote; `osdi_is_mfactor_alias`).
[`examples/limguard_examples/`](../examples/limguard_examples/) (4 checks in section
[2]/[3], 114), [`examples/exportname_examples/`](../examples/exportname_examples/)
(check [7b], 20 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
The hunt page.

**Suites:** `limguard` 114 of 114 (110 of 114 on the E-730 binaries); `exportname` 20 of
20 per solver, both solvers (19 of 20 on E-730); `paramsetinst`, `multimod`, `osdiparam`,
`deckdomain`, `dropguard`, `concat` unchanged; no new build warnings; full sweep, run
alone.

## What was wrong

A module with `(* desc="temp" *) real temp;` — a variable, not a parameter — loaded with

```
Warning: clash: the operating-point variable 'temp' has the same name as the simulator's own instance parameter 'temp', which wins the lookup -- `@<inst>[temp]` reads the simulator's value, not the model's. Rename it in the Verilog-A source.
Warning: clash: instance parameter 'temp' is declared more than once differing only in case; SPICE cannot tell the names apart, so only one of them can be set from a netlist.
```

The first line is [E-505](Enhancement-505.md)'s and is right. The second is
[E-335](Enhancement-335.md)'s, and is wrong twice: the module declares no instance
parameter `temp`, and the two spellings are identical. A variable named `m` drew the same
pair, and one named `dt` too.

The instance table `osdi_create_spicedev` builds starts with rows the *loader* writes —
`dt` and `dtemp` when the module has no `dtemp` of its own, `temp` when it has no `temp`
([E-396](Enhancement-396.md) routes or suppresses them otherwise) — then the module's
own parameters and operating-point variables, then the terminal currents `i_<term>` and
the bare `i` of [E-394](Enhancement-394.md). And `write_param_info` writes the compiler's
`$mfactor` under the spelling `m` as well. E-335's check compared every pair of rows
sharing a keyword with different ids, over the whole table, so the loader's `temp` and the
module's variable `temp` — one keyword, two ids — read as a duplicate declaration. E-396
had narrowed the check from keywords to ids for the *routed* pairs (a CMC model's `dtemp`
shares its id with the loader's row); a variable is not routed, so its id differs, and the
check fired.

## What changed

**The check is handed the module's own rows.** `osdi_create_spicedev` notes where
`write_param_info` starts writing and how many rows it wrote, and
`osdi_warn_case_collisions` runs over that range alone. The loader's prefix (`dt`, `dtemp`,
`temp`) and suffix (`i_<term>`, `i`) are not declarations of the model's, and a collision
with them is either E-505's case (a variable `m`, `temp` or `dt`, warned about once by
name) or E-644's (a variable `i` or `i_<term>` comes first in the table, wins, and is the
author's choice).

**The `m` spelling of `$mfactor` is skipped.** It is the one loader row that sits *among*
the module's rows, so `osdi_is_mfactor_alias` recognises it (keyword `m`, the id of an
instance parameter named `$mfactor`) and a pair holding it is passed over; the compiler
emits `$mfactor` on every module, so a variable `m` met it every time.

The genuine case, `GAIN` beside `gain` with different ids, is reported as before. The
model table's check is unchanged (it has no loader rows).

## Verification

`limguard` section [2]/[3], four new checks: a variable `temp`, `m` and `dt` each draws
E-505's line exactly once and no "declared more than once" (three checks, all three fail
on the E-730 binaries); variables `i_p` and `i` on a two-terminal module draw no line at
all, `@n1[i_p]` and `@n1[i]` read the model's 43 and 44, `@n1[i_n]` the loader's −1 mA
(fails on E-730 with the wrong line for both names). The existing `GAIN`/`gain` check
still passes. `exportname` [7b]: the module of [7] (variables `m`, `temp`, `dt`) loads
with three "wins the lookup" lines and no "differing only in case" (fails on E-730).

By hand: the hunt's [G6] deck on both binaries; `show n1` still lists both `temp` rows
(27 and 44), as before.

## What this does not do

- A variable named `temp`, `m` or `dt` is still unreadable through the accessor — the
  simulator's parameter wins the lookup, as E-505 says. Renaming it is the cure; this only
  stops accusing the module of a second declaration.
- A variable named `i` or `i_<term>` still shadows the synthesized terminal current, as
  [E-644](Enhancement-644.md) chose for `i`; the compiler's L035 says so at build time, and
  the loader now says nothing for `i_<term>` as it said nothing for `i`.
- The wording of the true collision ("instance parameter … declared more than once") is
  unchanged, also when both rows are operating-point variables.
