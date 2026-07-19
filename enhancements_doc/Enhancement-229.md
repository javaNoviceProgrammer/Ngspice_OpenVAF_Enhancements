# Enhancement-229 — `pre_osdi -f`: reload a recompiled OSDI model without restarting

A Verilog-A model developer's inner loop is *edit `.va` → recompile `.osdi` →
re-run*. In ngspice that loop was broken in interactive mode: once an `.osdi` is
loaded, **re-loading it is a no-op**, so a recompiled model never takes effect
until you quit and restart ngspice.

## Why the re-load was skipped

Loading an OSDI object goes through `load_osdi()` (`spicelib/devices/dev.c`),
which is guarded three ways — each deliberate:

1. **Path dedup** — `load_osdi` keeps a global list of every path loaded this
   session; a second load of the same path printed *"already loaded; skipping
   (restart ngspice to load a recompiled file)"* and returned.
2. **Handle dedup** — `load_object_file` (`osdi/osdiregistry.c`) also keys a
   table on the `dlopen` handle.
3. **Device-name dedup** — a device type already in the global `DEVices[]`
   registry is warned-and-ignored, because the model-card lookup scans the table
   front-to-back and the **first (stale) entry wins**, silently shadowing a new
   one (and, for a module named like a built-in, previously crashed model
   creation — see [E-223](Enhancement-223.md)).

Underneath all three, `dlopen` itself caches by path: once a shared library is
mapped, `dlopen`-ing the same path returns the *cached* handle and does not
re-read the file from disk. So even without the guards, a recompiled `.osdi` at
the same path is invisible until the old mapping is gone.

These guards are correct for the normal case (avoid duplicate/shadowing
registration). They just left no way to intentionally refresh a model.

## The fix — an opt-in `-f` flag

`pre_osdi -f <file>` (equivalently the interactive `osdi -f <file>`) forces a
reload:

- **`com_osdi`** (`frontend/com_dl.c`) parses a `-f`/`-force` token anywhere in
  the argument list and passes a `force` flag to `load_osdi`.
- **`load_osdi(path, force)`** (`dev.c`), when the path is already loaded and
  `force` is set, **stages a byte-for-byte copy of the (recompiled) file under a
  fresh, unique path** and loads *that*. This sidesteps `dlopen`'s path cache
  (a new path is always re-read) and avoids `dlclose` — on macOS, `dlclose` does
  not reliably unmap, and overwriting a still-mapped file is not even permitted
  (it faults the process). The staged copy is `remove`d immediately after it is
  mapped, so nothing is left on disk.
- **`osdi_add_device(…, replace)`** swaps the registered device to the freshly
  loaded descriptor **in place** at its existing table index, so no other device
  type's index shifts.

Because a re-`source` builds a fresh circuit, the reloaded model binds cleanly to
the new run. The previous `SPICEdev` and its library mapping are intentionally
left resident: any circuit still built against the old model keeps a valid
device, and freeing descriptor-owned memory would risk a double free. (The one
caveat, documented, is not to re-run a *pre-existing* circuit built against the
prior version of a model after reloading it.)

Behaviour is unchanged without `-f`: a plain re-load is still skipped, now with a
hint pointing at `-f`.

## Verification (`examples/osdireload_examples`)

`verify_osdireload.py` compiles a resistor model twice (R = 1 kΩ, then 2 kΩ),
drives ngspice in pipe mode to load the 1 kΩ version (`i(v1) = −1 mA`),
recompiles the same file to 2 kΩ mid-session, confirms a plain re-load is skipped
(still 1 kΩ), then `osdi -f` reloads it and the operating point changes to the
2 kΩ result (`i(v1) = −0.5 mA`) — all in one process, no restart.

## Scope

ngspice frontend + device registry only, four files (`frontend/com_dl.c`,
`frontend/commands.c` help text, `spicelib/devices/dev.c`,
`spicelib/devices/dev.h`); no solver, analysis, or compiler change. Full
regression: 188/188.
