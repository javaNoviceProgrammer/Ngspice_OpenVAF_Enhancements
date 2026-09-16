"""Bind every IHP paramset file to each constant corner and compile it with the
repo's openvaf-r. The corner binding (`corner_res` is an instance the gnucap
deck creates) and the statistical draws are the two things the tool chain
does not supply yet, so: the instance name is rewritten to the corner module's
name, only the constant corner modules are included, and the mismatch
modules' `$rdist_normal(..., "instance")` draws are replaced by their means
(mismatch off)."""
import os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.join(HERE, "work")          # what fetch.sh downloaded
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
VAF = os.environ.get("OPENVAF_BIN", os.path.join(REPO, "OpenVAF-master-20260610", "target", "opt", "openvaf-r"))
os.makedirs(f"{H}/bound", exist_ok=True); os.makedirs(f"{H}/out", exist_ok=True)

def modules(path):
    s = open(path).read()
    return {m.group(1): m.group(0) for m in re.finditer(r'module\s+(\w+)\s*\(\s*\)\s*;.*?endmodule', s, re.S)}

def stub_draws(text):
    # $rdist_normal(seed, mean, sigma[, "..."]) -> (mean)
    return re.sub(r'\$rdist_normal\(\s*[^,]+,\s*([^,]+),\s*[^,)]+(?:,\s*"[^"]*")?\s*\)', r'(\1)', text)

def corner_file(src, keep, stub, out):
    mods = modules(src)
    # cornerMOShv.va's moshv_fs says `parameter real` where every other corner
    # says `localparam real` (a library slip; LRM 6.4.1 allows references to
    # local parameters only) -- read it as the localparam it is meant to be
    parts = [re.sub(r'^(\s*)parameter real', r'\1localparam real', mods[k], flags=re.M) for k in keep] + [stub_draws(mods[k]) for k in stub]
    open(out, "w").write("\n".join(parts) + "\n")

FILES = {
    # paramset file: (corner instance name, corner file, constant corners, stubbed mismatch modules, include line to add after, extra fixes)
    "resistor_paramset.va":       ("corner_res",  "cornerRES.va",   ["res_typ", "res_bcs", "res_wcs"], ["res_stat_param", "res_mm"], '`include "resistor.va"'),
    "capacitor_paramset.va":      ("corner_cap",  "cornerCAP.va",   ["cap_typ", "cap_bcs", "cap_wcs"], ["cap_mm"], '`include "cap_cmomf.va"'),
    "sg13g2_moslv_paramset.va":   ("corner_moslv", "cornerMOSlv.va", ["moslv_tt", "moslv_ss", "moslv_ff", "moslv_sf", "moslv_fs"], [], '`include "psp103.va"'),
    "sg13g2_moslv_rf_paramset.va": ("corner_moslv", "cornerMOSlv.va", ["moslv_tt", "moslv_ss", "moslv_ff", "moslv_sf", "moslv_fs"], [], '`include "psp103_nqs.va"'),
    "sg13g2_moshv_paramset.va":   ("corner_moshv", "cornerMOShv.va", ["moshv_tt", "moshv_ss", "moshv_ff", "moshv_sf", "moshv_fs"], [], '`include "psp103.va"'),
    "sg13g2_moshv_rf_paramset.va": ("corner_moshv", "cornerMOShv.va", ["moshv_tt", "moshv_ss", "moshv_ff", "moshv_sf", "moshv_fs"], [], '`include "psp103_nqs.va"'),
}
only = sys.argv[1:]
results = []
for f, (inst, cfile, corners, stubs, after) in FILES.items():
    stem = f.replace("_paramset.va", "")
    cconst = f"{H}/bound/{cfile.replace('.va', '_const.va')}"
    corner_file(f"{H}/{cfile}", corners, stubs, cconst)
    for corner in corners:
        tag = f"{stem}_{corner}"
        if only and not any(o in tag for o in only):
            continue
        t = open(f"{H}/{f}").read()
        t = t.replace(after, after + f'\n`include "{os.path.basename(cconst)}"')
        t = t.replace(f"{inst}.", f"{corner}.").replace("103.8.2", "103").replace("108.3.2", "103")
        src = f"{H}/bound/{tag}.va"
        open(src, "w").write(t)
        osdi = f"{H}/out/{tag}.osdi"
        t0 = time.time()
        r = subprocess.run([VAF, "-D__NGSPICE__", "-I", f"{H}/bound", "-I", H, "-I", f"{H}/va/r3_cmc", "-I", f"{H}/va/psp103",
                            "-I", f"{H}/va/cap_cmomi", "-I", f"{H}/va/cap_cmomf", "-o", osdi, src],
                           capture_output=True, text=True, env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"})
        dt = time.time() - t0
        out = r.stdout + r.stderr
        errs = [l for l in out.splitlines() if l.startswith("error")]
        warns = sorted(set(l for l in out.splitlines() if l.startswith("warning[")))
        results.append((tag, r.returncode, dt, errs, warns, os.path.getsize(osdi) if os.path.exists(osdi) else 0))
        print(f"{tag:32s} rc={r.returncode} {dt:5.1f}s {len(errs)} errors {len(warns)} warning kinds  {results[-1][5]:8d} bytes")
        for e in errs[:3]: print("    " + e[:150])
for tag, rc, dt, errs, warns, size in results:
    for w in warns: print(f"  {tag}: {w[:120]}")
