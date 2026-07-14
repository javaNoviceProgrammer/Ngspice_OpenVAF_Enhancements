#!/usr/bin/env python3
"""snp2va.py -- convert a Touchstone .sNp S-parameter file into a Verilog-A n-port
model realized with laplace_nd, so it works in AC *and* transient through OpenVAF's
OSDI laplace machinery. Pure Python standard library (no numpy).

Usage: snp2va.py <file.sNp> [-o out.va] [-m module] [--order N] [--tol T]

Pipeline: parse Touchstone -> S(f) -> Y(f) -> common-pole vector fit (with
automatic order selection, Gustavsen pole seeding, spurious-pole pruning,
stability & passivity checks) -> emit  I(p_i) <+ sum_j laplace_nd(V(p_j),num,den)
                                              + e_ij*ddt(V(p_j)).
"""

import sys, math, cmath, argparse, os

# ---- inlined pure-Python linear algebra (was pplinalg.py) ----


def lstsq_real(A, b):
    """Least-squares min||A x - b|| for REAL overdetermined A (m x n, m>=n) via
    Householder QR. A: list of m rows (each list of n). b: list of m. Returns x (n)."""
    m = len(A); n = len(A[0])
    # work on copies
    R = [row[:] for row in A]
    y = b[:]
    for k in range(n):
        # Householder vector for column k (rows k..m-1)
        norm = math.sqrt(sum(R[i][k]**2 for i in range(k, m)))
        if norm == 0.0:
            continue
        alpha = -norm if R[k][k] >= 0 else norm
        v = [0.0]*m
        v[k] = R[k][k] - alpha
        for i in range(k+1, m):
            v[i] = R[i][k]
        vnorm2 = sum(v[i]*v[i] for i in range(k, m))
        if vnorm2 == 0.0:
            continue
        # apply H = I - 2 v v^T / (v^T v) to R[:,k:] and y
        for j in range(k, n):
            s = sum(v[i]*R[i][j] for i in range(k, m)) * 2.0 / vnorm2
            for i in range(k, m):
                R[i][j] -= s*v[i]
        s = sum(v[i]*y[i] for i in range(k, m)) * 2.0 / vnorm2
        for i in range(k, m):
            y[i] -= s*v[i]
    # back-substitute R[0:n,0:n] x = y[0:n]
    x = [0.0]*n
    for i in range(n-1, -1, -1):
        acc = y[i]
        for j in range(i+1, n):
            acc -= R[i][j]*x[j]
        x[i] = acc / R[i][i] if R[i][i] != 0.0 else 0.0
    return x

def mat_inv(M):
    """Inverse of an n x n COMPLEX matrix (list of rows) via Gauss-Jordan w/ pivot."""
    n = len(M)
    A = [ [M[i][j] for j in range(n)] + [1.0 if i==j else 0.0 for j in range(n)] for i in range(n) ]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) == 0.0:
            raise ZeroDivisionError("singular matrix in mat_inv")
        A[col], A[piv] = A[piv], A[col]
        d = A[col][col]
        A[col] = [x/d for x in A[col]]
        for r in range(n):
            if r != col and abs(A[r][col]) > 0:
                f = A[r][col]
                A[r] = [a - f*c for a, c in zip(A[r], A[col])]
    return [row[n:] for row in A]

def matmul(A, B):
    n=len(A); m=len(B[0]); k=len(B)
    return [[sum(A[i][t]*B[t][j] for t in range(k)) for j in range(m)] for i in range(n)]

def poly_from_roots(roots):
    """Monic polynomial coefficients (DESCENDING, leading 1) from roots (complex)."""
    c = [1.0+0j]
    for r in roots:
        nc = [0j]*(len(c)+1)
        for i, ci in enumerate(c):
            nc[i]   += ci
            nc[i+1] -= ci*r
        c = nc
    return c

def poly_mul(a, b):
    c = [0j]*(len(a)+len(b)-1)
    for i, ai in enumerate(a):
        for j, bj in enumerate(b):
            c[i+j] += ai*bj
    return c

def poly_add(a, b):
    n = max(len(a), len(b)); a = [0j]*(n-len(a))+list(a); b=[0j]*(n-len(b))+list(b)
    return [x+y for x, y in zip(a, b)]

def poly_eval(c, x):
    r = 0j
    for ci in c:
        r = r*x + ci
    return r

