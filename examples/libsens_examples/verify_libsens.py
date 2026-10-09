#!/usr/bin/env python3
"""Enhancements 823 to 825 (F7-F9 of the 2026-10-08 ngspice + OSDI hunt):
`pre_osdi` in an included library, a `.model` card inside a `.subckt`, and a
Verilog-A $fatal, $finish or $stop raised while `sens` perturbs a parameter.

Enhancement-823 (F7). A `pre_osdi` or `osdi` line in an included file
(`.include`, a `.lib` section) resolved a relative name against the TOP deck's
directory, so a library shipping `models.lib` and `models.osdi` side by side
could not load its object: "Error opening osdi lib", or for `pre_osdi -va`
"no such Verilog-A source". Such a name now resolves beside the file it is
written in, as a nested `.include` does.
  [1] the object and the -va forms from another directory, a library under a
      path with spaces, a .lib section, a nested include, the plain `osdi`
      command; the top deck's own line (control) and a name not found beside
      the library (left as written)

Enhancement-824 (F8). A `.model` inside a `.subckt` is copied once per
instance, and each instance looked its copy up with a linear walk of the model
list: 32 000 wrappers took 9 s with a built-in card inside, 3 s with an OSDI
card, 0.14 s with the card at top level. The lookup now uses the hash the
model table already kept.
  [2] the card inside costs under four times the card at top level, for a
      built-in, an OSDI and an XSPICE card; each copy is still its own card

Enhancement-825 (F9). A $fatal raised while `sens` perturbed a parameter was
printed "(at the operating point)" and ignored -- every sensitivity was
reported -- and $finish and $stop were dropped without a word.
  [3] $fatal aborts sens and names the perturbation, DC and AC; $finish and
      $stop end it with a note; a perturbation that trips nothing (control)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="libsens_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def compile_va(src, out):
    r = subprocess.run([VAF, src, "-o", out], capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def ngrun(deck, cwd, env=None):
    """run a deck file from `cwd`; combined stdout+stderr"""
    p = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, timeout=300,
                       cwd=cwd, errors="replace", env=env)
    return p.stdout + p.stderr


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    return float(m.group(1).rstrip(",")) if m else None


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-12, abs(b))


GRES = """`include "disciplines.vams"
module gres(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
analog I(a,b) <+ g*V(a,b);
endmodule
"""

print("Enhancements 823-825: libraries, model cards in subcircuits, sens perturbations\n")

# ------------------------------------------------------------- [1] ---
print("[1] Enhancement-823: pre_osdi in an included file names its files beside that file")
SUB = os.path.join(WORK, "sub")
write(os.path.join(SUB, "gres.va"), GRES)
compile_va(os.path.join(SUB, "gres.va"), os.path.join(SUB, "gres.osdi"))
SPACE = os.path.join(WORK, "sp ace", "lib")
os.makedirs(SPACE)
shutil.copy(os.path.join(SUB, "gres.osdi"), SPACE)
os.makedirs(os.path.join(SUB, "inner"))
shutil.copy(os.path.join(SUB, "gres.osdi"), os.path.join(SUB, "inner"))
LIBS = {
    "sub/inc.lib": "* lib\n.control\npre_osdi gres.osdi\n.endc\n.model gm gres g=2m\n",
    "sub/incva.lib": "* lib va\n.control\npre_osdi -va gres.va\n.endc\n.model gm gres g=3m\n",
    "sub/models.lib": "* lib sections\n.lib tt\n.control\npre_osdi gres.osdi\n.endc\n.model gm gres g=4m\n.endl tt\n",
    "sub/outer.lib": "* outer\n.include inner/inc.lib\n",
    "sub/inner/inc.lib": "* inner\n.control\npre_osdi gres.osdi\n.endc\n.model gm gres g=5m\n",
    "sub/plain.lib": "* plain osdi\n.control\nosdi gres.osdi\n.endc\n",
    "sub/missing.lib": "* missing\n.control\npre_osdi nothere.osdi\n.endc\n",
    "sp ace/lib/inc.lib": "* lib\n.control\npre_osdi gres.osdi\n.endc\n.model gm gres g=6m\n",
}
for rel, text in LIBS.items():
    write(os.path.join(WORK, rel), text)
ELSEWHERE = os.path.join(WORK, "elsewhere")
os.makedirs(ELSEWHERE)


def top(name, inc, body="v1 1 0 1\nn1 1 0 gm\n.control\nop\nprint i(v1)\n.endc\n"):
    path = os.path.join(WORK, name)
    write(path, f"* {name}\n{inc}\n{body}.end\n")
    return path


for inc, ma, what in ((".include sub/inc.lib", 2e-3, "`pre_osdi gres.osdi` in sub/inc.lib"),
                      (".lib sub/models.lib tt", 4e-3, "the same in a .lib section"),
                      (".include sub/outer.lib", 5e-3, "the same two includes deep (sub/inner/inc.lib)"),
                      ('.include "sp ace/lib/inc.lib"', 6e-3, "a library under a path with a space")):
    out = ngrun(top("t1.cir", inc), ELSEWHERE)
    check(f"[1] {what}, run from another directory: the object loads, i(v1) = -{ma * 1e3:g} mA "
          "(was 'Error opening osdi lib')",
          near(val(out, "i(v1)"), -ma) and "Error opening" not in out, f"{val(out, 'i(v1)')} {out[-300:]}")

env = dict(os.environ, OPENVAF=VAF)
out = ngrun(top("t2.cir", ".include sub/incva.lib"), ELSEWHERE, env)
check("[1] `pre_osdi -va gres.va` in sub/incva.lib: compiled from sub/gres.va into osdi/sub_gres.osdi "
      "beside the top deck, i(v1) = -3 mA (was 'no such Verilog-A source: ./gres.va')",
      near(val(out, "i(v1)"), -3e-3) and os.path.isfile(os.path.join(WORK, "osdi", "sub_gres.osdi")),
      f"{val(out, 'i(v1)')} {os.listdir(WORK)} {out[-300:]}")

out = ngrun(top("t3.cir", ".include sub/plain.lib", "v1 1 0 1\n.control\ndevhelp gres\n.endc\n"), ELSEWHERE)
check("[1] the plain `osdi gres.osdi` command in an included file: the device is loaded "
      "(`devhelp gres` describes it)",
      "gres - A simulator independent device loaded with OSDI" in out, out[-300:])

write(os.path.join(SUB, "deck.cir"),
      "* deck beside its object\n.control\npre_osdi gres.osdi\n.endc\nv1 1 0 1\nn1 1 0 gm\n"
      ".model gm gres g=1m\n.control\nop\nprint i(v1)\n.endc\n.end\n")
out = ngrun(os.path.join(SUB, "deck.cir"), ELSEWHERE)
check("[1] the top deck's own relative `pre_osdi` (control): i(v1) = -1 mA from another directory",
      near(val(out, "i(v1)"), -1e-3), out[-300:])

out = ngrun(top("t4.cir", ".include sub/missing.lib", "v1 1 0 1\n.control\nop\n.endc\n"), ELSEWHERE)
check("[1] a name not found beside the library is left as written: the error names `nothere.osdi`",
      'Error opening osdi lib "nothere.osdi"' in out, out[-300:])

# ------------------------------------------------------------- [2] ---
print("[2] Enhancement-824: a .model inside a .subckt is found by hash")
N = 32000
osdi_abs = os.path.join(SUB, "gres.osdi")


def wrapper_deck(kind, where, n):
    card = {"R": ".model gm r r=1k\n", "osdi": ".model gm gres g=1m\n",
            "xspice": ".model gm gain(gain=2)\n"}[kind]
    dev = {"R": "r1 a b gm\n", "osdi": "n1 a b gm\n", "xspice": "a1 a b gm\nr1 b 0 1k\n"}[kind]
    sub = ".subckt cell a b\n" + (card if where == "inside" else "") + dev + ".ends\n"
    pre = {"R": "", "osdi": f".control\npre_osdi {osdi_abs}\n.endc\n",
           "xspice": f".control\npre_codemodel {CM}\n.endc\n"}[kind]
    tail = "1 0" if kind != "xspice" else "1 o{i}"
    inst = "".join(f"x{i} {tail.format(i=i)} cell\n" for i in range(n))
    probe = "print i(v1)" if kind != "xspice" else "print v(o1)"
    path = os.path.join(WORK, f"w_{kind}_{where}.cir")
    write(path, f"* wrappers {kind} {where}\n{pre}{sub}{'' if where == 'inside' else card}"
                f"v1 1 0 1\n{inst}.control\nop\n{probe}\n.endc\n.end\n")
    return path


def fastest(path, k=3):
    """the fastest of k runs and the last run's output: one sample under a
    parallel sweep can catch a load spike"""
    best, out = None, ""
    for _ in range(k):
        t0 = time.perf_counter()
        out = ngrun(path, WORK)
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best, out


ngdir = os.path.dirname(os.path.abspath(NGSPICE))
CM = next((c for c in (os.path.join(ngdir, "codemodels", "analog.cm"),
                       os.path.join(ngdir, "xspice", "icm", "analog", "analog.cm")) if os.path.isfile(c)), None)
NAMES = {"R": ("a built-in R", "60x"), "osdi": ("an OSDI", "18x"), "xspice": ("an XSPICE", "11x")}
for kind, n, probe, want in (("R", N, "i(v1)", -N * 1e-3), ("osdi", N, "i(v1)", -N * 1e-3),
                             ("xspice", 16000, "v(o1)", 2.0)):
    if kind == "xspice" and CM is None:
        check("[2] an XSPICE card inside (skipped: no analog.cm beside the ngspice binary)", True)
        continue
    t_in, o_in = fastest(wrapper_deck(kind, "inside", n))
    t_top, o_top = fastest(wrapper_deck(kind, "top", n))
    check(f"[2] {n} wrappers, {NAMES[kind][0]} card inside each: under four times the card at top level "
          f"(was {NAMES[kind][1]}), the same answer",
          # the copies cost about 1.6x of their own (a model struct and its
          # setup per instance); a loaded CI runner measured 2.2x, so the
          # limit leaves room for that and still sits far below 11x-60x
          t_in < 4.0 * t_top + 0.05 and near(val(o_in, probe), want) and near(val(o_top, probe), want),
          f"{t_in:.2f} {t_top:.2f} {val(o_in, probe)} {val(o_top, probe)}")

path = os.path.join(WORK, "two.cir")
write(path, f"* two subcircuits, each with its own gm\n.control\npre_osdi {osdi_abs}\n.endc\n"
            ".subckt ca a b\n.model gm gres g=1m\nn1 a b gm\n.ends\n"
            ".subckt cb a b\n.model gm gres g=2m\nn1 a b gm\n.ends\n"
            "v1 1 0 1\nx1 1 0 ca\nx2 1 0 ca\nx3 1 0 cb\n.control\nop\nprint i(v1)\n.endc\n.end\n")
out = ngrun(path, WORK)
check("[2] two subcircuits each holding a card `gm` (1m and 2m): each copy is its own card, "
      "i(v1) = -4 mA", near(val(out, "i(v1)"), -4e-3), out[-300:])

# ------------------------------------------------------------- [3] ---
print("[3] Enhancement-825: a Verilog-A task raised while sens perturbs a parameter")


def sf_module(task):
    return ('`include "disciplines.vams"\nmodule sf(a, b);\ninout a, b; electrical a, b;\n'
            "parameter real g = 1e-3;\nparameter real lim = 1e-3;\nanalog begin\n"
            f"  I(a,b) <+ g*V(a,b);\n  if (g > lim) {task};\nend\nendmodule\n")


