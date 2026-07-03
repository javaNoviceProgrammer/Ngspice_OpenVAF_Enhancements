#!/usr/bin/env python3
"""
verify_rng.py -- verify Enhancement-10's statistical / random-number system
functions ($random, $dist_*, $rdist_*) end-to-end through version11's own
openvaf-r + ngspice-46.

`rng_demo` fixes V(p,n) to a single random draw whose distribution is chosen by
the `dist` model parameter and whose stream is chosen by `seed`. Because each
draw is a pure, reproducible function of the (seed, call-site) pair (see
Enhancement-10.md), instantiating N devices with seeds 1..N and running a single
`.op` yields N independent samples of the selected distribution. For each
distribution we compare the sample mean and standard deviation against the
closed-form values, and separately check:

  * reproducibility  -- the same seed gives byte-identical results across runs,
  * independence     -- distinct seeds give distinct draws,
  * $random          -- signed 32-bit integers, ~uniform sign and magnitude.

Everything runs via a Python subprocess (a bare ngspice heredoc misbehaves in
some shells -- see the project notes); no external dependencies beyond the
standard library.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

N = 4000  # samples (instances) per distribution

# Distribution codes must match rng_demo.va.
UNIFORM, NORMAL, EXPONENTIAL, POISSON, CHI_SQUARE, STUDENT_T, ERLANG, RANDOM, \
    DIST_UNIFORM_INT, DIST_NORMAL_INT = range(10)


def compile_osdi():
    subprocess.run([OPENVAF, "rng_demo.va", "-o", "rng_demo.osdi"], cwd=HERE,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def draw_samples(dist, n=N, p1=0.0, p2=1.0, k=2, seed0=1):
    """Instantiate `n` rng_demo devices (seeds seed0..seed0+n-1) and return the
    list of V(p,n) draws from a single .op."""
    inst = [f"n{i} o{i} 0 m{i}" for i in range(n)]
    mods = [f".model m{i} rng_demo(seed={seed0 + i} dist={dist} "
            f"p1={p1} p2={p2} k={k})" for i in range(n)]
    deck = ("* rng stats\n"
            + "\n".join(inst) + "\n"
            + "\n".join(mods) + "\n"
            + ".control\npre_osdi rng_demo.osdi\nop\nprint all\n.endc\n.end\n")
    deck_path = os.path.join(HERE, "_stats.cir")
    with open(deck_path, "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", deck_path], cwd=HERE,
                         capture_output=True, text=True).stdout
    vals = {}
    for line in out.splitlines():
        m = re.match(r"o(\d+)\s*=\s*([-+0-9.eE]+)\s*$", line.strip())
        if m:
            vals[int(m.group(1))] = float(m.group(2))
    return [vals[i] for i in range(n) if i in vals]


def mean_std(xs):
    n = len(xs)
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / n
    return mu, math.sqrt(var)


def check(label, got, exp, tol, results):
    ok = abs(got - exp) <= tol
    results.append(ok)
    print(f"    {label:24s} got={got:12.4f}  expected={exp:12.4f}  "
          f"tol={tol:.4f}  {'PASS' if ok else 'FAIL'}")
    return ok


def moment_test(name, dist, exp_mean, exp_std, results, **kw):
    xs = draw_samples(dist, **kw)
    if len(xs) < 0.9 * N:
        print(f"  {name}: only got {len(xs)}/{N} samples -- FAIL")
        results.append(False)
        return
    mu, sd = mean_std(xs)
    # Sampling error of the mean ~ std/sqrt(N); allow a generous ~5 sigma band
    # plus a small absolute floor so exact-zero means don't need 0 tolerance.
    se = exp_std / math.sqrt(len(xs))
    print(f"  {name}  (n={len(xs)})")
    check("mean", mu, exp_mean, 5 * se + 0.02 * abs(exp_std), results)
    # std estimate error ~ std/sqrt(2N)
    check("std", sd, exp_std, 6 * exp_std / math.sqrt(2 * len(xs)) + 1e-3,
          results)


def main():
    compile_osdi()
    results = []

    print("Distribution moment checks:")
    # Uniform on [-2, 6): mean 2, var (b-a)^2/12 = 64/12
    moment_test("uniform[-2,6)", UNIFORM, 2.0, math.sqrt(64.0 / 12.0),
                results, p1=-2.0, p2=6.0)
    # Normal(mean=3, sd=2)
    moment_test("normal(3,2)", NORMAL, 3.0, 2.0, results, p1=3.0, p2=2.0)
    # Exponential(mean=4): std == mean
    moment_test("exponential(4)", EXPONENTIAL, 4.0, 4.0, results, p1=4.0)
    # Poisson(mean=5): var == mean
    moment_test("poisson(5)", POISSON, 5.0, math.sqrt(5.0), results, p1=5.0)
    # Chi-square(dof=4): mean k, var 2k
    moment_test("chi_square(4)", CHI_SQUARE, 4.0, math.sqrt(8.0), results, k=4)
    # Erlang(k=3, mean=6): var mean^2/k
    moment_test("erlang(k=3,mean=6)", ERLANG, 6.0, math.sqrt(36.0 / 3.0),
                results, k=3, p1=6.0)
    # Student-t(dof=5): mean 0, var k/(k-2) = 5/3 (heavy tails -> loose std)
    xs = draw_samples(STUDENT_T, k=5)
    mu, sd = mean_std(xs)
    print(f"  student_t(5)  (n={len(xs)})")
    check("mean", mu, 0.0, 0.15, results)
    check("std", sd, math.sqrt(5.0 / 3.0), 0.5, results)

    print("\n$random checks (signed 32-bit integers):")
    ri = draw_samples(RANDOM, n=2000)
    frac_neg = sum(1 for x in ri if x < 0) / len(ri)
    big = sum(1 for x in ri if abs(x) > 1e8) / len(ri)
    check("fraction negative", frac_neg, 0.5, 0.08, results)
    check("fraction |x|>1e8", big, 1.0 - 1e8 / 2.147483648e9, 0.08, results)
    all_int = all(abs(x - round(x)) < 1e-6 for x in ri)
    results.append(all_int)
    print(f"    {'all integral':24s} {'PASS' if all_int else 'FAIL'}")

    print("\n$dist_uniform integer check (inclusive [0,k], k=6 -> a fair die):")
    di = draw_samples(DIST_UNIFORM_INT, n=3000, k=6)
    faces = sorted(set(round(x) for x in di))
    in_range = faces and faces[0] >= 0 and faces[-1] <= 6
    all_int = all(abs(x - round(x)) < 1e-6 for x in di)
    mu, _ = mean_std(di)
    print(f"    observed faces: {faces}")
    results.append(bool(in_range) and all_int)
    print(f"    {'integral & in [0,6]':24s} "
          f"{'PASS' if in_range and all_int else 'FAIL'}")
    check("mean", mu, 3.0, 0.2, results)

    print("\n$dist_normal integer-rounded check (mean=k=5, sd=2):")
    dn = draw_samples(DIST_NORMAL_INT, n=4000, k=5)
    all_int = all(abs(x - round(x)) < 1e-6 for x in dn)
    mu, sd = mean_std(dn)
    results.append(all_int)
    print(f"    {'all integral':24s} {'PASS' if all_int else 'FAIL'}")
    # Rounding a N(5, 2) draw leaves the mean at 5 and inflates the variance by
    # ~1/12 (Sheppard's correction): sd ~ sqrt(4 + 1/12) ~ 2.02.
    check("mean", mu, 5.0, 0.2, results)
    check("std", sd, math.sqrt(4.0 + 1.0 / 12.0), 0.2, results)

    print("\nReproducibility & independence:")
    a = draw_samples(NORMAL, n=50, p1=0.0, p2=1.0)
    b = draw_samples(NORMAL, n=50, p1=0.0, p2=1.0)
    repro = a == b
    results.append(repro)
    print(f"    {'same seeds -> identical':24s} {'PASS' if repro else 'FAIL'}")
    distinct = len(set(round(x, 9) for x in a)) == len(a)
    results.append(distinct)
    print(f"    {'distinct seeds -> distinct':24s} "
          f"{'PASS' if distinct else 'FAIL'}")

    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