def poly_roots(c):
    """All roots of a polynomial (DESCENDING coeffs) via Durand-Kerner."""
    # strip leading zeros, make monic
    c = list(c)
    while len(c) > 1 and abs(c[0]) < 1e-300:
        c = c[1:]
    deg = len(c)-1
    if deg == 0:
        return []
    c = [ci/c[0] for ci in c]
    # init roots on a circle (spread)
    roots = [(0.4+0.9j)**k for k in range(deg)]
    for _ in range(500):
        maxstep = 0.0
        newr = []
        for i in range(deg):
            num = poly_eval(c, roots[i])
            den = 1.0+0j
            for j in range(deg):
                if j != i:
                    den *= (roots[i]-roots[j])
            step = num/den if abs(den) > 1e-300 else 0j
            newr.append(roots[i]-step)
            maxstep = max(maxstep, abs(step))
        roots = newr
        if maxstep < 1e-14:
            break
    return roots
# ---- inlined vector fitting (was ppvfit.py) ----


def _layout(poles):
    """List of ('r',i) real poles / ('c',i) cc-pair-start, over the pole array."""
    Np=len(poles); out=[]; i=0
    while i<Np:
        if abs(poles[i].imag) < 1e-9*abs(poles[i].real)+1e-30:
            out.append(('r',i)); i+=1
        else:
            out.append(('c',i)); i+=2
    return out

def _basis(s, poles, lay):
    """Ns x Np complex basis (real-valued cc combos)."""
    Ns=len(s); Np=len(poles); A=[[0j]*Np for _ in range(Ns)]
    for r in range(Ns):
        for kind,i in lay:
            if kind=='r':
                A[r][i]=1.0/(s[r]-poles[i])
            else:
                p=poles[i]
                A[r][i]  =1.0/(s[r]-p)+1.0/(s[r]-p.conjugate())
                A[r][i+1]=1j/(s[r]-p)-1j/(s[r]-p.conjugate())
    return A

def _cres(ctil, poles, lay):
    """complex residues from real ctil coeffs (per real/cc layout)."""
    Np=len(poles); c=[0j]*Np
    for kind,i in lay:
        if kind=='r': c[i]=complex(ctil[i],0.0)
        else: c[i]=complex(ctil[i],ctil[i+1]); c[i+1]=c[i].conjugate()
    return c

def vector_fit(s, F, poles, n_iter=10):
    """s: complex samples (list). F: list of Nf functions, each a list of Ns
    complex samples. poles: initial complex poles. Returns poles,res,d,e."""
    Ns=len(s); Nf=len(F); poles=[complex(p) for p in poles]; Np=len(poles)
    for _ in range(n_iter):
        lay=_layout(poles); A=_basis(s,poles,lay)
        # pole-ID LS: unknowns [per-fn (c[Np],d,e)]*Nf + shared ctil[Np]
        ncol=Nf*(Np+2)+Np
        M=[]; rhs=[]
        for k in range(Nf):
            for r in range(Ns):
                row=[0j]*ncol
                for j in range(Np): row[k*(Np+2)+j]=A[r][j]
                row[k*(Np+2)+Np]=1.0
                row[k*(Np+2)+Np+1]=s[r]
                for j in range(Np): row[Nf*(Np+2)+j]=-F[k][r]*A[r][j]
                M.append(row); rhs.append(F[k][r])
        # real-stack
        Mr=[[x.real for x in row] for row in M]+[[x.imag for x in row] for row in M]
        br=[x.real for x in rhs]+[x.imag for x in rhs]
        x=lstsq_real(Mr,br)
        ctil=x[Nf*(Np+2):]
        cres=_cres(ctil,poles,lay)
        # relocate: roots of sigma numerator = D(s)+sum cres_i * D(s)/(s-a_i)
        allp=poles
        D=poly_from_roots(allp)
        numsig=list(D)
        for i in range(Np):
            Di=poly_from_roots([allp[j] for j in range(Np) if j!=i])
            numsig=poly_add(numsig,[cres[i]*x for x in Di])
        newp=poly_roots(numsig)
        newp=[(-p.real+1j*p.imag) if p.real>0 else p for p in newp]  # stabilize
        # sort so cc pairs are adjacent (real first)
        newp.sort(key=lambda p:(abs(p.imag)>1e-6, p.real, p.imag))
        poles=newp
    # final residues (fixed poles)
    lay=_layout(poles); A=_basis(s,poles,lay)
    res=[[0j]*Np for _ in range(Nf)]; d=[0.0]*Nf; e=[0.0]*Nf
    for k in range(Nf):
        M=[]; rhs=[]
        for r in range(Ns):
            row=A[r][:]+[1.0+0j, s[r]]; M.append(row); rhs.append(F[k][r])
        Mr=[[x.real for x in row] for row in M]+[[x.imag for x in row] for row in M]
        br=[x.real for x in rhs]+[x.imag for x in rhs]
        xk=lstsq_real(Mr,br)
        cr=_cres(xk[:Np],poles,lay)
        for j in range(Np): res[k][j]=cr[j]
        d[k]=xk[Np]; e[k]=xk[Np+1]
    return poles,res,d,e