for tag, task in (("fatal", '$fatal(0, "g %g over limit", g)'), ("finish", "$finish"), ("stop", "$stop")):
    write(os.path.join(WORK, f"sf_{tag}.va"), sf_module(task))
    compile_va(os.path.join(WORK, f"sf_{tag}.va"), os.path.join(WORK, f"sf_{tag}.osdi"))


def sens_run(tag, card, ctl):
    path = os.path.join(WORK, f"s_{tag}_{abs(hash(card + ctl)) % 10000}.cir")
    write(path, f"* sens {tag}\n.control\npre_osdi sf_{tag}.osdi\n.endc\nv1 1 0 1 ac 1\nr2 1 2 1k\n"
                f"n1 2 0 sfm\n.model sfm sf {card}\n.control\n{ctl}\necho AFTER-SENS\nop\nprint v(2)\n.endc\n.end\n")
    return ngrun(path, WORK)


PERT = "n1:g to 0.001000001"
out = sens_run("fatal", "g=1m", "sens v(2)\nprint n1:g")
check("[3] DC sens, $fatal on the first upward step of g (nominal g = lim): aborted, the error and "
      "the device's line name the perturbation, no sensitivity printed (it reported every one)",
      f"raised $fatal while sens perturbed {PERT}; aborting" in out
      and f"OSDI(fatal) n1: g 0.001 over limit (while sens perturbed {PERT})" in out
      and "sens simulation(s) aborted" in out and val(out, "n1:g") is None, out[-500:])
