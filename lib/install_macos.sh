#!/bin/bash
# install_macos.sh -- put this project's libngspice into KiCad.app (macOS)
#
#   ./lib/install_macos.sh                  # default /Applications/KiCad/KiCad.app
#   ./lib/install_macos.sh /path/KiCad.app  # another bundle
#   ./lib/install_macos.sh --codemodels     # also replace KiCad's XSPICE .cm files
#   ./lib/install_macos.sh --restore        # put the backed-up originals back
#
# KiCad's simulator loads libngspice.0.dylib from two places inside the bundle,
# Contents/Frameworks/ and Contents/PlugIns/sim/ (README.md). The script picks
# the bundle in lib/macos/ that matches this Mac (apple-silicon or intel), keeps
# KiCad's own library beside each copy as libngspice.0.dylib.orig -- written once
# and never overwritten, so it is always the untouched original -- and the
# library replaced by this run as libngspice.0.dylib.prev, copies the new one in,
# and ad-hoc re-signs it. Quit KiCad first; the script refuses to run while it
# is open.

set -euo pipefail

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

APP=""
APP_GIVEN=""
RESTORE=0
CODEMODELS=0
for arg in "$@"; do
    case "$arg" in
        -h|--help) usage 0 ;;
        --restore) RESTORE=1 ;;
        --codemodels) CODEMODELS=1 ;;
        -*) echo "unknown option: $arg" >&2; usage 2 ;;
        *) APP="$arg"; APP_GIVEN="$arg" ;;
    esac
done

if [ "$(uname -s)" != "Darwin" ]; then
    echo "this script installs into KiCad.app and runs on macOS only" >&2
    exit 1
fi

# --- the bundle ---------------------------------------------------------------
if [ -z "$APP" ]; then
    APP="${KICAD_APP:-}"
    [ -z "$APP" ] && [ -d /Applications/KiCad/KiCad.app ] && APP=/Applications/KiCad/KiCad.app
    [ -z "$APP" ] && [ -d /Applications/KiCad.app ] && APP=/Applications/KiCad.app
fi
if [ -z "$APP" ] || [ ! -d "$APP/Contents/MacOS" ]; then
    echo "KiCad.app not found (looked in /Applications/KiCad/KiCad.app and /Applications/KiCad.app);" >&2
    echo "give the bundle's path as the argument, or set KICAD_APP" >&2
    exit 1
fi
C="$APP/Contents"
FW="$C/Frameworks/libngspice.0.dylib"
PL="$C/PlugIns/sim/libngspice.0.dylib"
CM="$C/PlugIns/sim/ngspice"
for f in "$FW" "$PL"; do
    [ -f "$f" ] || { echo "$f is missing -- is this a KiCad 7+ bundle?" >&2; exit 1; }
done

# --- KiCad must be closed -----------------------------------------------------
if pgrep -f "$APP/Contents/" >/dev/null 2>&1; then
    echo "KiCad is running (from $APP); quit it, then run this again" >&2
    exit 1
fi

# --- writable? ----------------------------------------------------------------
if [ ! -w "$C/Frameworks" ] || [ ! -w "$C/PlugIns/sim" ]; then
    echo "$APP is not writable by $(id -un); run this with sudo" >&2
    exit 1
fi

# --- which library: the Mac's architecture, checked against KiCad's binary ------
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
    MACHINE=arm64            # Apple silicon, even if this shell runs under Rosetta
else
    MACHINE=$(uname -m)      # x86_64 on an Intel Mac
fi
KICAD_BIN="$C/MacOS/kicad"
KICAD_ARCHS=$(lipo -archs "$KICAD_BIN" 2>/dev/null || echo "")
# has_arch "<lipo -archs output>" arm64|x86_64 -- arm64e counts as arm64
has_arch() { echo " $1 " | grep -Eq " $2e? "; }
case "$MACHINE" in
    arm64)
        ARCH=arm64; BUNDLE=apple-silicon
        # an Intel-only KiCad on Apple silicon runs under Rosetta and needs the Intel library
        if [ -n "$KICAD_ARCHS" ] && ! has_arch "$KICAD_ARCHS" arm64; then
            ARCH=x86_64; BUNDLE=intel
            echo "note: this is an Apple-silicon Mac, but $APP is an Intel build ($KICAD_ARCHS) that runs under Rosetta; installing the intel library"
        fi ;;
    x86_64)
        ARCH=x86_64; BUNDLE=intel ;;
    *)
        echo "unrecognised machine architecture '$MACHINE'" >&2; exit 1 ;;
