# Enhancement-781: the simulator's per-instance OSDI state was misaligned on x86-64 — every BSIM4-class model crashed ngspice on macOS Intel, and every transition and slew model the Windows job lost had the same misalignment

**Scope:** ngspice: `osdi/osdidefs.h` (`osdi_extra_data_off`), `osdi/osdiinit.c` (the instance
block's size), `osdi/osdiregistry.c` (`osdi_extra_instance_data`). From the macOS Intel CI sweep
(run 37047779037), read through E-777's lldb traces.

**Suites:** the full sweep on macOS, 536 of 536. On the CI runners: benchmark, binstale,
osdilimit, paramgiven, paramsetoverload, savecur and vafautodiff on macOS Intel; transedge,
evtedge, rtdomain, opargs, defaulttransition, lrmops, portconnected and domainwarn on Windows.

## What was wrong

Each OSDI instance is one block ngspice allocates: its generic header, the compiled model's
instance data at `inst_offset` (padded to `alignof(max_align_t)`), and after that ngspice's own
per-instance state, `OsdiExtraInstData` -- limiter history, absdelay, transition and slew slots,
crossing times -- and two small arrays. The struct is declared
`aligned(alignof(max_align_t))`, which is 16 on x86-64 (8 on arm64). It was placed straight after
the model's data, at `inst + inst_offset + instance_size`, and `instance_size` is only a multiple
of 8. Whenever it was 8 modulo 16 the struct sat 8 bytes off its declared alignment, and a compiler
that trusts the declaration may use an aligned 16-byte store into it.

On macOS Intel clang did: every one of the 43 ngspice runs that crashed in the seven suites above
stopped at the same instruction, `movapd %xmm11, 0x130(%rbx)` in `OSDIload`, an aligned store of
`lim_old[0..1]` (the MOS/BJT limiter history), with `EXC_I386_GPFLT`. Apple Silicon is not
exposed (its `max_align_t` is 8 bytes, so nothing is misaligned), and the Linux x86-64 job passed
with the same misalignment: its compiler did not emit an aligned 16-byte store there.

The Windows job lost a family of `transition`, `slew` and event models at once (0xC0000005, no
output) while others like them ran. An x86-64 build of ngspice with `-fsanitize=alignment`, run
under Rosetta, sorts the Windows results exactly -- the models it lost have their state
misaligned, the ones it ran do not:

| model (suite) | Windows CI | misaligned accesses, before | after |
|---|---|---|---|
| tedge (transedge) | crash | 130 | 0 |
| slewdemo (opargs) | crash | 100 | 0 |
| rtdom (rtdomain) | crash | 103 | 0 |
| dt_bare (defaulttransition) | crash | 103 | 0 |
| run-time slew rate (domainwarn [27]) | crash | 100 | 0 |
| tramp (transedge) | passes | 0 | 0 |
| constant slew rates (domainwarn [21]..[24], [28]) | passes | 0 | 0 |
| bsim4va (benchmark) | -- | 61 | 0 |

Windows' ngspice is built by MSYS2's GCC, which vectorizes at `-O2` (GCC 12 and later; the Linux
job's Ubuntu 22.04 GCC 11 does not). The Windows job's cdb trace (E-779) is what confirms the
faulting store there.

## The change

`osdi_extra_data_off()` rounds the offset after the model's data up to `MAX_ALIGN`. The block's
size (`osdiinit.c`) and the accessor (`osdiregistry.c`) both use it, so the layout is still
written in exactly two places, now through one helper. The arrays that follow the struct keep
their alignment, since `sizeof(OsdiExtraInstData)` is a multiple of its alignment.

## Verification

- x86-64 `-fsanitize=alignment` ngspice under Rosetta: the eight models above, before and after
  (table); the BSIM4 twin's currents unchanged (`-1.54711300e-04` A against the built-in
  `-1.48954666e-04` A).
- The full sweep on macOS (arm64, where the offset does not change: `MAX_ALIGN` is 8).

## Limits

- The macOS Intel and Windows jobs are where the fix is exercised; the arm64 sweep cannot see it.
