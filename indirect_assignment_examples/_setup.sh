# Shared setup for the indirect_assignment_examples scripts. Sourced, not run.
#
# Selects the right prebuilt binaries from bin/<os>/<arch>/ for the current
# machine and (re)compiles the opamp model for this platform, because a
# .osdi is a native shared library and is therefore architecture-specific.
#
# After sourcing, the following are set:
#   NG    absolute path to the ngspice binary for this platform
#   VAF   absolute path to the openvaf-r binary for this platform
#   OSDI  absolute path to a freshly compiled opamp.osdi (in .build/)

# Directory containing this file (= indirect_assignment_examples/)
_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_BIN_DIR="$(cd "$_SETUP_DIR/../bin" && pwd)"

# --- detect OS / arch and map to the bin/ matrix ---
case "$(uname -s)" in
  Darwin) _os=macos ;;
  Linux)  _os=linux ;;
  *) echo "Unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) if [ "$_os" = macos ]; then _arch=apple-silicon; else _arch=arm; fi ;;
  x86_64|amd64)  _arch=intel ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

NG="$_BIN_DIR/$_os/$_arch/ngspice"
VAF="$_BIN_DIR/$_os/$_arch/openvaf-r"

for _b in "$NG" "$VAF"; do
  if [ ! -x "$_b" ]; then
    echo "Required binary not found or not executable:" >&2
    echo "  $_b" >&2
    echo "Build it (see CI / README) or check the bin/$_os/$_arch directory." >&2
    exit 1
  fi
done

# --- (re)compile the model for THIS platform (.osdi is arch-specific) ---
_BUILD_DIR="$_SETUP_DIR/.build"
mkdir -p "$_BUILD_DIR"
OSDI="$_BUILD_DIR/opamp.osdi"
if ! ( cd "$_SETUP_DIR" && "$VAF" opamp.va -o "$OSDI" ) >/dev/null 2>&1; then
  echo "openvaf-r failed to compile opamp.va" >&2
  exit 1
fi
[ -f "$OSDI" ] || { echo "opamp.osdi was not produced at $OSDI" >&2; exit 1; }

echo "platform : $_os/$_arch"
echo "  ngspice  : $NG"
echo "  openvaf-r: $VAF"
echo "  model    : $OSDI (compiled for this platform)"