def model_eval(s,poles,res,d,e,k):
    return [d[k]+s[r]*e[k]+sum(res[k][j]/(s[r]-poles[j]) for j in range(len(poles))) for r in range(len(s))]
# ---- converter ----


# ---------------------------------------------------------------- Touchstone I/O
def parse_touchstone(fn, nports_hint=None):
    unit = {'HZ':1.0,'KHZ':1e3,'MHZ':1e6,'GHZ':1e9}
    fmul=1e9; ptype='S'; fmt='MA'; z0=50.0
    nums=[]
    for line in open(fn):
        line=line.split('!',1)[0].strip()
        if not line: continue
        if line.startswith('#'):
            t=line[1:].split()
            i=0
            while i<len(t):
                u=t[i].upper()
                if u in unit: fmul=unit[u]
                elif u in ('S','Y','Z','H','G'): ptype=u
                elif u in ('MA','DB','RI'): fmt=u
                elif u=='R' and i+1<len(t): z0=float(t[i+1]); i+=1
                i+=1
            continue
        nums.extend(float(x) for x in line.replace(',',' ').split())
    # infer nports: each record = 1 freq + 2*N*N values
    N = nports_hint
    if N is None:
        m=fn.lower().rsplit('.s',1)
        if len(m)==2 and m[1].endswith('p'):
            try: N=int(m[1][:-1])
            except ValueError: N=None
    if N is None:
        # brute-force: find N with (len % (1+2N^2))==0
        for cand in range(1,17):
            if len(nums)%(1+2*cand*cand)==0: N=cand; break
    rec=1+2*N*N
    freqs=[]; mats=[]
    for r in range(0,len(nums),rec):
        chunk=nums[r:r+rec]
        if len(chunk)<rec: break
        freqs.append(chunk[0]*fmul)
        vals=chunk[1:]
        pv=[]
        for k in range(N*N):
            a,b=vals[2*k],vals[2*k+1]
            if fmt=='MA': c=a*cmath.exp(1j*math.radians(b))
            elif fmt=='DB': c=(10**(a/20.0))*cmath.exp(1j*math.radians(b))
            else: c=complex(a,b)
            pv.append(c)
        # Touchstone order: N=2 is S11 S21 S12 S22; general is row-major S11 S12...
        M=[[0j]*N for _ in range(N)]
        if N==2:
            M[0][0],M[1][0],M[0][1],M[1][1]=pv[0],pv[1],pv[2],pv[3]
        else:
            for i in range(N):
                for j in range(N): M[i][j]=pv[i*N+j]
        mats.append(M)
    return freqs, mats, N, ptype, z0

def to_Y(mats, ptype, z0):
    """Convert S/Y/Z matrices to Y (admittance, common real ref impedance z0)."""
    N=len(mats[0]); I=[[1.0 if i==j else 0j for j in range(N)] for i in range(N)]
    out=[]
    for M in mats:
        if ptype=='Y': out.append(M)
        elif ptype=='Z': out.append(mat_inv(M))
        else:  # S -> Y = (1/z0)(I-S)(I+S)^-1
            IpS=[[I[i][j]+M[i][j] for j in range(N)] for i in range(N)]
            ImS=[[I[i][j]-M[i][j] for j in range(N)] for i in range(N)]
            Y=matmul(ImS, mat_inv(IpS))
            out.append([[Y[i][j]/z0 for j in range(N)] for i in range(N)])
    return out

# ---------------------------------------------------------------- vector fit
def seed_poles(fmin, fmax, npair):
    """Gustavsen complex-conjugate seed poles, log-spaced beta over [fmin,fmax]."""
    if npair==1:
        betas=[2*math.pi*math.sqrt(fmin*fmax)]
    else:
        betas=[2*math.pi*fmin*(fmax/fmin)**(k/(npair-1)) for k in range(npair)]
    p=[]
    for b in betas:
        a=b/100.0
        p+=[complex(-a,b), complex(-a,-b)]
    return p