check("[3] ...the op after it runs on the netlist's g: v(2) = 0.5", near(val(out, "v(2)"), 0.5), out[-300:])

out = sens_run("fatal", "g=1m", "sens v(2) ac dec 2 1k 10k")
check("[3] AC sens, the same $fatal (raised in the setup pass, no evaluation flag): aborted",
      f"raised $fatal while sens perturbed {PERT}; aborting" in out
      and "sens simulation(s) aborted" in out, out[-500:])

out = sens_run("finish", "g=1m", "sens v(2)\nprint n1:g")
check("[3] $finish at the perturbation: sens ends there with a note, no sensitivities "
      "(it was dropped in silence)",
      f"Note: $finish requested by a Verilog-A device while sens perturbed {PERT}; sens ends there" in out
      and val(out, "n1:g") is None and near(val(out, "v(2)"), 0.5), out[-500:])

out = sens_run("stop", "g=1m", "sens v(2)\nprint n1:g")
check("[3] $stop at the perturbation: the same, and the note says sens cannot pause there",
      f"Note: $stop requested by a Verilog-A device while sens perturbed {PERT}; sens ends there "
      "(it cannot pause inside its perturbations)" in out and val(out, "n1:g") is None, out[-500:])

out = sens_run("fatal", "g=1m lim=2m", "sens v(2)\nprint n1:g")
check("[3] a perturbation inside the limit (control): sens completes, n1:g = -250",
      near(val(out, "n1:g"), -250.0, 1e-4) and "OSDI(fatal)" not in out, out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
