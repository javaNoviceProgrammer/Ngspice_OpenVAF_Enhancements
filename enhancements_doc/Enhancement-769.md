# Enhancement-769: a compiled model links on Windows again — every model failed with LNK1227 ("conflicting weak extern definition for 'osdi_io_iter_begin'") from E-516 on, because the runtime state shared by a module's five objects was emitted as COFF weak externals with a different default in each; each weak definition is now in a COMDAT of its own name with "any" selection, and MSVC's link.exe keeps one copy

**Scope:** a user report of 2026-10-02 (Windows, MSVC). OpenVAF only:
`openvaf/osdi/src/compilation_unit.rs` (`coff_comdat_weak_definitions`, called from
`new_codegen` when the target is Windows). Linux and macOS output is unchanged.

**Suites:** a new `winlink` suite, 5 of 5 (2 of 5 on the E-768 compiler); the full sweep
536 of 536. On macOS the section contents and disassembly of three models are
identical to the E-768 compiler's; only the linker's per-link UUID and signature differ, as
they do between two runs of the same compiler.

## What was wrong

openvaf-r builds a module from five objects — the descriptor module and the access,
setup_model, setup_instance and eval units — and links the whole OSDI runtime library
(`osdi/stdlib.c`, compiled to bitcode) into each. E-516 made the library's mutable state
weak, so the five copies merge into one at link time: nineteen `OSDI_SHARED` variables
(the descriptor tables, the deferred-write buffer, the scan cursor) and the two I/O hooks
the simulator looks up, `osdi_io_iter_begin` and `osdi_io_flush`, which `new_codegen` makes
weak_odr. ELF and Mach-O linkers merge weak definitions.

On COFF, LLVM emits a weak definition that has no COMDAT as a *weak external* with a
default symbol, and since LLVM 17 it names that default after the first external symbol of
its object, so that two objects' defaults do not collide. A module's five objects therefore
carried five different defaults for each of the 21 symbols:

```
wr.o1   .weak.osdi_io_iter_begin.default.access_0
wr.o2   .weak.osdi_io_iter_begin.default.setup_model_0
wr.o3   .weak.osdi_io_iter_begin.default.setup_instance_0
wr.o4   .weak.osdi_io_iter_begin.default.eval_0
wr.o    .weak.osdi_io_iter_begin.default.osdi_instance_name
```

MSVC's link.exe refuses two weak externals for one symbol whose defaults differ:

```
fp_amf_slot_waveguide_1310.o2 : fatal error LNK1227: conflicting weak extern definition for
'osdi_io_iter_begin'.  New default '.weak.osdi_io_iter_begin.default.setup_model_0' conflicts
with old default '.weak.osdi_io_iter_begin.default.access_0' in fp_amf_slot_waveguide_1310.o1
```

`osdi_io_iter_begin` is merely the first of the 21 that link.exe meets; lld-link reports the
same objects as duplicate symbols. Every model failed this way from E-516 (2026-08-31) on,
not from the most recent compiler change: E-760 added one more variable to the same pattern.
Nothing caught it because the Windows CI job built openvaf-r.exe and never compiled a model.

The diagnosis was reproduced on macOS by cross-compiling a one-resistor module for
`aarch64-pc-windows` (an MSVC COFF target, with the same rules) through a stand-in `link.exe`
that kept the objects and handed them to lld-link.

## What changed

`new_codegen`, which builds every one of the five units, ends on a Windows target (MSVC and
MinGW alike, `is_like_windows`) with `coff_comdat_weak_definitions`: every defined function
and global whose linkage is weak, weak_odr, linkonce or linkonce_odr and that has no COMDAT
gets one of its own name with "any" selection. In such a COMDAT a weak definition is an
ordinary external in a section of its own, and the linker keeps one copy — the mechanism
MSVC itself uses for inline functions and `__declspec(selectany)` data — which is exactly
the sharing E-516 intended. A `dllexport` hook stays exported.

After the change the same cross-compile gives, in each of the five objects, no weak external
and 21 symbols in "any" COMDATs, and lld-link links them into a DLL whose exports are the
OSDI tables, `osdi_log`, `osdi_instance_name` and both hooks; the only unresolved symbols are
six C runtime functions (`fputs`, `fclose`, `fseek`, `ftell`, `free`, `__acrt_iob_func`) that
`msvcrt.lib` supplies on Windows. Mach-O has no COMDATs and ELF does not need them here, so
no other target takes this path: three models compiled for macOS have section contents and
disassembly identical to the E-768 compiler's.

The README's Windows notes and the handbook's platform paragraph now say that openvaf-r.exe
links each model with MSVC's link.exe, which it finds through a Visual Studio installation,
so compiling Verilog-A on Windows needs Visual Studio or its Build Tools with the C++
workload.

## Checks

`examples/winlink_examples/verify_winlink.py`, a new suite, 5 checks. On a non-Windows host
it cross-compiles a one-resistor module for `<host arch>-pc-windows` through a stand-in
`link.exe` (a shell script on PATH that keeps the objects) and reads the COFF symbol tables
itself, so no LLVM tool is needed: [1] five COFF objects for the right machine reach the
linker; [2] no object defines a weak external (each defined 21); [3] every symbol defined in
more than one object is, in each, an external in a COMDAT section with "any" selection, the
two hooks among them; [4] where lld-link is installed (Homebrew's llvm@18 ships it) the five
objects link into a DLL with no duplicate symbol, only C runtime functions unresolved, both
hooks and `OSDI_DESCRIPTORS` named in it; [5] the module compiled for the host loads in
ngspice and gives -1 mA across 1 kΩ. On a Windows host checks [1] to [4] stand aside and [5]
is the LNK1227 case itself, linked by the real link.exe — which the CI's Windows job now
runs, with the whole regression sweep, since the sweep was added to every platform's build.

## Limits

- The real link.exe has not run here: the evidence is the symbol tables, lld-link, and the
  MSVC semantics of "any" COMDATs. The Windows CI job is the first run against link.exe.
- The MinGW target (`x86_64-pc-windows-gnu`) takes the same path but is not checked by the
  suite, whose stand-in is named for the MSVC linker.
