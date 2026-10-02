# Enhancement-771: what the first CI sweep found in openvaf-r — on the macOS Intel runner every model failed to link (`ld: library 'System' not found`) because the clang first on PATH was Homebrew's, whose built-in SDK path that machine lacks; the macOS SDK is now named to the linker explicitly, and a select with a constant condition, which made a 20 000-element localparam array take 30 s to code-generate on x86-64, is resolved before LLVM sees it

**Scope:** the first regression sweep on every CI platform (run 36996142076,
2026-10-02). OpenVAF only: `openvaf/linker/src/lib.rs` (`macos_sdk_root`, used by the
macOS link), `openvaf/target/src/spec/x86_64_apple_darwin.rs` (no second `-lSystem`),
`openvaf/mir_llvm/src/builder.rs` (`build_select`). The `arrayscale` suite's bound for
the cross-event compile is 30 s on an x86-64 host. The simulator's share of the same run
is [E-770](Enhancement-770.md).

**Suites:** the full sweep, 536 of 536, and 536 of 536 under Linux's conditions (see
E-770). A model links through a stand-in `ld` that
hides the Command Line Tools SDK, as that runner has none: the E-769 compiler fails with
`ld: library 'System' not found`, this one links and the model loads in ngspice at -1 mA
across 1 kΩ.

## What was wrong

**1. No model linked on the macOS Intel runner.** The sweep failed 372 of 536 suites on
`macos-26-intel`, every one that compiles Verilog-A, with
`ld: library 'System' not found`. openvaf-r links a model by running `clang`, whichever
is first on PATH, and that clang finds libSystem through its default SDK. Apple's
/usr/bin/clang asks xcrun for it. Homebrew's LLVM clang — first on PATH wherever llvm@18
is set up to build openvaf-r, the CI job included — takes it from configuration files
Homebrew writes at install time, which name the Command Line Tools SDK
(`/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk`); that runner has Xcode and no
Command Line Tools, ld was handed a library root that does not exist, and found no
libSystem. The same happens to a user with Homebrew's llvm@18 on PATH and Xcode alone.

When `SDKROOT` is not set, openvaf-r now asks `xcrun --show-sdk-path` and passes the SDK
as `--sysroot=`. That spelling matters: with Homebrew's configuration file present, an
`-isysroot` or an `SDKROOT` loses to the file for the link (`-syslibroot` stays the
Command Line Tools path), while `--sysroot` reaches ld from both clangs. With `SDKROOT`
set, no xcrun, or no such directory, nothing is added. The x86-64 macOS target also
passed its own `-lSystem` on top of the one clang adds, which Apple's linker reported on
every model as `ignoring duplicate libraries: '-lSystem'`; the arm64 target never had
it, and now neither does x86-64.

**2. A 20 000-element localparam array took 36.6 s to compile on Linux.** `arrayscale`
expects under 8 s (0.8 s on a Mac). E-579 made the setup functions branchless, one
`select` per parameter (`given ? value : default`) in one straight-line block, and a
module that large is built at -O0, where no pass folds anything. A localparam is never
given, so each of the 20 000 elements became `select i1 false, double %value, double 1.0`.
On arm64 a select of a double is one `fcsel`; x86 has none, and each became a CMOV_FR64
pseudo whose expansion splits the block and moves the rest of it — quadratic in the
block. `llc -O0` on that module takes 0.24 s for arm64 and 30 s for x86-64, on Linux and
macOS triples alike, 98.6 % of it in "Finalize ISel and expand pseudo-instructions".
`build_select` now resolves a constant condition to its operand, as LLVM's folder would
at -O1: the module has no constant select left and takes 0.11 s on x86-64. Every target
gets the smaller IR; a select whose condition is not constant is emitted as before.

## Checks

- The CI case, reproduced on arm64 macOS: a stand-in `ld` first on PATH rewrites the
  Command Line Tools SDK path to a missing directory. The E-769 compiler: `ld: library
  'System' not found`, exit 65. This one: links, the model loads, `i(v1) = -1.000e-03`.
  Without the stand-in, a model's `LC_BUILD_VERSION` is unchanged.
- `lp713` (the 20 000-element literal): 20 000 constant selects in the dumped IR before,
  0 after; `llc -O0 -mtriple=x86_64-unknown-linux-gnu` on its setup module 30.1 s before,
  0.11 s after.
- `arrayscale` passes; on an x86-64 host the 300-event `@(cross)` compile is bounded at
  30 s instead of 10 s. Its `x = i` selects have real conditions, so each is still a
  CMOV_FR64 expansion on x86-64; the Linux runner took 14.7 s, and a return of the
  quadratic list scheduler (500 events: 111 s on arm64) is far outside either bound.

## Limits

- The macOS Intel runner itself has not run this yet; the evidence is the stand-in that
  hides the Command Line Tools SDK. A link from another host (no xcrun) is unchanged.
- An x86-64 eval with many non-constant double selects in one block (the `@(cross)`
  case) still pays LLVM's pseudo expansion; emitting such a select as an integer select
  of the bits was tried and made a 100-event module slower (11.7 s against 7.5 s), so it
  was not kept.