esac

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$LIB_DIR/macos/$BUNDLE/libngspice.0.dylib"
SRC_CM="$LIB_DIR/macos/$BUNDLE/codemodels"

# --- --restore: the .orig copies go back --------------------------------------
if [ "$RESTORE" = 1 ]; then
    n=0
    for f in "$FW" "$PL"; do
        if [ -f "$f.orig" ]; then
            cp -p "$f.orig" "$f" && echo "restored $f"; n=$((n+1))
        else
            echo "no backup $f.orig -- nothing to restore there" >&2
        fi
    done
    if [ -d "$CM" ]; then
        for o in "$CM"/*.cm.orig; do
            [ -f "$o" ] || continue
            cp -p "$o" "${o%.orig}" && echo "restored ${o%.orig}"; n=$((n+1))
        done
    fi
    [ "$n" -gt 0 ] || exit 1
    # the .orig files carry KiCad's own signature, so nothing is re-signed here
    echo "KiCad's original ngspice is back"
    exit 0
fi

# --- install ------------------------------------------------------------------
[ -f "$SRC" ] || { echo "$SRC is missing: the lib/ bundle for $BUNDLE is not in this checkout" >&2; exit 1; }
SRC_ARCHS=$(lipo -archs "$SRC" 2>/dev/null || echo "?")
has_arch "$SRC_ARCHS" "$ARCH" || {
    echo "$SRC is built for '$SRC_ARCHS', not $ARCH" >&2; exit 1; }
if [ -n "$KICAD_ARCHS" ] && ! has_arch "$KICAD_ARCHS" "$ARCH"; then
    echo "$KICAD_BIN is '$KICAD_ARCHS', which cannot load a $ARCH library" >&2; exit 1
fi

echo "Mac: $MACHINE  KiCad: $APP ($KICAD_ARCHS)  library: lib/macos/$BUNDLE/libngspice.0.dylib"
for dst in "$FW" "$PL"; do
    if [ ! -f "$dst.orig" ]; then
        cp -p "$dst" "$dst.orig"
        echo "backed up $dst -> $(basename "$dst").orig"
    else
        cp -p "$dst" "$dst.prev"
        echo "kept $(basename "$dst").orig (the original); the library replaced now is $(basename "$dst").prev"
    fi
    cp "$SRC" "$dst"
    chmod 644 "$dst"
    xattr -d com.apple.quarantine "$dst" 2>/dev/null || true
done
# KiCad's own symlink; put it back if a previous hand install lost it
ln -sfn libngspice.0.dylib "$C/PlugIns/sim/libngspice.dylib"

if [ "$CODEMODELS" = 1 ]; then
    [ -d "$SRC_CM" ] || { echo "$SRC_CM is missing" >&2; exit 1; }
    mkdir -p "$CM"
    for cm in "$SRC_CM"/*.cm; do
        b=$(basename "$cm")
        if [ -f "$CM/$b" ] && [ ! -f "$CM/$b.orig" ]; then cp -p "$CM/$b" "$CM/$b.orig"; fi
        cp "$cm" "$CM/$b"
        xattr -d com.apple.quarantine "$CM/$b" 2>/dev/null || true
    done
    echo "code models: $(ls "$SRC_CM"/*.cm | wc -l | tr -d ' ') .cm files into PlugIns/sim/ngspice/ (originals kept as .orig)"
fi

codesign -s - --force "$FW" "$PL"
codesign --verify "$FW" "$PL"
echo "installed: $(otool -D "$PL" | tail -1) ($(lipo -archs "$PL")), $(stat -f %z "$PL") bytes, signed ad hoc"
if [ -n "$APP_GIVEN" ]; then echo "to go back: $0 --restore \"$APP_GIVEN\""
elif [ -n "${KICAD_APP:-}" ]; then echo "to go back: KICAD_APP=\"$APP\" $0 --restore"
else echo "to go back: $0 --restore"; fi
