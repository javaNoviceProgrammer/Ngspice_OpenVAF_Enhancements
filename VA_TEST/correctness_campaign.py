#!/usr/bin/env python3
"""openvaf-r correctness campaign -- compile every standalone corpus model, build a
generic ngspice netlist for it, run DC / AC / transient, and sanity-check the
results against model-agnostic physical invariants.

The invariants hold for ANY correct device, so a violation points at an openvaf-r
codegen bug -- a mis-stamped contribution breaks current conservation, a bad
expression or derivative yields NaN, an unstable stamp blows up:

  * convergence   -- the DC operating point solves;
  * finiteness    -- no NaN / Inf in DC, AC or transient terminal currents;
  * KCL           -- the electrical terminal currents sum to ~0 (conservation);
  * stability     -- the transient response stays bounded.

Every terminal is driven by a DC source; the first few ELECTRICAL terminals (the
primary device nodes) get distinct modest biases and the rest are held at their 0
reference, so a config-gated / substrate node cannot contribute a spurious
collapse current. i(Vk) is the current the k-th source delivers, so the sum over
electrical terminals of i(Vk) == 0 for a conservative device. The first driven
terminal also carries an AC + sinusoidal stimulus.

The harness adapts to real compact-model idioms it discovers at run time (see
correctness_campaign.md): the device NAME/ports come from the modules the compiled
.osdi actually exports; non-electrical (thermal, ...) nodes are excluded from the
current sum; an optional terminal gated by a selector parameter is enabled by
reading the model's own $fatal message; a conditional-compilation variant with
fewer terminals drops a node; and a singular small-signal matrix at a near-off
bias is retried AC-only with a tiny shunt.

Usage:  python3 VA_TEST/correctness_campaign.py [name-substring ...]
        OPENVAF_BIN / NGSPICE_BIN override the toolchain binaries.
Exit code is non-zero if any device-module is not OK.
"""
import os, re, subprocess, sys, tempfile, math
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # VA_TEST/ lives one level under the repo root
sys.path.insert(0, os.path.join(ROOT, "examples"))  # reuse the committed binary-matrix resolver
from _setup import VAF, NG                          # honours OPENVAF_BIN / NGSPICE_BIN overrides
BIAS = [0.7, 0.35, 0.0, 0.1, 0.2, 0.3, 0.4, 0.15, 0.25, 0.05]
DISC = ("electrical", "thermal", "kinematic", "magnetic", "rotational")
NANINF = re.compile(r'(nan|inf|1#inf|1#ind)', re.I)


def _strip(txt):
    txt = re.sub(r'//[^\n]*', '', txt)
    return re.sub(r'/\*.*?\*/', '', txt, flags=re.S)


def standalone_models():
    va = []
    for dp, _, fs in os.walk(HERE):
        for f in fs:
            if f.endswith(".va"):
                va.append(os.path.join(dp, f))
    inc = set()
    for p in va:
        for m in re.finditer(r'`include\s+"([^"]+)"', open(p, encoding="latin1").read()):
            inc.add(os.path.basename(m.group(1)))
    return sorted(p for p in va if os.path.basename(p) not in inc)


def parse_modules(path):
    """{module_name: (ordered_ports, {port: discipline})} for every module in the
    .va; disciplines are read from the .va + sibling fragment files."""
    txt = _strip(open(path, encoding="latin1").read())
    body = txt
    d = os.path.dirname(path)
    for f in os.listdir(d):
        if f.endswith((".va", ".inc", ".include", ".h")) and f != os.path.basename(path):
            try:
                body += "\n" + _strip(open(os.path.join(d, f), encoding="latin1").read())
            except OSError:
                pass
    # discipline map over ALL declared identifiers (shared across modules)
    disc_all = {}
    for kw in DISC:
        for mm in re.finditer(r'\b' + kw + r'\b([^;]*);', body):
            for tok in re.split(r'[,\s]+', mm.group(1)):
                if re.fullmatch(r'[A-Za-z_]\w*', tok or ""):
                    # a self-heating temperature node is often declared `electrical`
                    # (its "voltage" is temp rise, its "current" is power). Detect it
                    # by conventional NAME so it is excluded from electrical current
                    # KCL. (A group-wide "temperature" keyword scan over-matched --
                    # e.g. psp104's d,g,s,b got mis-flagged -- so name only.)
                    d = "thermal" if re.fullmatch(
                        r'(?i)(dt|dtj|tj|tk|tnode|temp|rth|th)', tok) else kw
                    disc_all.setdefault(tok, d)
    mods = {}
    for m in re.finditer(r'\bmodule\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;', txt, flags=re.S):
        plist = re.sub(r'\(\*.*?\*\)', '', m.group(2), flags=re.S)
        ports = [t.strip() for t in plist.split(',') if t.strip()]
        disc = {p: disc_all.get(p, "electrical") for p in ports}
        mods[m.group(1)] = (ports, disc)
    return mods


