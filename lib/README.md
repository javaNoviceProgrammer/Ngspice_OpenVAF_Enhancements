# lib/ — this project's ngspice as a shared library, for KiCad

KiCad never runs an `ngspice` executable: its simulator loads **libngspice**, the
`--with-ngshared` build of the same sources. `bin/` holds the executables the
[Build binaries](../.github/workflows/build-binaries.yml) workflow ships; this
directory holds the libraries the [Build libraries](../.github/workflows/build-libraries.yml)
workflow ships, built natively on each platform from the same `ngspice-46/src`,
so they carry every enhancement of the commit they were built at. The workflow
runs on every push to `main` (a documentation-only push excepted) and commits
the result here as `ci: update prebuilt libraries [skip ci]`.

| bundle | library | with it |
|---|---|---|
| `macos/apple-silicon/`, `macos/intel/` | `libngspice.0.dylib` — install name `@rpath/../PlugIns/sim/libngspice.0.dylib` (KiCad's own), ad-hoc signed, deployment target macOS 12 | `codemodels/*.cm` |
| `linux/intel/`, `linux/arm/` | `libngspice.so.0` — built on Ubuntu 22.04, no glibc symbol newer than 2.35 | `codemodels/*.cm` |
| `windows/intel/`, `windows/arm/` | `libngspice-0.dll` — MSYS2 MINGW64 / CLANGARM64, with the runtime DLLs it needs beside it | `codemodels/*.cm` |

The configure line is the executable's minus the interactive front end —
`--with-ngshared --disable-debug --enable-klu --disable-openmp --without-x
--with-readline=no` — which is also how to build one locally:

```bash
cd ngspice-46 && ./autogen.sh
mkdir -p build-shared && cd build-shared
../configure --with-ngshared --disable-debug --enable-klu --disable-openmp --without-x --with-readline=no
make -j8            # -> src/.libs/libngspice.0.dylib | libngspice.so.0.0.<n> | libngspice-0.dll
```

Keep that tree separate from `build/`: a `--with-ngshared` build has no
interactive paths and is not a drop-in for `build/src/ngspice`.

## Installing into KiCad

**macOS.** `KiCad.app` keeps two independent copies of the library plus a
symlink — `Contents/Frameworks/libngspice.0.dylib`,
`Contents/PlugIns/sim/libngspice.0.dylib` and
`PlugIns/sim/libngspice.dylib -> libngspice.0.dylib`. Replace both real files
and re-sign; the copy here already carries KiCad's install name.

```bash
K=/Applications/KiCad/KiCad.app/Contents
cp "$K/Frameworks/libngspice.0.dylib"  "$K/Frameworks/libngspice.0.dylib.orig"      # back up first
cp "$K/PlugIns/sim/libngspice.0.dylib" "$K/PlugIns/sim/libngspice.0.dylib.orig"
cp lib/macos/apple-silicon/libngspice.0.dylib "$K/Frameworks/"
cp lib/macos/apple-silicon/libngspice.0.dylib "$K/PlugIns/sim/"
codesign -s - --force "$K/Frameworks/libngspice.0.dylib" "$K/PlugIns/sim/libngspice.0.dylib"
```

Quit KiCad before copying. Replacing files inside a signed bundle invalidates
KiCad's signature; the ad-hoc re-sign is usually enough on a machine where the
app already runs, but Gatekeeper may object again after an OS or KiCad update.
The `.orig` copies are the way back short of reinstalling.

**Windows.** KiCad's installer keeps `libngspice-0.dll` in its `bin\`
directory; back it up and replace it with the one from `windows/intel/` (or
`windows/arm/` on an ARM machine), together with any runtime DLL from the same
bundle that KiCad does not already ship.

**Linux.** KiCad loads the distribution's `libngspice.so.0` (typically
`/usr/lib/x86_64-linux-gnu/libngspice.so.0`); back it up and replace it with the
one from `linux/intel/` or `linux/arm/`, or point `LD_LIBRARY_PATH` at the bundle
directory when launching KiCad.

The code models beside each library are the XSPICE `.cm` files built with it
(`analog`, `digital`, `spice2poly`, `table`, `tlines`, `xtradev`, `xtraevt`).
KiCad ships its own copies (macOS: `PlugIns/sim/ngspice/`); they normally keep
working with this library, and can be replaced with these when they do not.

Once installed, a schematic text directive loads an OSDI model compiled with
`openvaf-r` — `.control` / `pre_osdi /path/to/model.osdi` / `.endc` — and every
`.option` of this project (`autobus`, `osdimc`, `savemc`, …) is available from
KiCad's simulator. `examples/` and the handbook's
[§3.6](../docs/handbook/03-ngspice-workflows.md) describe them.
