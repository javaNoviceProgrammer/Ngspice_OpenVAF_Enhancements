# Enhancement-77 — ngspice zero-warning build: 33 → 0 (version11)

This document describes Enhancement-77: the ngspice counterpart of the
openvaf-r warning cleanup released with Enhancement-66 (44 → 0). A full
clean rebuild of ngspice-46 on macOS/clang emitted **33 warnings**; all
are fixed at the source (five tracked-file changes) or traced to stale
generated files and eliminated. The final clean rebuild is **warning-free**,
and behavior is unchanged (full regression green). No compiler changes.

## The inventory and the fixes

**(1) `'ALIGN' macro redefined` × ~8 — `src/osdi/osdidefs.h`.** The OSDI
glue's `ALIGN(pow)` collides with the macOS SDK's unrelated `ALIGN` from
`<sys/param.h>` in every OSDI translation unit that pulls both. Renamed to
`OSDI_ALIGN` (definition + the one use on `OsdiExtraInstData`).

**(2) `'NODEV' macro redefined` — `src/frontend/display.c`.** Same
collision class: the display driver's local `NODEV` vs the SDK's device
number `NODEV`. One `#undef NODEV` above the local definition.

**(3) `-Wformat` × 4 — `src/frontend/outitf.c`.** The plot-memory guard
printed sizes with `%Id` — a Windows-only length modifier that is
undefined behavior elsewhere, and the reason Enhancement-74/76 saw the
garbled `"memory required (Id Bytes)"` message with no numbers in it.
Replaced with the portable `%zu` (the arguments are `size_t`), so the
guard now reports actual byte counts on every platform.

**(4) `-Wimplicit-const-int-float-conversion` × 3 —
`src/maths/sparse/spfactor.c`.** The Markowitz-product overflow guards
compare a `double` against `LARGEST_LONG_INTEGER` (= `LONG_MAX`), which is
not exactly representable as a double; the implicit conversion rounds it
to 2⁶³. Made the conversion explicit (`(double)LARGEST_LONG_INTEGER`) —
identical semantics, intentional and visible.

**(5) `ld: -undefined suppress is deprecated` × 14.** Two independent
sources, one real:

- **`src/xspice/icm/makedefs.in` (tracked — the real fix):** the XSPICE
  codemodel (`.cm`) link rule hardcodes the pre-macOS-10.3 idiom
  `-bundle -flat_namespace -undefined suppress`, which the modern linker
  deprecates loudly on every one of the codemodel links — including in
  the CI macOS builds. Replaced with `-bundle -undefined dynamic_lookup`,
  the modern spelling for plugins whose host symbols resolve at load
  time (the codemodels' exact situation).
- **Stale generated `configure` (local-only, nothing to commit):** the
  local build tree's `configure` predated libtool 2.4.7's fix for the
  `MACOSX_DEPLOYMENT_TARGET` default (`${VAR-10.0}` matched the
  `10.[012]` → `suppress` branch when the variable is simply unset).
  Regenerated with `./autogen.sh` (libtool 2.5.4), whose logic falls
  through to `dynamic_lookup`; CI already regenerates on every build and
  never had this half.

## Verification

- Full `make clean` rebuild: **0 warnings** (was 33), build exit 0.
- The E-74/E-76 plot-memory message now prints real numbers
  (`memory required (NNN Bytes)`).
- Full regression: all 69 example verify suites pass with the
  zero-warning ngspice; the integration suite 28/28; the VA_TEST corpus
  compiles 92/92 (compiler untouched).

## Scope note

This pass covers everything clang emits on the macOS build — the platform
this project develops on and one of the five CI targets. If the Linux/gcc
or Windows/MinGW CI logs show additional platform-specific warnings, they
are a follow-up round in the same mold (the E-66 openvaf cleanup and this
one give the recipe).