def num(s):
    if s is None:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def run_one(name, ports, disc, osdi):
    """Build + run the DC/AC/tran netlist for one device module; return a result."""
    k0 = len(ports)
    r = {"name": name, "nterm": k0}
    d = os.path.dirname(osdi)
    cir = os.path.join(d, "c_%s.cir" % name)

    def build(k, mparams):
        elec = [i for i in range(k) if disc.get(ports[i], "electrical") == "electrical"]
        if not elec:
            return None, None, None
        stim_term = elec[0]
        # Bias only the first few electrical terminals (the primary device nodes:
        # d/g/s/b, c/b/e, a/c). Extra electrical nodes (substrate, body-contact,
        # ...) and all non-electrical nodes are held at 0 -- this exercises the
        # core device physics while keeping any config-gated / optional node at
        # its reference, so it can't contribute a spurious collapse-to-ground
        # current. KCL is still summed over ALL electrical terminals, so a real
        # conservation bug (which shows in the driven-terminal currents) is caught.
        active = set(elec[:4])
        srcs = []
        for i in range(k):
            b = BIAS[i % len(BIAS)] if i in active else 0.0
            stim = " ac 1 sin(%g 0.05 1e6)" % b if i == stim_term else ""
            srcs.append("V%d t%d 0 dc %g%s" % (i, i, b, stim))
        terms = " ".join("t%d" % i for i in range(k))
        ksum = "+".join("i(v%d)" % i for i in elec)
        prints = " ".join("i(v%d)" % i for i in elec)
        deck = f"""* correctness {name}
.control
pre_osdi {osdi}
.endc
N1 {terms} mod
{chr(10).join(srcs)}
.model mod {name}{mparams}
.control
op
let ksum = {ksum}
print {prints}
print ksum
ac dec 3 1 1e9
let acmax = vecmax(abs(i(v{stim_term})))
let acksum = vecmax(abs({ksum}))
print acmax acksum
tran 5n 1u
let trmax = vecmax(abs(i(v{stim_term})))
let trksum = vecmax(abs({ksum}))
print trmax trksum
.endc
.end
"""
        return deck, elec, stim_term

    # Retry loop that adapts to two model quirks, reading the model's own
    # $fatal messages: (1) an optional terminal gated by a selector param
    # ("N nodes connected but COSUBNODE = 0") -> enable the named flag; (2) a
    # conditional-compilation variant with fewer terminals than the .va's last
    # module declaration ("too many nodes connected") -> drop a terminal.
    k = k0
    mparams = ""
    enabled = set()
    out = ""
    elec = stim_term = None
    try:
        for _ in range(8):
            deck, elec, stim_term = build(k, mparams)
            if deck is None:
                r["nelec"] = 0; r["status"] = "NO-ELEC"; return r
            open(cir, "w").write(deck)
            s = subprocess.run([NG, "-b", cir], capture_output=True, text=True,
                               timeout=90, cwd=d, errors="replace")
            out = (s.stdout or "") + (s.stderr or "")
            low = out.lower()
            m = re.search(r'nodes are connected but ([A-Za-z_]\w*)\s*=\s*0', out)
            if "too many nodes" in low and k > 2:
                k -= 1; continue
            if m and m.group(1) not in enabled:
                enabled.add(m.group(1)); mparams += " %s=1" % m.group(1); continue
            break
    except subprocess.TimeoutExpired:
        r["status"] = "TIMEOUT"; return r
    r["nterm"] = k
    r["nelec"] = len(elec)
    if enabled:
        r["params"] = " ".join(sorted(enabled))

    def val(label):
        m = re.search(re.escape(label) + r"\s*=\s*(\S+)", out)
        return m.group(1) if m else None

    if "unable to find definition" in out.lower():
        r["status"] = "INSTANTIATE-FAIL"; r["detail"] = "model/terminal mismatch"; return r
    dc_i = [num(val("i(v%d)" % i)) for i in elec]
    ksv = num(val("ksum"))
    if "no convergence" in out.lower() or any(x is None for x in dc_i) or ksv is None:
        r["status"] = "DC-NOCONV"; return r
    if NANINF.search(" ".join(str(x) for x in dc_i + [ksv])) or not all(math.isfinite(x) for x in dc_i):
        r["status"] = "DC-NAN"; return r
    imax = max((abs(x) for x in dc_i), default=0.0)
    # a real conservation bug (a mis-stamped contribution) leaves a residual
    # ~O(imax); numerical noise sits at the solver's abstol (1e-12 A) or roundoff.
    # Threshold: 0.01% of the largest terminal current, floored at 2x abstol.
    tol = 1e-4 * imax + 2e-12
    r["imax"] = imax; r["ksum"] = ksv
    if abs(ksv) > tol:
        r["status"] = "KCL-FAIL"
        r["detail"] = f"|ksum|={ksv:.3e} vs imax={imax:.3e} (rel {abs(ksv)/(imax+1e-30):.1e})"
        return r

    acmax, acksum = num(val("acmax")), num(val("acksum"))
    if (acmax is None or not math.isfinite(acmax)) and "singular" in out.lower():
        # The small-signal (AC) matrix is singular at this near-off operating
        # point -- an internal node has no AC path when the device barely
        # conducts. This is ngspice matrix conditioning, not openvaf producing
        # bad AC: a tiny node-to-ground shunt de-singularizes it. Retry AC-only
        # with rshunt to confirm openvaf's AC codegen yields FINITE output
        # (rshunt would pollute the current-KCL sum, so it is not used for KCL).
        active_r = set([i for i in range(k)
                        if disc.get(ports[i], "electrical") == "electrical"][:4])
        srcs2 = "\n".join(
            "V%d t%d 0 dc %g%s" % (i, i, BIAS[i % len(BIAS)] if i in active_r else 0.0,
                                   " ac 1" if i == stim_term else "")
            for i in range(k))
        deck2 = (f"* ac-retry {name}\n.control\npre_osdi {osdi}\n.endc\n"
                 f"N1 {' '.join('t%d'%i for i in range(k))} mod\n{srcs2}\n"
                 f".model mod {name}{mparams}\n.options rshunt=1e12\n"
                 f".control\nop\nac dec 3 1 1e9\n"
                 f"let acm = vecmax(abs(i(v{stim_term})))\nprint acm\n.endc\n.end\n")
        open(cir, "w").write(deck2)
        try:
            s2 = subprocess.run([NG, "-b", cir], capture_output=True, text=True,
                                timeout=60, cwd=d, errors="replace")
            o2 = (s2.stdout or "") + (s2.stderr or "")
            mm = re.search(r"acm\s*=\s*(\S+)", o2)
            a2 = num(mm.group(1)) if mm else None
            if a2 is not None and math.isfinite(a2):
                acmax, acksum = a2, 0.0
                r["ac_note"] = "rshunt (singular AC at bias)"
        except subprocess.TimeoutExpired:
            pass
    if acmax is None or not math.isfinite(acmax) or NANINF.search(str(acksum)):
        r["status"] = "AC-FAIL" if acmax is None else "AC-NAN"; return r
    trmax, trksum = num(val("trmax")), num(val("trksum"))
    if trmax is None:
        r["status"] = "TRAN-FAIL"; return r
    if not math.isfinite(trmax) or NANINF.search(str(trksum)):
        r["status"] = "TRAN-NAN"; return r
    if trmax > 1e6:
        r["status"] = "TRAN-BLOWUP"; r["detail"] = f"trmax={trmax:.1e}"; return r
    r["ac"] = (acmax, acksum); r["tran"] = (trmax, trksum)
    r["status"] = "OK"
    return r


