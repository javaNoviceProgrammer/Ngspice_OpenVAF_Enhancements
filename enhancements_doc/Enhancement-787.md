# Enhancement-787: openvaf-r builds without warnings on rustc 1.99 — the `std::u32::MAX`-style constants it named are deprecated there

**Scope:** openvaf: `mir/src/entities.rs`, `sim_back/src/dae/builder.rs`,
`hir_lower/src/parameters.rs`, `parser/src/token_set.rs`, `basedb/src/line_index.rs`,
`vfs/src/lib.rs`; tests `mir/src/immediates/tests.rs`, `lib/stdx/src/ieee64/tests.rs`. Every
constant keeps its value under its new name; nothing the compiler does changes. From CI run
37103375574.

**Suites:** the full sweep on macOS, 536 of 536; the unit tests of the seven crates touched; the
deprecation lint on rustc 1.97.1 (below), 39 warnings before and none after.

## What was wrong

Since run 36996142076 (2 October) every Build binaries job has printed 36 warnings while building
openvaf-r, the same 36 on all five platforms. The jobs install the current stable Rust, which moved
from 1.98.1 (the last run on 30 September) to 1.99.0. Rust 1.99 deprecates the constants of the old
per-type modules -- `std::u32::MAX`, `std::f64::NEG_INFINITY` -- and the modules themselves, in
favour of the associated constants `u32::MAX` and `f64::NEG_INFINITY`. Until then they were only
marked for deprecation, which the default lints do not report, so the local build (rustc 1.97.1)
printed none.

| Crate | Warnings | Where |
|---|---|---|
| mir | 26 (14 repeats) | `use core::u32;` in `entities.rs`. With the module imported, every `u32::MAX` in the file named the module's constant, including those the `impl_idx_from!` macro expands to for each entity type |
| sim_back | 6 | `std::u32::MAX` in `dae/builder.rs`, five lines (one holds two) |
| hir_lower | 2 | `use std::f64::NEG_INFINITY;` in `parameters.rs` and its one use |
| parser | 1 | `use std::u128;` in `token_set.rs`, imported and not used |
| basedb | 1 | `use std::{iter, usize};` in `line_index.rs` |

## The change

The associated constants are named directly and the module imports are gone. Two more of the same
kind are changed with them: vfs's `std::char::REPLACEMENT_CHARACTER`, which 1.99 does not yet
deprecate but which is marked for it, and `use core::f64;` in two test files, which only `cargo test`
compiles.

## Verification

- rustc 1.97.1 reports the marked constants under `-W deprecated_in_future`. `cargo check --features
  llvm18 --bin openvaf-r` with it gave, before the change, the CI set exactly (the same five crates,
  the same counts) plus vfs's 3, and none after; `cargo check --tests` of mir, stdx, vfs, basedb and
  parser gives none after.
- `cargo build --profile opt --features llvm18 --bin openvaf-r`: no warnings.
- `cargo test` of mir, stdx, vfs, basedb, parser, hir_lower and sim_back: all pass.
- The full sweep: 536 of 536.

## Limits

- The change was checked against 1.99 through the lint on 1.97.1, not with a 1.99 compiler; the
  next CI run shows the count there.
- The other "warning" lines in the same CI logs come from ngspice's C build, MSYS2 and rustup;
  openvaf-r's build step prints no other warnings on any platform.