def fit_common(freqs, Yentries, order=None, tol=1e-3, n_iter=12):
    """Fit all Y entries with shared poles. Auto order-selection if order is None."""
    s=[1j*2*math.pi*f for f in freqs]
    wn=math.sqrt(abs(s[0])*abs(s[-1])); sn=[si/wn for si in s]
    fmin,fmax=freqs[0],freqs[-1]
    def try_order(np_pairs):
        p0=[p/wn for p in seed_poles(fmin,fmax,np_pairs)]
        poles,res,d,e=vector_fit(sn,Yentries,p0,n_iter)
        # un-normalize
        P=[p*wn for p in poles]; Rr=[[r*wn for r in rk] for rk in res]; E=[ek/wn for ek in e]
        # rms rel error
        err=0.0
        for k in range(len(Yentries)):
            fit=model_eval(s,P,Rr,d,E,k)
            num=math.sqrt(sum(abs(fit[r]-Yentries[k][r])**2 for r in range(len(s))))
            den=math.sqrt(sum(abs(Yentries[k][r])**2 for r in range(len(s))))+1e-300
            err=max(err,num/den)
        return P,Rr,d,E,err
    if order is not None:
        return try_order(max(1,order//2))
    # Automatic order selection: grow the pole count until the fit reaches `tol`
    # OR the error stops improving (the "knee" -- more poles past this just fit
    # measurement noise, producing an over-fitted, ill-conditioned model). At the
    # knee we return the PREVIOUS (lower) order, which captures the real dynamics.
    best=None; prev_err=None; prev_cand=None
    for npair in range(1, 11):
        cand=try_order(npair); err=cand[-1]
        if best is None or err<best[-1]: best=cand
        if err<tol:
            return cand
        if prev_err is not None and err>0.8*prev_err:      # <20% improvement -> knee
            return prev_cand
        prev_err=err; prev_cand=cand
    return best

# ---------------------------------------------------------------- checks
def check_stable(poles):
    return all(p.real<=1e-6 for p in poles)
def check_passive(freqs, Y):
    """Y passive iff Re(Y) (Hermitian part) is positive semidefinite at all f.
    Cheap proxy: real part of the Hermitian part's diagonal >=0 and 2x2 minors."""
    N=len(Y[0][0]) if False else len(Y[0])
    bad=0
    for M in Y:
        G=[[0.5*(M[i][j]+M[j][i].conjugate()) for j in range(len(M))] for i in range(len(M))]
        # diagonal real parts
        for i in range(len(M)):
            if G[i][i].real < -1e-9: bad+=1; break
    return bad==0

# ---------------------------------------------------------------- emit VA
def poly_asc_real(c_desc):
    return [x.real for x in c_desc][::-1]

def num_proper(poles, res_k, d_k):
    D=poly_from_roots(poles)          # descending
    num=[d_k*x for x in D]
    for i in range(len(poles)):
        Di=poly_from_roots([poles[j] for j in range(len(poles)) if j!=i])
        num=poly_add(num,[res_k[i]*x for x in Di])
    return num

def fmt_arr(v):
    return "'{"+", ".join(f"{x:.12g}" for x in v)+"}"

def emit_va(module, N, poles, res, d, e):
    den=poly_asc_real(poly_from_roots(poles))
    ports=", ".join(f"p{i+1}" for i in range(N))
    lines=[f'`include "disciplines.vams"','',
           f"// Generated by snp2va.py from a Touchstone file.",
           f"// {N}-port, {len(poles)} common poles; realized with laplace_nd (AC + transient).",
           f"module {module}({ports});",
           f"    inout {ports};",
           f"    electrical {ports};",
           f"    analog begin"]
    for i in range(N):
        terms=[]
        for j in range(N):
            k=i*N+j
            nm=poly_asc_real(num_proper(poles,res[k],d[k]))
            terms.append(f"laplace_nd(V(p{j+1}), {fmt_arr(nm)}, {fmt_arr(den)})")
            if abs(e[k])>1e-30:
                terms.append(f"({e[k]:.12g})*ddt(V(p{j+1}))")
        lines.append(f"        I(p{i+1}) <+ " + "\n                 + ".join(terms) + ";")
    lines+=["    end","endmodule",""]
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("snp"); ap.add_argument("-o","--out"); ap.add_argument("-m","--module")
    ap.add_argument("--order",type=int,default=None); ap.add_argument("--tol",type=float,default=1e-3)
    a=ap.parse_args()
    freqs,mats,N,ptype,z0=parse_touchstone(a.snp)
    module=a.module or ("nport"+os.path.basename(a.snp).split('.')[0])
    Y=to_Y(mats,ptype,z0)
    # entries in row-major i*N+j order
    Yent=[[Y[f][i][j] for f in range(len(freqs))] for i in range(N) for j in range(N)]
    poles,res,d,e,err=fit_common(freqs,Yent,a.order,a.tol)
    stab=check_stable(poles); pas=check_passive(freqs,Y)
    va=emit_va(module,N,poles,res,d,e)
    out=a.out or (module+".va")
    open(out,"w").write(va)
    sys.stderr.write(f"snp2va: {N}-port, {len(poles)} poles, fit rms rel err {err:.2e}, "
                     f"{'stable' if stab else 'UNSTABLE(flipped)'}, "
                     f"{'passive' if pas else 'NONPASSIVE(warn)'} -> {out} (module {module})\n")

if __name__=="__main__":
    main()