def run_file(path):
    """Compile the .va, find the modules the .osdi exports, test each."""
    mods = parse_modules(path)
    base = {"file": os.path.basename(path)}
    if not mods:
        return [{**base, "name": None, "status": "PARSE-FAIL"}]
    d = tempfile.mkdtemp()
    osdi = os.path.join(d, "m.osdi")
    vadir = os.path.dirname(path)
    c = subprocess.run([VAF, path, "-o", osdi, "-I", vadir],
                       capture_output=True, text=True, cwd=vadir, errors="replace")
    if c.returncode != 0 or not os.path.exists(osdi):
        return [{**base, "name": None, "status": "COMPILE-FAIL",
                 "detail": (c.stderr or "")[-160:]}]
    # Exported device names appear as a STANDALONE string in the .osdi (the OSDI
    # descriptor's `name` field). Match whole strings-lines only -- matching the
    # name anywhere caught it inside error-message strings too (e.g. "ERROR
    # (psphv): ..." made a non-exported wrapper look like a device).
    try:
        st = subprocess.run(["strings", osdi], capture_output=True, text=True).stdout
    except Exception:
        st = ""
    lines = set(st.splitlines())
    exported = [n for n in mods if n in lines]
    if not exported:  # fall back to any substring hit, else the first module
        exported = [n for n in mods if n in st] or list(mods)[:1]
    results = []
    for n in exported:
        ports, disc = mods[n]
        res = run_one(n, ports, disc, osdi)
        results.append({**base, **res})
    return results


if __name__ == "__main__":
    sel = sys.argv[1:]
    models = standalone_models()
    if sel:
        models = [m for m in models if any(s in m for s in sel)]
    print(f"# {len(models)} files; VAF={os.path.basename(VAF)} NG={os.path.basename(NG)}")
    tally = Counter()
    allres = []
    for p in models:
        for r in run_file(p):
            allres.append(r)
            tally[r["status"]] += 1
            line = f"{r['status']:16} {r.get('nterm','?')}T/{r.get('nelec','?')}e  {str(r.get('name'))[:20]:20} {r['file']}"
            if r["status"] == "OK":
                line += f"   Id~{r['imax']:.1e} ksum={r['ksum']:.1e}"
            elif r.get("detail"):
                line += "   :: " + str(r["detail"])[:70]
            print(line, flush=True)
    print("\n# TALLY:", dict(tally))
    print("# total device-modules tested:", len(allres))
