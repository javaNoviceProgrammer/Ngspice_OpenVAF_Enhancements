# winlink_examples — a compiled model links on Windows (Enhancement 769)

```
python3 verify_winlink.py
```

5 checks, one run (a compiler property; no linear solver is involved). 2 of 5 on the E-768
compiler.

From [Enhancement-516](../../enhancements_doc/Enhancement-516.md) until
[Enhancement-769](../../enhancements_doc/Enhancement-769.md) every model failed to link on
Windows with MSVC's link.exe: `LNK1227: conflicting weak extern definition for
'osdi_io_iter_begin'`. A module is linked from five objects, each carrying the OSDI runtime's
shared state as weak definitions, and on COFF those became weak externals with a different
default in each object. Each weak definition is now in a COMDAT of its own name with "any"
selection.

On Linux and macOS the suite cross-compiles `winres.va` for `<host arch>-pc-windows` through a
stand-in `link.exe` — a shell script put on PATH that keeps the objects — and reads their COFF
symbol tables itself, so no LLVM tool is needed. On Windows the real link.exe does the link
and check [5] is the LNK1227 case.

| check | what it pins |
|---|---|
| [1] | the cross-compile hands the linker five COFF objects (`.o`, `.o1`–`.o4`) for the host's machine |
| [2] | no object defines a weak external (each defined 21) |
| [3] | every symbol defined in more than one object is, in each, an external in a COMDAT section with "any" selection, both I/O hooks among them |
| [4] | where lld-link is installed, the five objects link into a DLL: no duplicate symbol, only C runtime functions unresolved, both hooks and `OSDI_DESCRIPTORS` named in it |
| [5] | the module compiled for the host loads in ngspice: -1 mA across 1 kΩ |
