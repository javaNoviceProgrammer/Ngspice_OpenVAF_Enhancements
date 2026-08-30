use hir::builtin::{
    AC_STIMT_NAME, AC_STIM_NAME_MAG_PHASE, AC_STIM_UNIT, FLICKER_NOISE_NAME,
    NOISE_TABLE_FILE, NOISE_TABLE_FILE_NAME, NOISE_TABLE_INLINE, NOISE_TABLE_INLINE_NAME,
    WHITE_NOISE_NAME,
};
use hir::signatures::{
    ABSDELAY_MAX, ABS_INT, ABS_REAL, BOOL_EQ, DDX_POT, IDTMOD_IC, IDTMOD_IC_MODULUS,
    IDTMOD_IC_MODULUS_OFFSET, IDTMOD_IC_MODULUS_OFFSET_NATURE, IDTMOD_IC_MODULUS_OFFSET_TOL,
    IDTMOD_NO_IC, IDT_IC, IDT_IC_ASSERT, IDT_IC_ASSERT_NATURE, IDT_IC_ASSERT_TOL, IDT_NO_IC,
    INT_EQ, INT_OP, LAST_CROSSING_DIRECTION, LAST_CROSSING_NO_DIRECTION, LIMIT_BUILTIN_FUNCTION,
    MAX_INT, MAX_REAL, NATURE_ACCESS_BRANCH,
    NATURE_ACCESS_NODES, NATURE_ACCESS_NODE_GND, NATURE_ACCESS_PORT_FLOW, REAL_EQ, REAL_OP,
    SIMPARAM_DEFAULT, SIMPARAM_NO_DEFAULT, SLEW_NEG_MAX, SLEW_NO_MAX, SLEW_POS_MAX, STR_EQ, STR_REL,
    TRANSITION_DELAY, TRANSITION_DELAY_RISET, TRANSITION_DELAY_RISET_FALLT,
    TRANSITION_DELAY_RISET_FALLT_TOL, TRANSITION_NO_ARGS,
};
use hir::{Body, BodyRef, BuiltIn, CompilationDB, Expr, ExprId, Literal, /*ParamSysFun,*/ Ref, ResolvedFun, Type};
use mir::builder::InstBuilder;
use mir::{InstructionData, Opcode, Value, FALSE, F_ONE, F_ZERO, GRAVESTONE, INFINITY, TRUE, ZERO};
use stdx::iter::zip;
use syntax::ast::{BinaryOp, UnaryOp};

use crate::body::BodyLoweringCtx;
use crate::fmt::DisplayKind;
use crate::{
    CallBackKind, CurrentKind, FileOp, IdtKind, ImplicitEquationKind, NoiseTable, ParamKind,
    PlaceKind, PrintDst, RetFlag, RngFun, ScanKind,
};

/// Builds the natural-cubic-spline "moment matrix" `L` (n×n) for an ascending `grid`, such that the
/// vector of second derivatives (moments) `M = L · y` for any data vector `y` sampled on the grid.
///
/// A natural cubic spline pins `M[0] = M[n-1] = 0` and solves a tridiagonal system for the interior
/// moments; because that system is linear in `y` and depends only on the grid spacings, `M` is a
/// fixed linear operator on `y`. Precomputing `L` at compile time (here) lets the runtime evaluation
/// express each moment as a constant-weighted sum of the (possibly runtime) grid values — so the
/// whole spline lowers to differentiable MIR with no runtime linear solve. Returns an all-zero
/// matrix for `n < 3` (callers fall back to linear interpolation there).
fn natural_cubic_spline_moment_matrix(grid: &[f64]) -> Vec<Vec<f64>> {
    let n = grid.len();
    let mut l = vec![vec![0.0f64; n]; n];
    if n < 3 {
        return l;
    }
    let h: Vec<f64> = (0..n - 1).map(|i| grid[i + 1] - grid[i]).collect();
    let m = n - 2; // number of interior unknowns M[1..=n-2]

    // Interior tridiagonal system  T · m_interior = R · y.
    let mut t = vec![vec![0.0f64; m]; m];
    let mut r = vec![vec![0.0f64; n]; m];
    for row in 0..m {
        let k = row + 1; // full-grid index of this interior moment
        t[row][row] = 2.0 * (h[k - 1] + h[k]);
        if row >= 1 {
            t[row][row - 1] = h[k - 1];
        }
        if row + 1 < m {
            t[row][row + 1] = h[k];
        }
        r[row][k - 1] += 6.0 / h[k - 1];
        r[row][k] += -6.0 * (1.0 / h[k - 1] + 1.0 / h[k]);
        r[row][k + 1] += 6.0 / h[k];
    }

    // Invert T (small, dense) via Gauss–Jordan, then L_interior = T⁻¹ · R.
    let mut a = t;
    let mut inv = vec![vec![0.0f64; m]; m];
    for i in 0..m {
        inv[i][i] = 1.0;
    }
    for col in 0..m {
        // partial pivot
        let mut piv = col;
        for row in col + 1..m {
            if a[row][col].abs() > a[piv][col].abs() {
                piv = row;
            }
        }
        a.swap(col, piv);
        inv.swap(col, piv);
        let d = a[col][col];
        if d == 0.0 {
            return vec![vec![0.0f64; n]; n]; // singular (degenerate grid) -> caller falls back
        }
        for j in 0..m {
            a[col][j] /= d;
            inv[col][j] /= d;
        }
        for row in 0..m {
            if row == col {
                continue;
            }
            let f = a[row][col];
            if f == 0.0 {
                continue;
            }
            for j in 0..m {
                a[row][j] -= f * a[col][j];
                inv[row][j] -= f * inv[col][j];
            }
        }
    }
    // L rows 1..=n-2 = (T⁻¹ · R); rows 0 and n-1 stay zero (natural boundary).
    for row in 0..m {
        for col in 0..n {
            let mut s = 0.0;
            for kk in 0..m {
                s += inv[row][kk] * r[kk][col];
            }
            l[row + 1][col] = s;
        }
    }
    l
}

impl BodyLoweringCtx<'_, '_, '_> {
    pub fn lower_expr(&mut self, expr: ExprId) -> Value {
        let old_loc = self.ctx.get_srcloc();
        self.ctx.set_srcloc(mir::SourceLoc::new(u32::from(expr) as i32 + 1));

        // A dynamic-index array read `c[i]` / `m[i][j]` (non-constant indices) has no single
        // backing variable; it lowers to a runtime select over the array's element variables.
        // Enhancement-405: the same runtime select chain over a PARAMETER array's elements.
        if let Some((elems, dims, indices)) = self.body.dynamic_param_index(expr) {
            let mut res = self.lower_dynamic_param_index_read(&elems, &dims, &indices);
            if let Some((src, dst)) = self.body.needs_cast(expr) {
                res = self.ctx.insert_cast(res, &src, dst);
            }
            self.ctx.set_srcloc(old_loc);
            return res;
        }

        if let Some((elems, dims, indices)) = self.body.dynamic_index(expr) {
            let mut res = self.lower_dynamic_index_read(&elems, &dims, &indices);
            if let Some((src, dst)) = self.body.needs_cast(expr) {
                res = self.ctx.insert_cast(res, &src, dst);
            }
            self.ctx.set_srcloc(old_loc);
            return res;
        }

        let mut res = match self.body.get_expr(expr) {
            // Enhancement-328: unreachable here -- the `dynamic_index()` short-circuit
            // above already returned for exactly these expressions. The arm exists so
            // that `Expr` can carry the shape for OTHER `get_expr` callers (which merely
            // probe an expression and used to panic on it) while keeping this match
            // exhaustive.
            Expr::DynIndexRead => unreachable!(
                "dynamic-index array read must be lowered by the short-circuit above"
            ),
            Expr::Read(Ref::Variable(var)) => self.ctx.read_variable(var),
            Expr::Read(Ref::ParamSysFun(param)) => {
                self.ctx.use_param(ParamKind::ParamSysFun(param))
            }
            Expr::Read(Ref::Parameter(param)) => self.ctx.use_param(ParamKind::Param(param)),
            Expr::Read(Ref::FunctionReturn(fun)) => {
                self.ctx.use_place(PlaceKind::FunctionReturn(fun))
            }
            Expr::Read(Ref::FunctionArg(fun)) => self.ctx.use_place(PlaceKind::FunctionArg(fun)),
            Expr::Read(Ref::NatureAttr(attr)) => self.lower_body(attr.value(self.ctx.db), 0),
            Expr::BinaryOp { lhs, rhs, op } => self.lower_bin_op(expr, lhs, rhs, op),
            Expr::UnaryOp { expr: arg, op } => self.lower_unary_op(expr, arg, op),
            Expr::Select { cond, then_val, else_val } => {
                let cond = self.lower_expr(cond);
                let (then_src, else_src) = self.lower_cond_with(cond, |mut ctx, then| {
                    let expr = if then { then_val } else { else_val };
                    ctx.lower_expr(expr)
                });

                self.ctx.ins().phi(&[then_src, else_src])
            }
            Expr::Call { args, fun } => match fun {
                ResolvedFun::User { func, limit } => self.lower_user_fun(func, limit, args),
                ResolvedFun::BuiltIn(builtin) => self.lower_builtin(expr, builtin, args),
            },
            Expr::Array(vals) => self.lower_array(expr, vals),
            // Enhancement-34: a `{...}` concatenation in scalar position is a STRING
            // concatenation (numeric concats are array-valued and consumed element-wise
            // by their contexts via `lower_array_elems`, never reaching this path).
            Expr::Concat { rep, elems } => {
                debug_assert!(matches!(self.body.expr_type(expr), Type::String));
                self.lower_string_concat(rep, elems)
            }
            Expr::Literal(lit) => match *lit {
                Literal::String(ref str) => self.ctx.sconst(str),
                Literal::Int(val) => self.ctx.iconst(val),
                Literal::Float(val) => self.ctx.fconst(val.into()),
                Literal::Inf => {
                    self.ctx.set_srcloc(old_loc);
                    match self.body.expr_type(expr) {
                        Type::Real => return INFINITY,
                        Type::Integer => return self.ctx.iconst(i32::MAX),
                        _ => unreachable!(),
                    }
                }
            },
        };

        if let Some((src, dst)) = self.body.needs_cast(expr) {
            res = self.ctx.insert_cast(res, &src, dst)
        };
        self.ctx.set_srcloc(old_loc);
        res
    }

    fn lower_unary_op(&mut self, expr: ExprId, arg: ExprId, op: UnaryOp) -> Value {
        let is_inf = self.body.as_literal(arg) == Some(&Literal::Inf);
        let arg_ = self.lower_expr(arg);
        match op {
            // Enhancement-37: `~x` is BITWISE not (`-x - 1`), not arithmetic negation.
            // It was lowered as `ineg` (`-x`), so `~12` gave -12 instead of -13.
            UnaryOp::BitNegate => self.ctx.ins().inot(arg_),
            UnaryOp::Not => self.ctx.ins().bnot(arg_),
            UnaryOp::Neg => {
                // Special case INFINITY
                if is_inf {
                    match self.body.expr_type(arg) {
                        Type::Real => return self.ctx.fconst(f64::NEG_INFINITY),
                        Type::Integer => return self.ctx.iconst(i32::MIN),
                        ty => unreachable!("{ty:?}"),
                    }
                }
                match self.body.get_call_signature(expr) {
                    REAL_OP => self.ctx.ins().fneg(arg_),
                    INT_OP => self.ctx.ins().ineg(arg_),
                    _ => unreachable!(),
                }
            }
            UnaryOp::Identity => arg_,
        }
    }

    fn lower_array(&mut self, _expr: ExprId, _args: &[ExprId]) -> Value {
        // Enhancement-33: array expressions never reach the generic scalar lowering path.
        // Every context that accepts an array value consumes its *elements* directly —
        // aggregate assignment (E-14), `laplace_*`/`zi_*` coefficient args (E-4/E-31),
        // `$table_model` data (E-16), whole-array function args (E-18/E-33) and `case`
        // discriminants/items (E-33) all go through `lower_array_elems` or their own
        // element-wise lowering, and type inference rejects array values everywhere else
        // (there is no first-class array `Value` in the MIR).
        unreachable!("array expression in scalar value position (rejected by inference)")
    }

    /// Computes the runtime *flat* element position of a dynamic array access from its per-dimension
    /// indices, matching `BusDecl::index_tuples` ordering: `flat = Σ_k pos_k · stride_k`, where
    /// `pos_k` is the declaration-order position within dimension `k` (`idx-msb` ascending,
    /// `msb-idx` descending) and `stride_k` is the product of the sizes of the later dimensions.
    pub(crate) fn lower_flat_array_index(&mut self, dims: &[(i32, i32)], indices: &[ExprId]) -> Value {
        let n = dims.len();
        let sizes: Vec<i32> = dims.iter().map(|&(m, l)| (m - l).abs() + 1).collect();
        let mut strides = vec![1i32; n];
        for k in (0..n.saturating_sub(1)).rev() {
            strides[k] = strides[k + 1] * sizes[k + 1];
        }
        let mut flat: Option<Value> = None;
        for k in 0..n {
            let (msb, lsb) = dims[k];
            let idx = self.lower_expr(indices[k]);
            // pos_k: steps from msb toward lsb
            let pos = if msb <= lsb {
                let m = self.ctx.iconst(msb);
                self.ctx.ins().binary1(Opcode::Isub, idx, m)
            } else {
                let m = self.ctx.iconst(msb);
                self.ctx.ins().binary1(Opcode::Isub, m, idx)
            };
            let term = if strides[k] == 1 {
                pos
            } else {
                let s = self.ctx.iconst(strides[k]);
                self.ctx.ins().binary1(Opcode::Imul, pos, s)
            };
            flat = Some(match flat {
                None => term,
                Some(acc) => self.ctx.ins().binary1(Opcode::Iadd, acc, term),
            });
        }
        flat.unwrap_or_else(|| self.ctx.iconst(0))
    }

    /// Enhancement-505: clamp a distribution argument that cannot be negative.
    ///
    /// hir_ty refuses an out-of-domain CONSTANT ("the standard deviation must not
    /// be negative"), but only a literal or a localparam; the ordinary case is a
    /// `parameter` overridden from the deck, which the compiler cannot refuse.
    /// What got through was not merely odd, it was impossible:
    /// `$rdist_normal(seed, 0, -1)` returned exactly the NEGATION of the `+1`
    /// deviate -- the sign was used, not validated -- and
    /// `$rdist_exponential(seed, -1)` returned a NEGATIVE deviate, which the
    /// exponential distribution has no values of.
    ///
    /// Zero is the projection onto the domain and is a distribution the RNG can
    /// actually produce: a zero standard deviation is the mean with certainty, a
    /// zero exponential/poisson mean is zero with certainty.
    fn clamp_non_negative(&mut self, v: Value) -> Value {
        let zero = self.ctx.fconst(0.0);
        let ok = self.ctx.ins().fgt(v, zero); // false for 0, negatives and NaN
        self.ctx.make_select(ok, |_, branch| if branch { v } else { zero })
    }

    /// Enhancement-505: `$rdist_uniform`'s bounds, ordered. The LRM requires the
    /// start below the end and hir_ty refuses a constant pair that is not; from
    /// the deck an inverted pair sampled an inverted range in silence. The high
    /// bound is raised to the low one, which degenerates the distribution to a
    /// point rather than inventing the user's intent by swapping them.
    fn clamp_upper_bound(&mut self, lo: Value, hi: Value) -> Value {
        let ok = self.ctx.ins().fgt(hi, lo);
        self.ctx.make_select(ok, |_, branch| if branch { hi } else { lo })
    }

    /// Enhancement-504: a noise POWER the model supplies must not be negative.
    ///
    /// A power is a variance and cannot be negative; hir_ty refuses one it can
    /// SEE, but only a literal or a localparam -- the ordinary case is a
    /// `parameter` overridden from the deck, which the compiler cannot refuse.
    /// What reached the simulator then was `sqrt(fabs(pwr))`, so
    /// `white_noise(-1e-20)` produced noise BIT-IDENTICAL to `white_noise(1e-20)`
    /// and the sign was simply gone.
    ///
    /// Clamped here, at the USER's argument, and deliberately not in ngspice:
    /// the power that reaches osdinoise.c has already had the contribution
    /// factor folded into it as `fac*|fac|`, and Enhancement-42 uses that SIGN
    /// to sum same-named sources coherently. Rejecting a negative there would
    /// break correlated noise; rejecting it here cannot, because this runs
    /// before the fold.
    fn lower_noise_power(&mut self, expr: ExprId) -> Value {
        let pwr = self.lower_expr(expr);
        let zero = self.ctx.fconst(0.0);
        let ok = self.ctx.ins().fgt(pwr, zero); // false for 0, negatives and NaN
        self.ctx.make_select(ok, |_, branch| if branch { pwr } else { zero })
    }

    /// Enhancement-506: `flicker_noise(pwr, exp)` has TWO arguments and only the
    /// first was guarded.
    ///
    /// `hir_ty` validates `args[0]` alone (`require_non_negative`, the noise
    /// power) and Enhancement-504's `lower_noise_power` above clamps that same
    /// argument at run time. The EXPONENT was checked nowhere, at either time, so
    /// a NaN reaching it -- `flicker_noise(1e-18, sqrt(p))` with a deck-set
    /// negative `p`, the ordinary route -- made `pwr/f^exp` NaN at every
    /// frequency and the device's whole contribution NaN with it.
    ///
    /// A noise contribution cannot fail to converge the way a value contribution
    /// does: `sqrt(p)` in a `V(o) <+` aborts the operating point loudly, but the
    /// same NaN in a noise source just prints `onoise_total = nan` and exits 0.
    /// That is why this one went unnoticed while its value-path twin did not.
    ///
    /// Only NaN is refused. Every finite exponent is meaningful (0 is white
    /// noise, negative shapes the other way), and both infinities saturate
    /// `f^-exp` to 0 or +inf per frequency rather than poisoning the spectrum.
    /// The projection follows `lower_noise_power` exactly -- an unusable spec
    /// makes the SOURCE INERT rather than the answer wrong -- so that the two
    /// arguments of one builtin cannot disagree about what a bad value means.
    ///
    /// BOTH arguments have to be neutralised, not just the power: the runtime
    /// evaluates `pwr / f**exp`, and `0 / f**NaN` is still NaN. Zeroing the power
    /// alone left the spectrum exactly as poisoned as before -- the fix has to
    /// reach the argument that is actually unusable.
    fn guard_flicker_args(&mut self, pwr: Value, exp: Value) -> (Value, Value) {
        let zero = self.ctx.fconst(0.0);
        let ok = self.ctx.ins().feq(exp, exp); // false only for NaN
        let pwr = self.ctx.make_select(ok, |_, branch| if branch { pwr } else { zero });
        let exp = self.ctx.make_select(ok, |_, branch| if branch { exp } else { zero });
        (pwr, exp)
    }

    /// Lowers a dynamic-index array read `c[i]` / `m[i][j]` to a runtime select chain over the
    /// element variables: `elems[0]` is the default and each `elems[k]` is chosen when the flat
    /// runtime position equals `k`.
    ///
    /// Enhancement-489: an index that matches no `k` therefore reads `elems[0]`, and that
    /// is DELIBERATE and load-bearing, not an accident of how the chain is built. A select
    /// chain has no pointer arithmetic, so an out-of-range index cannot read out of bounds
    /// at any value -- which is the whole reason the read is lowered this way rather than
    /// as an indexed load.
    ///
    /// A CONSTANT out-of-range index never gets here: a literal, a localparam and a derived
    /// constant expression are all rejected up front ("bus bit-select index out of range").
    /// What reaches this code is a value the compiler cannot pin down -- an overridable
    /// parameter, or a variable computed while solving -- and for those the project's rule
    /// is the one Enhancement-455 states for the domain guards: a run-time value out of
    /// range is the model's own business, because a parameter may be overridden and a
    /// variable may pass through any value on its way to the solution.
    ///
    /// Returning NaN instead was considered and rejected. It would turn a silent wrong
    /// element into a loud failure for the parameter case, where the index is fixed at
    /// setup -- but the variable case shares this lowering, and there an index can be
    /// transiently out of range mid-solve, so a NaN would poison the iteration and break
    /// models that converge today. Splitting the two would leave the same operation judged
    /// by two different rules, which is the drift this project keeps having to undo.
    /// Enhancement-405: parameter-array twin of [`Self::lower_dynamic_index_read`]. A
    /// parameter reads as an ordinary MIR value, so the select chain is identical apart
    /// from how each element is obtained.
    fn lower_dynamic_param_index_read(
        &mut self,
        elems: &[hir::Parameter],
        dims: &[(i32, i32)],
        indices: &[ExprId],
    ) -> Value {
        let flat = self.lower_flat_array_index(dims, indices);
        let mut res = self.ctx.use_param(ParamKind::Param(elems[0]));
        for (k, &param) in elems.iter().enumerate().skip(1) {
            let target = self.ctx.iconst(k as i32);
            let is_k = self.ctx.ins().binary1(Opcode::Ieq, flat, target);
            let elem_val = self.ctx.use_param(ParamKind::Param(param));
            res = self.ctx.make_select(is_k, move |_ctx, branch| if branch { elem_val } else { res });
        }
        res
    }

    fn lower_dynamic_index_read(
        &mut self,
        elems: &[hir::Variable],
        dims: &[(i32, i32)],
        indices: &[ExprId],
    ) -> Value {
        let flat = self.lower_flat_array_index(dims, indices);
        let mut res = self.ctx.read_variable(elems[0]);
        for (k, &var) in elems.iter().enumerate().skip(1) {
            let target = self.ctx.iconst(k as i32);
            let is_k = self.ctx.ins().binary1(Opcode::Ieq, flat, target);
            let elem_val = self.ctx.read_variable(var);
            res = self.ctx.make_select(is_k, move |_ctx, branch| if branch { elem_val } else { res });
        }
        res
    }
    fn lower_bin_op(&mut self, expr: ExprId, lhs: ExprId, rhs: ExprId, op: BinaryOp) -> Value {
        let signature = self.body.get_call_signature(expr);
        // Enhancement-106: string relational comparison. `==`/`!=` already had
        // a string signature (STR_EQ); the relational operators now accept two
        // strings too and lower to `strcmp(a, b) <op> 0` (lexicographic). The
        // op guard is required: a `Signature` is only an index into the
        // operator's own signature set, so `STR_REL` (index 2) also names, e.g.,
        // real equality's REAL_EQ -- only the relational ops use index 2 for a
        // string.
        let str_rel_op = match op {
            BinaryOp::LesserTest if signature == STR_REL => Some(Opcode::Ilt),
            BinaryOp::LesserEqualTest if signature == STR_REL => Some(Opcode::Ile),
            BinaryOp::GreaterTest if signature == STR_REL => Some(Opcode::Igt),
            BinaryOp::GreaterEqualTest if signature == STR_REL => Some(Opcode::Ige),
            _ => None,
        };
        if let Some(cmp_op) = str_rel_op {
            let lhs_ = self.lower_expr(lhs);
            let rhs_ = self.lower_expr(rhs);
            let cmp = self.ctx.call1(CallBackKind::StrCmp, &[lhs_, rhs_]);
            let zero = self.ctx.iconst(0);
            return self.ctx.ins().binary1(cmp_op, cmp, zero);
        }
        let op = match op {
            BinaryOp::BooleanOr => {
                // lhs || rhs if lhs { true } else { rhs }
                return self.lower_select(lhs, |_| TRUE, |mut s| s.lower_expr(rhs));
            }

            BinaryOp::BooleanAnd => {
                // lhs && rhs if lhs { rhs } else { false }
                return self.lower_select(lhs, |mut s| s.lower_expr(rhs), |_| FALSE);
            }

            BinaryOp::EqualityTest => match_signature! {
                signature:
                    BOOL_EQ => Opcode::Beq,
                    INT_EQ  => Opcode::Ieq,
                    REAL_EQ => Opcode::Feq,
                    STR_EQ  => Opcode::Seq
            },
            BinaryOp::NegatedEqualityTest => match_signature! {
                signature:
                    BOOL_EQ => Opcode::Bne,
                    INT_EQ  => Opcode::Ine,
                    REAL_EQ => Opcode::Fne,
                    STR_EQ  => Opcode::Sne
            },
            BinaryOp::GreaterEqualTest => {
                match_signature!(signature: INT_OP => Opcode::Ige, REAL_OP => Opcode::Fge)
            }
            BinaryOp::GreaterTest => {
                match_signature!(signature: INT_OP => Opcode::Igt, REAL_OP => Opcode::Fgt)
            }
            BinaryOp::LesserEqualTest => {
                match_signature!(signature: INT_OP => Opcode::Ile, REAL_OP => Opcode::Fle)
            }
            BinaryOp::LesserTest => {
                match_signature!(signature: INT_OP => Opcode::Ilt, REAL_OP => Opcode::Flt)
            }
            BinaryOp::Addition => {
                match_signature!(signature: INT_OP => Opcode::Iadd, REAL_OP => Opcode::Fadd)
            }
            BinaryOp::Subtraction => {
                match_signature!(signature: INT_OP => Opcode::Isub, REAL_OP => Opcode::Fsub)
            }
            BinaryOp::Multiplication => {
                match_signature!(signature: INT_OP => Opcode::Imul, REAL_OP => Opcode::Fmul)
            }
            BinaryOp::Division => {
                match_signature!(signature: INT_OP => Opcode::Idiv, REAL_OP => Opcode::Fdiv)
            }
            BinaryOp::Remainder => {
                match_signature!(signature: INT_OP => Opcode::Irem, REAL_OP => Opcode::Frem)
            }
            // Enhancement-420: two integer operands make `**` an integer expression
            // (IEEE 1364-2005 5.1.5). See `lower_int_pow`.
            BinaryOp::Power if signature == INT_OP => {
                let base = self.lower_expr(lhs);
                let exp = self.lower_expr(rhs);
                return self.lower_int_pow(base, exp);
            }
            // Enhancement-509: `**` reaches the same two domain holes as `pow`,
            // through this separate path (Enhancement-489's lesson: an operator
            // spelling needs its own guard).
            BinaryOp::Power => {
                let base = self.lower_expr(lhs);
                let exp = self.lower_expr(rhs);
                let base = self.guard_pow_base(lhs, rhs, base, exp);
                return self.ctx.ins().pow(base, exp);
            }

            BinaryOp::LeftShift => Opcode::Ishl,
            BinaryOp::RightShift => Opcode::Ishr,
            // `<<<` behaves exactly like `<<` per the LRM (left shift always zero-fills);
            // only right shift distinguishes logical (`>>`, zero-fill) from arithmetic
            // (`>>>`, sign-extending) fill of vacated bits.
            BinaryOp::ArithmeticLeftShift => Opcode::Ishl,
            BinaryOp::ArithmeticRightShift => Opcode::Iashr,

            BinaryOp::BitwiseXor => Opcode::Ixor,
            BinaryOp::BitwiseEq => {
                let lhs = self.lower_expr(lhs);
                let rhs = self.lower_expr(rhs);
                let res = self.ctx.ins().ixor(lhs, rhs);
                return self.ctx.ins().inot(res);
            }
            BinaryOp::BitwiseOr => Opcode::Ior,
            BinaryOp::BitwiseAnd => Opcode::Iand,
        };

        let lhs_ = self.lower_expr(lhs);
        let rhs_ = self.lower_expr(rhs);
        self.ctx.ins().binary1(op, lhs_, rhs_)
    }

    /// Enhancement-420: `base ** exp` with two INTEGER operands, per IEEE
    /// 1364-2005 Table 5-6.
    ///
    /// `**` used to be typed real unconditionally, so both operands were promoted
    /// to float, `llvm.pow.f64` ran, and the real result was rounded back away
    /// from zero wherever an integer was wanted. For a NEGATIVE exponent that is
    /// wrong every time the base is not 1 or -1: the true value is a fraction, the
    /// standard says the integer result is 0, and rounding away from zero gave
    /// `2 ** -1` = 1 -- off by a whole unit, silently, from source that compiled
    /// clean.
    ///
    /// Table 5-6 for a negative exponent: 1 when the base is 1; 1 or -1 for a base
    /// of -1 as the exponent is even or odd; 0 otherwise. A base of 0 is `'x`
    /// there, which is 0 in an integer context -- the same answer the `otherwise`
    /// arm already gives.
    ///
    /// Written branchless on purpose. A phi would be correct too, but every
    /// operand here is a comparison or a multiply by 0/1, so the constant folder
    /// collapses the whole thing when the operands are literals -- and, more
    /// importantly, the float `pow` never sees the negative exponent at all. That
    /// matters: `0 ** -1` is infinity in floating point, and `llvm.lround` of an
    /// infinity is undefined. Clamping the exponent the float path sees keeps the
    /// dead branch harmless rather than merely unused.
    fn lower_int_pow(&mut self, base: Value, exp: Value) -> Value {
        let zero = self.ctx.iconst(0);
        let one = self.ctx.iconst(1);
        let two = self.ctx.iconst(2);
        let minus_one = self.ctx.iconst(-1);

        // 1 when the exponent is negative, 0 otherwise
        let is_neg = self.ctx.ins().binary1(Opcode::Ilt, exp, zero);
        let neg = self.ctx.ins().bicast(is_neg);
        let not_neg = self.ctx.ins().binary1(Opcode::Isub, one, neg);

        // non-negative exponent: the float path, unchanged in value. The exponent
        // is forced to 0 when it is negative so `pow` cannot produce an infinity
        // that `ficast` would then have to round.
        let safe_exp = self.ctx.ins().binary1(Opcode::Imul, exp, not_neg);
        let fbase = self.ctx.ins().ifcast(base);
        let fexp = self.ctx.ins().ifcast(safe_exp);
        let fpow = self.ctx.ins().binary1(Opcode::Pow, fbase, fexp);
        let pos_res = self.ctx.ins().ficast(fpow);

        // negative exponent: Table 5-6. The two base tests are mutually exclusive,
        // so summing the two contributions is a select.
        let base_is_one = self.ctx.ins().binary1(Opcode::Ieq, base, one);
        let base_is_one = self.ctx.ins().bicast(base_is_one);
        let base_is_m1 = self.ctx.ins().binary1(Opcode::Ieq, base, minus_one);
        let base_is_m1 = self.ctx.ins().bicast(base_is_m1);
        // `exp & 1` is 1 for an odd exponent of either sign in two's complement
        let odd = self.ctx.ins().binary1(Opcode::Iand, exp, one);
        // odd -> -1, even -> +1
        let m1_res = self.ctx.ins().binary1(Opcode::Imul, two, odd);
        let m1_res = self.ctx.ins().binary1(Opcode::Isub, one, m1_res);
        let m1_res = self.ctx.ins().binary1(Opcode::Imul, base_is_m1, m1_res);
        let neg_res = self.ctx.ins().binary1(Opcode::Iadd, base_is_one, m1_res);

        let lo = self.ctx.ins().binary1(Opcode::Imul, neg, neg_res);
        let hi = self.ctx.ins().binary1(Opcode::Imul, not_neg, pos_res);
        self.ctx.ins().binary1(Opcode::Iadd, lo, hi)
    }

    fn lower_user_fun(&mut self, fun: hir::Function, lim: bool, args: &[ExprId]) -> Value {
        if lim {
            if self.ctx.no_equations {
                return self.lower_expr(args[0]);
            }
            let new_val = self.lower_expr(args[0]);
            let state = self.ctx.start_limit(new_val);
            let old_val = self.ctx.use_param(ParamKind::PrevState(state));
            let enable_lim = self.ctx.use_param(ParamKind::EnableLim);
            let res = self.lower_select_with(
                enable_lim,
                |mut cx| {
                    cx.ctx.def_place(PlaceKind::FunctionArg(fun.arg(0, self.ctx.db)), new_val);
                    cx.ctx.def_place(PlaceKind::FunctionArg(fun.arg(1, self.ctx.db)), old_val);
                    cx.lower_user_fun_impl(fun, args, true)
                },
                |_| new_val,
            );

            self.ctx.finish_limit(state, res)
        } else {
            self.lower_user_fun_impl(fun, args, false)
        }
    }

    fn lower_user_fun_impl(
        &mut self,
        fun: hir::Function,
        args: &[ExprId],
        inside_lim: bool,
    ) -> Value {
        // FIXME proper path for functions
        let mut path = self.path.to_owned();
        path.push_str(&fun.name(self.ctx.db));

        let mut args = zip(fun.args(self.ctx.db), args);
        // skip the first two arguments
        if inside_lim {
            args.next();
            args.next();
        }
        for (arg, expr) in args.clone() {
            if let Type::Array { .. } = arg.ty(self.ctx.db) {
                // Whole-array argument (Enhancement-18): bind the function's element variables
                // (`v[i]`) from the caller's array elements (input semantics).
                // Enhancement-33: `lower_array_elems` accepts array *literals* as well as
                // whole-array variable references. Previously a literal argument bound
                // nothing (`array_var_ref` is only populated for variable references), so
                // `f('{1.0, 2.0})` silently left every element at 0.
                let func_elems = arg.array_elems(self.ctx.db);
                let caller_vals = self.lower_array_elems(*expr);
                for (&p_i, val) in func_elems.iter().zip(caller_vals) {
                    self.ctx.def_place(PlaceKind::Var(p_i), val);
                }
                continue;
            }
            let init = if arg.is_input(self.ctx.db) {
                self.lower_expr(*expr)
            } else {
                match &arg.ty(self.ctx.db) {
                    Type::Real => F_ZERO,
                    Type::Integer => ZERO,
                    ty => unreachable!("invalid function arg type {:?}", ty),
                }
            };

            self.ctx.def_place(PlaceKind::FunctionArg(arg), init);
        }

        let init = match &fun.return_ty(self.ctx.db) {
            Type::Real => F_ZERO,
            Type::Integer => ZERO,
            ty => unreachable!("invalid function return type {:?}", ty),
        };
        self.ctx.def_place(PlaceKind::FunctionReturn(fun), init);

        let body = fun.body(self.ctx.db);
        BodyLoweringCtx { body: body.borrow(), path: self.path, ctx: self.ctx }.lower_entry_stmts();

        // write outputs back to the caller (including any required cast).
        for (arg, &expr) in args {
            if !arg.is_output(self.ctx.db) {
                continue;
            }
            if matches!(arg.ty(self.ctx.db), Type::Array { .. }) {
                // Whole-array output/inout argument (Enhancement-20): copy the function's element
                // variables back to the caller's array elements after the body has run.
                let func_elems = arg.array_elems(self.ctx.db);
                let caller_elems = self.body.array_var_ref(expr).unwrap_or_default();
                for (&p_i, &c_i) in func_elems.iter().zip(&caller_elems) {
                    let val = self.ctx.read_variable(p_i);
                    self.ctx.def_place(PlaceKind::Var(c_i), val);
                }
                continue;
            }
            let mut val = self.ctx.use_place(PlaceKind::FunctionArg(arg));
            // casting in reverse here since we write back
            if let Some((dst, src)) = self.body.needs_cast(expr) {
                val = self.ctx.insert_cast(val, src, &dst)
            }
            let dst = self.body.get_expr(expr).as_assignment_lhs();
            self.ctx.def_place(dst.into(), val);
        }

        self.ctx.use_place(PlaceKind::FunctionReturn(fun))
    }

    /// Evaluate a compile-time-constant real expression (literal, possibly
    /// with a leading unary `+`/`-`). Used to read the `noise_table` inline
    /// data array, whose elements must all be constants per the LRM.
    fn eval_const_real(&self, expr: ExprId) -> Option<f64> {
        self.eval_const_real_at(expr, 0)
    }

    /// Fold `expr` to a number if its value is fixed when the model is compiled.
    ///
    /// The tables built from this (`noise_table`, the inline `$table_model`) are
    /// materialised at COMPILE time, and the caller turns a `None` into `0.0`.
    /// Only literals and unary minus were folded here, so every other spelling
    /// of a constant silently became a zero ENTRY in the table: the same table,
    /// with one value written as `20.0` and as a `localparam` holding 20.0, gave
    /// `$table_model` 15 and 5 -- a plausible, smooth, wrong curve -- and cost
    /// `noise_table` its noise entirely. A constant-folded expression such as
    /// `1e-12*1.0` was dropped the same way.
    ///
    /// A `parameter` is deliberately not folded: it is overridable, so its value
    /// is not known here. Validation refuses such an entry outright rather than
    /// letting it reach the `unwrap_or(0.0)`.
    fn eval_const_real_at(&self, expr: ExprId, depth: u32) -> Option<f64> {
        const_real_in_body(self.ctx.db, self.body, expr, depth)
    }

    /// Read a whitespace-separated two-column `<freq> <power>` noise table
    /// file, resolved relative to the directory of the compilation root file.
    /// Blank lines and `#`/`//`/`*`-prefixed comment lines are skipped.
    fn read_noise_table_file(&self, fname: &str) -> Vec<(f64, f64)> {
        let Some(dir) = self.ctx.db.root_file_dir() else { return Vec::new() };
        let Some(path) = dir.join(fname) else { return Vec::new() };
        let Some(abs) = path.as_path() else { return Vec::new() };
        let Ok(content) = std::fs::read_to_string(abs) else { return Vec::new() };
        let mut out = Vec::new();
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty()
                || line.starts_with('#')
                || line.starts_with("//")
                || line.starts_with('*')
            {
                continue;
            }
            let mut it = line.split_whitespace();
            if let (Some(a), Some(b)) = (it.next(), it.next()) {
                // Enhancement-396: non-finite entries are refused, as for
                // $table_model data files.
                if let (Ok(f), Ok(p)) = (a.parse::<f64>(), b.parse::<f64>()) {
                    if f.is_finite() && p.is_finite() {
                        out.push((f, p));
                    }
                }
            }
        }
        out
    }

    /// Gather the `(frequency, power)` pairs backing a `noise_table` /
    /// `noise_table_log` call, either from an inline real array
    /// `{f0, p0, f1, p1, ...}` or from a two-column data file.
    fn noise_table_data(&self, signature: hir::Signature, args: &[ExprId]) -> Vec<(f64, f64)> {
        match signature {
            NOISE_TABLE_INLINE | NOISE_TABLE_INLINE_NAME => {
                let elems = match self.body.get_expr(args[0]) {
                    Expr::Array(vals) => vals,
                    _ => return Vec::new(),
                };
                let nums: Vec<f64> =
                    elems.iter().map(|&e| self.eval_const_real(e).unwrap_or(0.0)).collect();
                nums.chunks_exact(2).map(|c| (c[0], c[1])).collect()
            }
            NOISE_TABLE_FILE | NOISE_TABLE_FILE_NAME => {
                // Defensive: inference now requires a string LITERAL here, so this
                // cannot be reached with anything else. It used to be an `unwrap()`
                // that panicked the whole compiler on a string parameter.
                let Some(lit) = self.body.as_literal(args[0]) else { return Vec::new() };
                self.read_noise_table_file(lit.unwrap_str())
            }
            _ => Vec::new(),
        }
    }

    /// Reads all whitespace-separated numeric tokens from a table data file (blank lines and
    /// `#`/`//`/`*` comment lines skipped), resolved relative to the compilation root directory.
    fn read_table_tokens(&self, fname: &str) -> Vec<f64> {
        let Some(dir) = self.ctx.db.root_file_dir() else { return Vec::new() };
        let Some(path) = dir.join(fname) else { return Vec::new() };
        let Some(abs) = path.as_path() else { return Vec::new() };
        let Ok(content) = std::fs::read_to_string(abs) else { return Vec::new() };
        let mut out = Vec::new();
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty()
                || line.starts_with('#')
                || line.starts_with("//")
                || line.starts_with('*')
            {
                continue;
            }
            for tok in line.split_whitespace() {
                // Enhancement-396: a non-finite value (nan/inf, or an overflowing
                // exponent, which `parse` turns into an infinity rather than an
                // error) is refused here exactly as `table_file_is_usable` refuses
                // it, so the reader and the validator agree on what a usable file
                // is. Validation rejects such a file outright; this keeps the two
                // from drifting apart if that check is ever relaxed.
                if let Ok(v) = tok.parse::<f64>() {
                    if v.is_finite() {
                        out.push(v);
                    }
                }
            }
        }
        out
    }

    /// Reads a self-describing multi-dimensional grid file into per-axis coordinate vectors and a
    /// row-major value tensor (outermost axis slowest). Format (whitespace-separated, comments
    /// ignored): `ndim`, then `ndim` axis sizes, then each axis's ascending coordinates, then
    /// `prod(sizes)` values. Returns `None` on a dimensionality mismatch or a truncated file.
    fn read_table_grid_nd(&self, fname: &str, ndim: usize) -> Option<(Vec<Vec<f64>>, Vec<f64>)> {
        let mut it = self.read_table_tokens(fname).into_iter();
        if it.next()? as usize != ndim {
            return None;
        }
        let mut sizes: Vec<usize> =
            (0..ndim).map(|_| it.next().map(|v| v as usize)).collect::<Option<_>>()?;
        if sizes.iter().any(|&s| s == 0) {
            return None;
        }
        let mut axes: Vec<Vec<f64>> = Vec::with_capacity(ndim);
        for &sz in &sizes {
            axes.push((0..sz).map(|_| it.next()).collect::<Option<Vec<f64>>>()?);
        }
        let total: usize = sizes.iter().product();
        let mut tensor = (0..total).map(|_| it.next()).collect::<Option<Vec<f64>>>()?;
        // Enhancement-460: `interp_1d_values` below states its precondition -- "`grid` is
        // ascending" -- and this reader was the one path that never established it. The
        // 1-D forms (inline pairs and the two-column file) sort and de-duplicate their
        // breakpoints; a multi-dimensional grid did not, so a file whose axis ran
        // downwards, out of order, or repeated a coordinate was accepted in silence and
        // interpolated to garbage: with f(x,y)=x^2+y sampled on x=[0,1,2], writing that
        // axis as `2 1 0` returned 0.5, 4.5, 4.5 over x = 0, 0.5, 1 -- which matches NO
        // reading of the file, since taking it at its word (row k belongs to axis[k])
        // gives 4.5, 3.0, 1.5 and the ascending function gives 0.5, 1.0, 1.5. The
        // interpolation simply clamped. Normalising here makes every form of the table
        // behave identically, and the grid mean what the file says.
        for d in 0..ndim {
            Self::normalize_grid_axis(&mut sizes, &mut axes, &mut tensor, d);
        }
        Some((axes, tensor))
    }

    /// Sorts axis `d` ascending and drops repeated coordinates, permuting the row-major
    /// value tensor to match. Keeping the FIRST of a repeated coordinate is what
    /// `dedup_by` does on the 1-D path, so both agree on the same data.
    fn normalize_grid_axis(
        sizes: &mut [usize],
        axes: &mut [Vec<f64>],
        tensor: &mut Vec<f64>,
        d: usize,
    ) {
        let sz = sizes[d];
        let mut ord: Vec<usize> = (0..sz).collect();
        ord.sort_by(|&i, &j| {
            axes[d][i].partial_cmp(&axes[d][j]).unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut kept: Vec<usize> = Vec::with_capacity(sz);
        for &i in &ord {
            if kept.last().map_or(true, |&p| axes[d][p] != axes[d][i]) {
                kept.push(i);
            }
        }
        // already strictly ascending: nothing to permute
        if kept.len() == sz && kept.iter().enumerate().all(|(k, &i)| k == i) {
            return;
        }
        let new_sz = kept.len();
        let stride: usize = sizes[d + 1..].iter().product();
        let outer: usize = sizes[..d].iter().product();
        let mut out = Vec::with_capacity(outer * new_sz * stride);
        for o in 0..outer {
            for &i in &kept {
                let base = (o * sz + i) * stride;
                out.extend_from_slice(&tensor[base..base + stride]);
            }
        }
        let coords: Vec<f64> = kept.iter().map(|&i| axes[d][i]).collect();
        axes[d] = coords;
        sizes[d] = new_sz;
        *tensor = out;
    }

    /// One-dimensional piecewise-linear interpolation of runtime `vals` (one per `grid` point) at
    /// `x`, built as a select chain so it is differentiable. `grid` is ascending; outside it the
    /// result is clamped to the endpoint value (constant extrapolation) unless `linear_extrap`, in
    /// which case the end segments' slopes continue. This is the shared kernel for every dimension.
    fn interp_1d_values(
        &mut self,
        x: Value,
        grid: &[f64],
        vals: &[Value],
        linear_extrap: bool,
    ) -> Value {
        let n = grid.len();
        if n == 0 {
            return F_ZERO;
        }
        if n == 1 {
            return vals[0];
        }
        // segment i:  vals[i] + (x - grid[i]) * (vals[i+1]-vals[i]) / (grid[i+1]-grid[i])
        let mut seg = Vec::with_capacity(n - 1);
        for i in 0..n - 1 {
            let dv = self.ctx.ins().fsub(vals[i + 1], vals[i]);
            let dgrid = self.ctx.fconst(grid[i + 1] - grid[i]);
            let slope = self.ctx.ins().fdiv(dv, dgrid);
            let xi = self.ctx.fconst(grid[i]);
            let dx = self.ctx.ins().fsub(x, xi);
            let term = self.ctx.ins().fmul(dx, slope);
            seg.push(self.ctx.ins().fadd(vals[i], term));
        }
        // segment i applies once x >= grid[i] (segment 0 is the default and covers below the grid;
        // the last segment covers above it -- i.e. linear extrapolation from the end slopes).
        let mut result = seg[0];
        for i in 1..n - 1 {
            let gi = self.ctx.fconst(grid[i]);
            let ge = self.ctx.ins().fge(x, gi);
            let seg_i = seg[i];
            result = self.ctx.make_select(ge, move |_c, b| if b { seg_i } else { result });
        }
        if !linear_extrap {
            let g0 = self.ctx.fconst(grid[0]);
            let v0 = vals[0];
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { v0 } else { result });
            let gl = self.ctx.fconst(grid[n - 1]);
            let vl = vals[n - 1];
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { vl } else { result });
        }
        result
    }

    /// Enhancement-392: the largest runtime `$table_model` that is normalised
    /// (sorted and de-duplicated) in the emitted code.
    ///
    /// Enhancement-390 set this to 64 with a quadratic bubble network. That was
    /// low enough to matter and, worse, SILENT: above it the runtime form stopped
    /// sorting while the compile-time form kept sorting at any size, so the same
    /// data gave different answers again -- 160.0 against 6.2566 on a 65-knot
    /// reversed cubic table. A Batcher odd-even merge network is O(n log^2 n)
    /// instead of O(n^2), which buys the higher bound at lower cost than 64 used
    /// to be, and `hir_ty` now REPORTS a table that exceeds it rather than quietly
    /// changing behaviour.

    /// Enhancement-391: move repeated abscissae to the END of a runtime table and
    /// replicate the last distinct knot over them.
    ///
    /// The compile-time forms de-duplicate by SHORTENING the point vector, so the
    /// spline is solved over `m` distinct knots. Carrying the first value forward
    /// (Enhancement-390) reproduces that for LINEAR interpolation -- a zero-width
    /// segment with equal endpoints contributes nothing -- but not for a spline,
    /// where the dead knot still occupies a row of the tridiagonal system and
    /// perturbs every moment.
    ///
    /// A runtime array cannot shrink, so the duplicates are instead partitioned to
    /// the end (a stable 0/1 bubble network on a "is a repeat" flag that travels
    /// with its point), and the trailing slots take the last distinct knot's
    /// coordinates. The live prefix is then exactly the de-duplicated table, and
    /// `interp_1d_spline_runtime` forces the natural boundary onto the last live
    /// knot rather than the last slot.
    fn compact_distinct_runtime(&mut self, xs: &mut Vec<Value>, ys: &mut Vec<Value>) {
        let n = xs.len();
        // Enhancement-392: the SAME bound as the sort. De-duplication reads
        // adjacency, so it is only meaningful on sorted data; running it past the
        // point where sorting stops left half the normalisation in place.
        if n < 2 || n > MAX_RUNTIME_TABLE {
            return;
        }
        let one = self.ctx.fconst(1.0);
        // flag = 1.0 for a point whose abscissa repeats its predecessor's. Computed
        // before any movement, since it is a statement about the SORTED order.
        let mut flags: Vec<Value> = Vec::with_capacity(n);
        flags.push(F_ZERO);
        for i in 1..n {
            let dup = self.ctx.ins().feq(xs[i], xs[i - 1]);
            flags.push(self.ctx.make_select(dup, move |_c, b| if b { one } else { F_ZERO }));
        }
        // stable partition: flagged points bubble to the end, order otherwise kept
        for _ in 0..n {
            for j in 0..n - 1 {
                let swap = self.ctx.ins().fgt(flags[j], flags[j + 1]);
                let (xa, xb) = (xs[j], xs[j + 1]);
                let (ya, yb) = (ys[j], ys[j + 1]);
                let (fa, fb) = (flags[j], flags[j + 1]);
                let nx0 = self.ctx.make_select(swap, move |_c, b| if b { xb } else { xa });
                let nx1 = self.ctx.make_select(swap, move |_c, b| if b { xa } else { xb });
                let ny0 = self.ctx.make_select(swap, move |_c, b| if b { yb } else { ya });
                let ny1 = self.ctx.make_select(swap, move |_c, b| if b { ya } else { yb });
                let nf0 = self.ctx.make_select(swap, move |_c, b| if b { fb } else { fa });
                let nf1 = self.ctx.make_select(swap, move |_c, b| if b { fa } else { fb });
                xs[j] = nx0;
                xs[j + 1] = nx1;
                ys[j] = ny0;
                ys[j + 1] = ny1;
                flags[j] = nf0;
                flags[j + 1] = nf1;
            }
        }
        // the flagged tail takes the last distinct knot, one slot at a time
        let half = self.ctx.fconst(0.5);
        for i in 1..n {
            let dropped = self.ctx.ins().fgt(flags[i], half);
            let (px, py) = (xs[i - 1], ys[i - 1]);
            let (cx, cy) = (xs[i], ys[i]);
            xs[i] = self.ctx.make_select(dropped, move |_c, b| if b { px } else { cx });
            ys[i] = self.ctx.make_select(dropped, move |_c, b| if b { py } else { cy });
        }
    }

    /// Enhancement-390: natural cubic spline over a RUNTIME grid.
    ///
    /// `interp_1d_spline` builds its moment matrix by inverting the tridiagonal
    /// system at COMPILE time, which needs the abscissae as constants. With array
    /// variables for the data they are not, so the cubic control code was silently
    /// ignored and `"3"` quietly interpolated LINEARLY -- the same table and the
    /// same control string gave 0.35 from a literal and 0.5 from arrays.
    ///
    /// The system is instead solved in MIR by the Thomas algorithm, unrolled: the
    /// knot COUNT is known at compile time even when the knots are not, so the
    /// elimination and back-substitution are straight-line code over runtime
    /// values. Divisions are guarded, so a degenerate grid yields zero moments
    /// (i.e. the linear result) rather than NaN.
    fn interp_1d_spline_runtime(
        &mut self,
        x: Value,
        grid: &[Value],
        vals: &[Value],
        linear_extrap: bool,
    ) -> Value {
        let n = grid.len();
        if n < 3 {
            return self.interp_1d_runtime(x, grid, vals, linear_extrap);
        }
        // Enhancement-391: reduce to the distinct knots first, so the system below
        // is the one the compile-time spline solves.
        let (mut grid, mut vals) = (grid.to_vec(), vals.to_vec());
        self.compact_distinct_runtime(&mut grid, &mut vals);
        let (grid, vals) = (&grid[..], &vals[..]);
        let last_x = grid[n - 1];
        // h[i] = grid[i+1] - grid[i]
        let h: Vec<Value> =
            (0..n - 1).map(|i| self.ctx.ins().fsub(grid[i + 1], grid[i])).collect();
        // slopes d[i] = (vals[i+1]-vals[i]) / h[i]
        let d: Vec<Value> = (0..n - 1)
            .map(|i| {
                let dv = self.ctx.ins().fsub(vals[i + 1], vals[i]);
                self.fdiv_guarded(dv, h[i])
            })
            .collect();

        // Interior system for M[1..n-2] (natural spline: M[0] = M[n-1] = 0):
        //   h[i-1]*M[i-1] + 2*(h[i-1]+h[i])*M[i] + h[i]*M[i+1] = 6*(d[i] - d[i-1])
        let six = self.ctx.fconst(6.0);
        let two = self.ctx.fconst(2.0);
        let m_int = n - 2; // number of unknowns
        let mut a = Vec::with_capacity(m_int); // sub-diagonal
        let mut b = Vec::with_capacity(m_int); // diagonal
        let mut c = Vec::with_capacity(m_int); // super-diagonal
        let mut r = Vec::with_capacity(m_int); // rhs
        for k in 0..m_int {
            let i = k + 1;
            // Enhancement-391: a knot at the END of the live range -- the last
            // distinct knot and every replicated slot after it -- carries the
            // natural boundary condition M = 0. Compaction guarantees the live
            // prefix has strictly increasing abscissae, so every OTHER row is an
            // ordinary interior row with two non-degenerate intervals, exactly as
            // in the de-duplicated compile-time system.
            let at_end = self.ctx.ins().feq(grid[i], last_x);
            let ai = h[i - 1];
            let sum = self.ctx.ins().fadd(h[i - 1], h[i]);
            let bi = self.ctx.ins().fmul(two, sum);
            let ci = h[i];
            let dd = self.ctx.ins().fsub(d[i], d[i - 1]);
            let ri = self.ctx.ins().fmul(six, dd);
            let one = self.ctx.fconst(1.0);
            a.push(self.ctx.make_select(at_end, move |_c, b| if b { F_ZERO } else { ai }));
            b.push(self.ctx.make_select(at_end, move |_c, b| if b { one } else { bi }));
            c.push(self.ctx.make_select(at_end, move |_c, b| if b { F_ZERO } else { ci }));
            r.push(self.ctx.make_select(at_end, move |_c, b| if b { F_ZERO } else { ri }));
        }
        // forward elimination
        let mut cp = Vec::with_capacity(m_int);
        let mut rp = Vec::with_capacity(m_int);
        for k in 0..m_int {
            if k == 0 {
                cp.push(self.fdiv_guarded(c[0], b[0]));
                rp.push(self.fdiv_guarded(r[0], b[0]));
            } else {
                let acp = self.ctx.ins().fmul(a[k], cp[k - 1]);
                let den = self.ctx.ins().fsub(b[k], acp);
                let cpk = self.fdiv_guarded(c[k], den);
                let arp = self.ctx.ins().fmul(a[k], rp[k - 1]);
                let num = self.ctx.ins().fsub(r[k], arp);
                let rpk = self.fdiv_guarded(num, den);
                cp.push(cpk);
                rp.push(rpk);
            }
        }
        // back substitution -> interior moments
        let mut m_rev: Vec<Value> = Vec::with_capacity(m_int);
        for k in (0..m_int).rev() {
            let v = if k == m_int - 1 {
                rp[k]
            } else {
                let prev = *m_rev.last().unwrap();
                let cx = self.ctx.ins().fmul(cp[k], prev);
                self.ctx.ins().fsub(rp[k], cx)
            };
            m_rev.push(v);
        }
        m_rev.reverse();
        let mut moments = Vec::with_capacity(n);
        moments.push(F_ZERO);
        moments.extend(m_rev);
        moments.push(F_ZERO);

        // segment i:  M[i]*a^3/(6h) + M[i+1]*b^3/(6h)
        //           + (vals[i]/h - M[i]*h/6)*a + (vals[i+1]/h - M[i+1]*h/6)*b
        let mut seg = Vec::with_capacity(n - 1);
        for i in 0..n - 1 {
            let six_h = self.ctx.ins().fmul(six, h[i]);
            let aa = self.ctx.ins().fsub(grid[i + 1], x);
            let bb = self.ctx.ins().fsub(x, grid[i]);
            let a2 = self.ctx.ins().fmul(aa, aa);
            let a3 = self.ctx.ins().fmul(a2, aa);
            let b2 = self.ctx.ins().fmul(bb, bb);
            let b3 = self.ctx.ins().fmul(b2, bb);
            let mi_a3 = self.ctx.ins().fmul(moments[i], a3);
            let t1 = self.fdiv_guarded(mi_a3, six_h);
            let mi1_b3 = self.ctx.ins().fmul(moments[i + 1], b3);
            let t2 = self.fdiv_guarded(mi1_b3, six_h);
            let h6 = self.fdiv_guarded(h[i], six);
            let vih = self.fdiv_guarded(vals[i], h[i]);
            let mih6 = self.ctx.ins().fmul(moments[i], h6);
            let c3 = self.ctx.ins().fsub(vih, mih6);
            let t3 = self.ctx.ins().fmul(c3, aa);
            let vi1h = self.fdiv_guarded(vals[i + 1], h[i]);
            let mi1h6 = self.ctx.ins().fmul(moments[i + 1], h6);
            let c4 = self.ctx.ins().fsub(vi1h, mi1h6);
            let t4 = self.ctx.ins().fmul(c4, bb);
            let s12 = self.ctx.ins().fadd(t1, t2);
            let s34 = self.ctx.ins().fadd(t3, t4);
            let cubic = self.ctx.ins().fadd(s12, s34);
            // A zero-width interval carries no cubic; it stands for its own knot.
            let dead = self.ctx.ins().feq(h[i], F_ZERO);
            let vi = vals[i];
            seg.push(self.ctx.make_select(dead, move |_c, b| if b { vi } else { cubic }));
        }
        let mut result = seg[0];
        for i in 1..n - 1 {
            // Enhancement-391: skip the replicated tail. Without this the highest
            // qualifying index wins and a dead segment would shadow the last live
            // one for every x at or beyond the final knot.
            let ge = self.ctx.ins().fge(x, grid[i]);
            let live = self.ctx.ins().fgt(grid[i + 1], grid[i]);
            let take = crate::stmt::bool_and(self.ctx, ge, live);
            let seg_i = seg[i];
            result = self.ctx.make_select(take, move |_c, b| if b { seg_i } else { result });
        }

        // Extrapolation, mirroring the compile-time spline exactly: with 'L' the
        // END TANGENT is continued, NOT the cubic extended. Getting this wrong is
        // invisible inside the grid -- interior values match to the last digit
        // either way -- and shows up only outside it.
        let g0 = grid[0];
        let gl = grid[n - 1];
        if linear_extrap {
            let h0 = self.ctx.ins().fsub(grid[1], grid[0]);
            let six_c = self.ctx.fconst(6.0);
            let h06 = self.fdiv_guarded(h0, six_c);
            let dv0 = self.ctx.ins().fsub(vals[1], vals[0]);
            let dv0h = self.fdiv_guarded(dv0, h0);
            let m1term = self.ctx.ins().fmul(moments[1], h06);
            let slope0 = self.ctx.ins().fsub(dv0h, m1term);
            let dx0 = self.ctx.ins().fsub(x, g0);
            let ext0 = self.ctx.ins().fmul(dx0, slope0);
            let low = self.ctx.ins().fadd(vals[0], ext0);
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { low } else { result });

            // Enhancement-391: the upper end tangent must come from the last two
            // LIVE knots. After compaction the final slots are replicas of the last
            // distinct knot, so `grid[n-1] - grid[n-2]` is zero and the guarded
            // division silently turned the extrapolation into a CLAMP -- correct
            // inside the grid, wrong past it. Scanning forward and keeping the last
            // knot strictly below the end finds the real neighbour, since the live
            // prefix is strictly increasing.
            let mut prev_x = grid[0];
            let mut prev_y = vals[0];
            let mut prev_m = moments[0];
            for i in 1..n {
                let below = self.ctx.ins().flt(grid[i], last_x);
                let (gi, vi, mi) = (grid[i], vals[i], moments[i]);
                let (px, py, pm) = (prev_x, prev_y, prev_m);
                prev_x = self.ctx.make_select(below, move |_c, b| if b { gi } else { px });
                prev_y = self.ctx.make_select(below, move |_c, b| if b { vi } else { py });
                prev_m = self.ctx.make_select(below, move |_c, b| if b { mi } else { pm });
            }
            let hl = self.ctx.ins().fsub(last_x, prev_x);
            let six_c2 = self.ctx.fconst(6.0);
            let hl6 = self.fdiv_guarded(hl, six_c2);
            let dvl = self.ctx.ins().fsub(vals[n - 1], prev_y);
            let dvlh = self.fdiv_guarded(dvl, hl);
            let mlterm = self.ctx.ins().fmul(prev_m, hl6);
            let slopel = self.ctx.ins().fadd(dvlh, mlterm);
            let dxl = self.ctx.ins().fsub(x, gl);
            let extl = self.ctx.ins().fmul(dxl, slopel);
            let high = self.ctx.ins().fadd(vals[n - 1], extl);
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { high } else { result });
        } else {
            let v0 = vals[0];
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { v0 } else { result });
            let vl = vals[n - 1];
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { vl } else { result });
        }
        result
    }

    /// Enhancement-390: sort a runtime (x, y) table into ascending x.
    ///
    /// The compile-time forms sort and de-duplicate their breakpoints before
    /// interpolating (`pts.sort_by` / `dedup_by`), so the same table data gave
    /// DIFFERENT answers depending on whether it arrived as a literal or as array
    /// variables -- silently, with no diagnostic on either path. The LRM does
    /// require ascending data, but one path quietly repairing it and the other
    /// quietly trusting it is the worst of both.
    ///
    /// The sort is an unrolled bubble network: `n*(n-1)/2` compare-and-swap
    /// stages, each two `select`s. That is fine for the table sizes this form is
    /// meant for and quadratic beyond them, so above `MAX_RUNTIME_SORT` the data
    /// is used as given -- the LRM's ascending requirement then governs, exactly
    /// as it did before.
    fn sort_pairs_runtime(&mut self, xs: &mut Vec<Value>, ys: &mut Vec<Value>) {
        let n = xs.len();
        if n < 2 || n > MAX_RUNTIME_TABLE {
            return;
        }
        // Enhancement-392: the network must be STABLE, because the de-duplication
        // below -- and `pts.dedup_by` in the compile-time path it has to agree with
        // -- keeps the FIRST of any repeated abscissa in ORIGINAL order (Rust's
        // `sort_by` is stable). An odd-even transposition network is stable for
        // free, since it only ever exchanges neighbours; Batcher's is not, because
        // it compares elements that are far apart, and two equal abscissae can come
        // out swapped. That is invisible until the ys differ, and then the runtime
        // form keeps a different point than the compile-time form does.
        //
        // Stability is restored by carrying the original index alongside each point
        // and breaking ties on it, which makes every key distinct and the sort
        // order total. The indices are compile-time constants, so this costs one
        // more tracked value per point and nothing at runtime beyond the tie-break.
        let mut ps: Vec<Value> = (0..n).map(|i| self.ctx.fconst(i as f64)).collect();
        for (j, k) in batcher_network(n) {
            let xgt = self.ctx.ins().fgt(xs[j], xs[k]);
            let xeq = self.ctx.ins().feq(xs[j], xs[k]);
            let pgt = self.ctx.ins().fgt(ps[j], ps[k]);
            let tie = crate::stmt::bool_and(self.ctx, xeq, pgt);
            let swap = crate::stmt::bool_or(self.ctx, xgt, tie);
            let (xa, xb) = (xs[j], xs[k]);
            let (ya, yb) = (ys[j], ys[k]);
            let (pa, pb) = (ps[j], ps[k]);
            let lo_x = self.ctx.make_select(swap, move |_c, b| if b { xb } else { xa });
            let hi_x = self.ctx.make_select(swap, move |_c, b| if b { xa } else { xb });
            let lo_y = self.ctx.make_select(swap, move |_c, b| if b { yb } else { ya });
            let hi_y = self.ctx.make_select(swap, move |_c, b| if b { ya } else { yb });
            let lo_p = self.ctx.make_select(swap, move |_c, b| if b { pb } else { pa });
            let hi_p = self.ctx.make_select(swap, move |_c, b| if b { pa } else { pb });
            xs[j] = lo_x;
            xs[k] = hi_x;
            ys[j] = lo_y;
            ys[k] = hi_y;
            ps[j] = lo_p;
            ps[k] = hi_p;
        }

        // Enhancement-390: the compile-time forms also DE-DUPLICATE, keeping the
        // first of any repeated abscissa (`pts.dedup_by(|a, b| a.0 == b.0)`). A
        // runtime table cannot drop an element -- the array length is fixed -- but
        // carrying the first value forward over each repeat is equivalent for
        // interpolation, and leaves the two paths agreeing on identical data.
        for i in 0..n - 1 {
            let dup = self.ctx.ins().feq(xs[i + 1], xs[i]);
            let (keep, drop_) = (ys[i], ys[i + 1]);
            ys[i + 1] = self.ctx.make_select(dup, move |_c, b| if b { keep } else { drop_ });
        }
    }

    /// Enhancement-390: `a / b` guarded against a zero denominator.
    ///
    /// A runtime table may contain two equal abscissae -- duplicated data, or an
    /// array the body never filled in, whose elements are all 0. The segment width
    /// is then 0, the slope divides by zero, and the NaN propagates until ngspice
    /// gives up with "Timestep too small; cause unrecorded", which says nothing
    /// about the table. A zero-width segment carries no information, so its slope
    /// is taken as zero.
    fn fdiv_guarded(&mut self, num: Value, den: Value) -> Value {
        let zero = self.ctx.ins().feq(den, F_ZERO);
        let quot = self.ctx.ins().fdiv(num, den);
        self.ctx.make_select(zero, move |_c, b| if b { F_ZERO } else { quot })
    }

    /// Enhancement-389: `interp_1d_values` with a RUNTIME grid.
    ///
    /// `$table_model(x, xs, ys, "ctrl")` with array *variables* for the data (LRM
    /// p274) cannot fold its breakpoints at compile time -- `xs[i]` is whatever the
    /// body computed this evaluation -- so the abscissae become MIR values too, and
    /// every `fconst(grid[i])` here is a live read instead.
    ///
    /// The shape is otherwise identical, deliberately: the segment expressions and
    /// the select chain are the same arithmetic, so `mir_autodiff` differentiates
    /// this exactly as it does the compile-time form, including through `xs` when a
    /// breakpoint itself depends on the solution.
    ///
    /// The table must be ASCENDING in `x`, which the LRM already requires and which
    /// cannot be checked here (a compile-time table is sorted during lowering; these
    /// values do not exist yet). An unsorted runtime table selects the wrong segment
    /// rather than failing.
    fn interp_1d_runtime(
        &mut self,
        x: Value,
        grid: &[Value],
        vals: &[Value],
        linear_extrap: bool,
    ) -> Value {
        let n = grid.len();
        if n == 0 {
            return F_ZERO;
        }
        if n == 1 {
            return vals[0];
        }
        // segment i:  vals[i] + (x - grid[i]) * (vals[i+1]-vals[i]) / (grid[i+1]-grid[i])
        let mut seg = Vec::with_capacity(n - 1);
        for i in 0..n - 1 {
            let dv = self.ctx.ins().fsub(vals[i + 1], vals[i]);
            let dgrid = self.ctx.ins().fsub(grid[i + 1], grid[i]);
            // Enhancement-390: a duplicated or unset abscissa makes this zero.
            let slope = self.fdiv_guarded(dv, dgrid);
            let dx = self.ctx.ins().fsub(x, grid[i]);
            let term = self.ctx.ins().fmul(dx, slope);
            seg.push(self.ctx.ins().fadd(vals[i], term));
        }
        let mut result = seg[0];
        for i in 1..n - 1 {
            let ge = self.ctx.ins().fge(x, grid[i]);
            let seg_i = seg[i];
            result = self.ctx.make_select(ge, move |_c, b| if b { seg_i } else { result });
        }
        let v0 = vals[0];
        let g0 = grid[0];
        let vl = vals[n - 1];
        let gl = grid[n - 1];
        if !linear_extrap {
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { v0 } else { result });
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { vl } else { result });
        } else {
            // Enhancement-395: extrapolate along the first/last segment of NONZERO
            // width.
            //
            // A repeated abscissa at an end makes that segment's `dgrid` zero, so
            // `fdiv_guarded` yields a zero slope and the extrapolation went FLAT --
            // the runtime form returned 0.0 below a start-repeated grid where the
            // compile-time form (which de-duplicates by shortening the vector)
            // extrapolated properly, and likewise above an end-repeated one.
            // Interior values were exact, which is why it survived: only points
            // outside the grid differ. Enhancement-391 fixed exactly this for the
            // CUBIC end tangent; the LINEAR path kept the defect at both ends.
            //
            // `slope_lo` walks DOWN so the last assignment wins and it ends up
            // holding the FIRST live segment; `slope_hi` walks UP for the LAST.
            // With strictly increasing abscissae both reduce to seg[0]/seg[n-2]
            // and the emitted code is equivalent to before.
            let mut slope_lo = F_ZERO;
            for i in (0..n - 1).rev() {
                let dgrid = self.ctx.ins().fsub(grid[i + 1], grid[i]);
                let dv = self.ctx.ins().fsub(vals[i + 1], vals[i]);
                let sl = self.fdiv_guarded(dv, dgrid);
                let degenerate = self.ctx.ins().feq(dgrid, F_ZERO);
                slope_lo =
                    self.ctx.make_select(degenerate, move |_c, b| if b { slope_lo } else { sl });
            }
            let mut slope_hi = F_ZERO;
            for i in 0..n - 1 {
                let dgrid = self.ctx.ins().fsub(grid[i + 1], grid[i]);
                let dv = self.ctx.ins().fsub(vals[i + 1], vals[i]);
                let sl = self.fdiv_guarded(dv, dgrid);
                let degenerate = self.ctx.ins().feq(dgrid, F_ZERO);
                slope_hi =
                    self.ctx.make_select(degenerate, move |_c, b| if b { slope_hi } else { sl });
            }

            let below = self.ctx.ins().flt(x, g0);
            let dx_lo = self.ctx.ins().fsub(x, g0);
            let t_lo = self.ctx.ins().fmul(dx_lo, slope_lo);
            let ext_lo = self.ctx.ins().fadd(v0, t_lo);
            result = self.ctx.make_select(below, move |_c, b| if b { ext_lo } else { result });

            let above = self.ctx.ins().fgt(x, gl);
            let dx_hi = self.ctx.ins().fsub(x, gl);
            let t_hi = self.ctx.ins().fmul(dx_hi, slope_hi);
            let ext_hi = self.ctx.ins().fadd(vl, t_hi);
            result = self.ctx.make_select(above, move |_c, b| if b { ext_hi } else { result });
        }
        result
    }

    /// Weighted sum `Σ_j w[j]·vals[j]` (compile-time weights, runtime values), skipping zero
    /// weights. Used to express a natural-spline moment `M_i = Σ_j L[i][j]·vals[j]` in MIR.
    fn weighted_sum(&mut self, w: &[f64], vals: &[Value]) -> Value {
        let mut acc: Option<Value> = None;
        for (j, &wj) in w.iter().enumerate() {
            if wj == 0.0 {
                continue;
            }
            let c = self.ctx.fconst(wj);
            let term = self.ctx.ins().fmul(c, vals[j]);
            acc = Some(match acc {
                Some(a) => self.ctx.ins().fadd(a, term),
                None => term,
            });
        }
        acc.unwrap_or(F_ZERO)
    }

    /// One-dimensional **natural cubic spline** interpolation of runtime `vals` at `x`, built as a
    /// select chain over the grid intervals so it is differentiable (and C¹ — the smooth-derivative
    /// point of splines: `gm`/`gds` are continuous, unlike piecewise-linear). The per-point second
    /// derivatives (moments) are `M = L·vals` with `L` precomputed from the (compile-time) grid, so
    /// each moment is a constant-weighted sum of the runtime `vals` — no runtime linear solve.
    /// Degenerates to `interp_1d_values` (linear) for fewer than 3 points. Extrapolation mirrors the
    /// linear kernel: clamp to the endpoint value, or (with `linear_extrap`) continue the spline's
    /// end tangent.
    fn interp_1d_spline(
        &mut self,
        x: Value,
        grid: &[f64],
        vals: &[Value],
        linear_extrap: bool,
    ) -> Value {
        let n = grid.len();
        if n < 3 {
            return self.interp_1d_values(x, grid, vals, linear_extrap);
        }
        let l = natural_cubic_spline_moment_matrix(grid);
        // moments M[i] (M[0] = M[n-1] = 0 for a natural spline)
        let moments: Vec<Value> =
            (0..n).map(|i| self.weighted_sum(&l[i], vals)).collect();

        // cubic on interval i:  with a = grid[i+1]-x, b = x-grid[i], h = grid[i+1]-grid[i]:
        //   S = M[i]·a³/(6h) + M[i+1]·b³/(6h) + (vals[i]/h - M[i]·h/6)·a + (vals[i+1]/h - M[i+1]·h/6)·b
        let mut seg = Vec::with_capacity(n - 1);
        for i in 0..n - 1 {
            let h = grid[i + 1] - grid[i];
            let inv6h = self.ctx.fconst(1.0 / (6.0 * h));
            let invh = self.ctx.fconst(1.0 / h);
            let h6 = self.ctx.fconst(h / 6.0);
            let xi1 = self.ctx.fconst(grid[i + 1]);
            let xi = self.ctx.fconst(grid[i]);
            let a = self.ctx.ins().fsub(xi1, x);
            let b = self.ctx.ins().fsub(x, xi);
            let a2 = self.ctx.ins().fmul(a, a);
            let a3 = self.ctx.ins().fmul(a2, a);
            let b2 = self.ctx.ins().fmul(b, b);
            let b3 = self.ctx.ins().fmul(b2, b);

            let mi_a3 = self.ctx.ins().fmul(moments[i], a3);
            let t1 = self.ctx.ins().fmul(mi_a3, inv6h);
            let mi1_b3 = self.ctx.ins().fmul(moments[i + 1], b3);
            let t2 = self.ctx.ins().fmul(mi1_b3, inv6h);

            let vih = self.ctx.ins().fmul(vals[i], invh);
            let mih6 = self.ctx.ins().fmul(moments[i], h6);
            let c3 = self.ctx.ins().fsub(vih, mih6);
            let t3 = self.ctx.ins().fmul(c3, a);

            let vi1h = self.ctx.ins().fmul(vals[i + 1], invh);
            let mi1h6 = self.ctx.ins().fmul(moments[i + 1], h6);
            let c4 = self.ctx.ins().fsub(vi1h, mi1h6);
            let t4 = self.ctx.ins().fmul(c4, b);

            let s12 = self.ctx.ins().fadd(t1, t2);
            let s34 = self.ctx.ins().fadd(t3, t4);
            seg.push(self.ctx.ins().fadd(s12, s34));
        }

        // segment i applies once x >= grid[i]; segment 0 is the default (covers below the grid).
        let mut result = seg[0];
        for i in 1..n - 1 {
            let gi = self.ctx.fconst(grid[i]);
            let ge = self.ctx.ins().fge(x, gi);
            let seg_i = seg[i];
            result = self.ctx.make_select(ge, move |_c, b| if b { seg_i } else { result });
        }

        // Extrapolation outside [grid[0], grid[n-1]].
        let h0 = grid[1] - grid[0];
        let hl = grid[n - 1] - grid[n - 2];
        if linear_extrap {
            // continue the spline's end tangent:
            //   S'(grid[0])   = (v1-v0)/h0 - h0/6 · M[1]
            //   S'(grid[n-1]) = (v_{n-1}-v_{n-2})/h_l + h_l/6 · M[n-2]
            let g0 = self.ctx.fconst(grid[0]);
            let h0c = self.ctx.fconst(h0);
            let h06 = self.ctx.fconst(h0 / 6.0);
            let dv0 = self.ctx.ins().fsub(vals[1], vals[0]);
            let dv0h = self.ctx.ins().fdiv(dv0, h0c);
            let m1term = self.ctx.ins().fmul(moments[1], h06);
            let slope0 = self.ctx.ins().fsub(dv0h, m1term);
            let dx0 = self.ctx.ins().fsub(x, g0);
            let ext0 = self.ctx.ins().fmul(dx0, slope0);
            let low = self.ctx.ins().fadd(vals[0], ext0);
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { low } else { result });

            let gl = self.ctx.fconst(grid[n - 1]);
            let hlc = self.ctx.fconst(hl);
            let hl6 = self.ctx.fconst(hl / 6.0);
            let dvl = self.ctx.ins().fsub(vals[n - 1], vals[n - 2]);
            let dvlh = self.ctx.ins().fdiv(dvl, hlc);
            let mlterm = self.ctx.ins().fmul(moments[n - 2], hl6);
            let slopel = self.ctx.ins().fadd(dvlh, mlterm);
            let dxl = self.ctx.ins().fsub(x, gl);
            let extl = self.ctx.ins().fmul(dxl, slopel);
            let high = self.ctx.ins().fadd(vals[n - 1], extl);
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { high } else { result });
        } else {
            // clamp to the endpoint value (constant extrapolation)
            let g0 = self.ctx.fconst(grid[0]);
            let v0 = vals[0];
            let below = self.ctx.ins().flt(x, g0);
            result = self.ctx.make_select(below, move |_c, b| if b { v0 } else { result });
            let gl = self.ctx.fconst(grid[n - 1]);
            let vl = vals[n - 1];
            let above = self.ctx.ins().fgt(x, gl);
            result = self.ctx.make_select(above, move |_c, b| if b { vl } else { result });
        }
        result
    }

    /// N-dimensional interpolation as recursive 1-D interpolation: peel the outermost axis,
    /// interpolate each of its slices over the remaining axes (giving one runtime value per grid
    /// line), then interpolate those along the outermost axis. `tensor` is row-major (outermost axis
    /// slowest). With `cubic`, each 1-D step is a natural cubic spline (giving the exact
    /// tensor-product natural spline — recursive-1D natural spline equals the tensor-product one);
    /// otherwise multilinear. Differentiable in every coordinate.
    fn interp_nd(
        &mut self,
        coords: &[Value],
        axes: &[Vec<f64>],
        tensor: &[f64],
        linear_extrap: bool,
        cubic: bool,
    ) -> Value {
        if coords.len() == 1 {
            let vals: Vec<Value> = tensor.iter().map(|&v| self.ctx.fconst(v)).collect();
            return if cubic {
                self.interp_1d_spline(coords[0], &axes[0], &vals, linear_extrap)
            } else {
                self.interp_1d_values(coords[0], &axes[0], &vals, linear_extrap)
            };
        }
        let n0 = axes[0].len();
        if n0 == 0 || tensor.is_empty() {
            return F_ZERO;
        }
        let sub = tensor.len() / n0;
        let mut rows = Vec::with_capacity(n0);
        for i in 0..n0 {
            let row = self.interp_nd(
                &coords[1..],
                &axes[1..],
                &tensor[i * sub..(i + 1) * sub],
                linear_extrap,
                cubic,
            );
            rows.push(row);
        }
        if cubic {
            self.interp_1d_spline(coords[0], &axes[0], &rows, linear_extrap)
        } else {
            self.interp_1d_values(coords[0], &axes[0], &rows, linear_extrap)
        }
    }

    /// Lowers `$table_model(x1, ..., xn, <data>[, "ctrl"])` to differentiable MIR: reads the
    /// compile-time grid (inline array or data file), lowers each coordinate, and multilinearly
    /// interpolates via `interp_nd`, so `mir_autodiff` supplies the per-axis slope as the Jacobian.
    ///
    /// Enhancement-40: the dimension is derived from the argument SHAPES rather than the
    /// resolved signature, so tables of any dimension work (1-3D were previously hard-coded):
    /// an array as the second argument means the 1-D inline form; otherwise every argument up
    /// to the first string literal is a coordinate, the string literal is the data-file name,
    /// and one further trailing string literal is the control string.
    fn lower_table_model(&mut self, args: &[ExprId]) -> Value {
        // Enhancement-389: the RUNTIME-ARRAY form `$table_model(x, xs, ys[, "ctrl"])`
        // (LRM p274), where the data arrives as two array *variables* filled in by the
        // body rather than as a compile-time literal or a data file. Detected by the
        // data arguments being bare array references, which inference resolved to
        // element variables; everything below this point is the compile-time path and
        // is untouched.
        if args.len() >= 3 && self.body.array_var_ref(args[1]).is_some() {
            if self.body.array_var_ref(args[2]).is_some() {
                let grid = self.lower_array_elems_impl(args[1], true);
                let vals = self.lower_array_elems_impl(args[2], true);
                // A shorter y than x would index past the end; the extra abscissae
                // describe no data, so drop them rather than fault.
                let n = grid.len().min(vals.len());
                let (linear_extrap, cubic) =
                    match args.get(3).and_then(|&a| self.body.as_literal(a)) {
                        Some(Literal::String(ctrl)) => {
                            (ctrl.contains('L') || ctrl.contains('l'), ctrl.contains('3'))
                        }
                        _ => (false, false),
                    };
                let x = self.lower_expr(args[0]);
                // Enhancement-390: sort as the compile-time forms do, and honour the
                // cubic control code instead of silently interpolating linearly.
                let (mut grid, mut vals) = (grid[..n].to_vec(), vals[..n].to_vec());
                self.sort_pairs_runtime(&mut grid, &mut vals);
                return if cubic {
                    self.interp_1d_spline_runtime(x, &grid, &vals, linear_extrap)
                } else {
                    self.interp_1d_runtime(x, &grid, &vals, linear_extrap)
                };
            }
        }

        let is_str =
            |sel: &Self, e: ExprId| matches!(sel.body.as_literal(e), Some(Literal::String(_)));
        let (ndim, is_file, has_ctrl) = if matches!(self.body.get_expr(args[1]), Expr::Array(_)) {
            (1, false, args.len() > 2)
        } else {
            match (1..args.len()).find(|&i| is_str(self, args[i])) {
                Some(k) => (k, true, args.len() > k + 1),
                // defensive: no data argument at all (inference already diagnosed it)
                None => (1, false, false),
            }
        };

        // The control string selects extrapolation ('L' -> linear, else clamp) and interpolation
        // degree ('3' -> natural cubic spline, else multilinear). Following Enhancement-16/17's
        // simplification, a code found anywhere applies to all axes (per-axis codes are future work).
        let (linear_extrap, cubic) = if has_ctrl {
            let ctrl = self.body.as_literal(args[ndim + 1]).unwrap().unwrap_str();
            (ctrl.contains('L') || ctrl.contains('l'), ctrl.contains('3'))
        } else {
            (false, false)
        };

        // read the grid into per-axis coordinate vectors + a row-major value tensor
        let (axes, tensor) = if is_file && ndim >= 2 {
            let fname = self.body.as_literal(args[ndim]).unwrap().unwrap_str();
            match self.read_table_grid_nd(fname, ndim) {
                Some(g) => g,
                None => return F_ZERO,
            }
        } else {
            // 1-D: inline `{x0,y0,...}` pairs or a two-column data file
            let mut pts: Vec<(f64, f64)> = if is_file {
                let fname = self.body.as_literal(args[1]).unwrap().unwrap_str();
                self.read_noise_table_file(fname)
            } else {
                match self.body.get_expr(args[1]) {
                    Expr::Array(vals) => {
                        let nums: Vec<f64> =
                            vals.iter().map(|&e| self.eval_const_real(e).unwrap_or(0.0)).collect();
                        nums.chunks_exact(2).map(|c| (c[0], c[1])).collect()
                    }
                    _ => Vec::new(),
                }
            };
            pts.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            pts.dedup_by(|a, b| a.0 == b.0);
            (vec![pts.iter().map(|p| p.0).collect()], pts.iter().map(|p| p.1).collect())
        };

        if axes.iter().any(|a| a.is_empty()) {
            return F_ZERO;
        }

        let mut coords = Vec::with_capacity(ndim);
        for i in 0..ndim {
            coords.push(self.lower_expr(args[i]));
        }
        self.interp_nd(&coords, &axes, &tensor, linear_extrap, cubic)
    }

    fn lower_builtin(&mut self, expr: ExprId, builtin: BuiltIn, args: &[ExprId]) -> Value {
        let signature = self.body.get_call_signature(expr);
        match builtin {
            BuiltIn::abs => {
                let (negate, comparison, zero, is_real) = match_signature!(signature:
                    ABS_REAL => (Opcode::Fneg, Opcode::Flt,  F_ZERO, true),
                    ABS_INT => (Opcode::Ineg, Opcode::Ilt, ZERO, false)
                );
                let val = self.lower_expr(args[0]);
                let (inst, dfg) = self.ctx.ins().binary(comparison, val, zero);
                let cond = dfg.first_result(inst);

                self.lower_select_with(
                    cond,
                    |sel| {
                        let (inst, dfg) = sel.ctx.ins().unary(negate, val);
                        dfg.first_result(inst)
                    },
                    // `x < 0 ? -x : x` is |x| for every real EXCEPT negative
                    // zero: `-0.0 < 0.0` is false, so -0.0 fell through the
                    // else branch unchanged and `abs(-0.0)` came out NEGATIVE.
                    // That is observable -- `1.0/abs(-0.0)` gave -inf where the
                    // compiler's own constant folding gave +inf for the same
                    // expression, so the two disagreed on the sign of infinity.
                    // Adding +0.0 normalises it: (-0.0) + 0.0 is +0.0 under
                    // round-to-nearest, and `x + 0.0` is x for every other
                    // value, NaN and the infinities included. (LLVM cannot fold
                    // this add away for exactly the reason it is here.)
                    |sel| {
                        if is_real {
                            sel.ctx.ins().fadd(val, F_ZERO)
                        } else {
                            val
                        }
                    },
                )
            }
            BuiltIn::acos => {
                let arg0 = self.lower_expr(args[0]);
                let mag = self.lower_fabs(arg0);
                let ok = self.ctx.ins().fle(mag, F_ONE);
                let not_nan = self.ctx.ins().feq(arg0, arg0);
                let ok = self.ctx.ins().iand(ok, not_nan);
                let arg0 =
                    self.guard_arg_domain("acos", "values in [-1, 1]", args[0], arg0, ok, F_ZERO);
                self.ctx.ins().acos(arg0)
            }
            BuiltIn::acosh => {
                let arg0 = self.lower_expr(args[0]);
                let ok = self.ctx.ins().fge(arg0, F_ONE);
                let arg0 =
                    self.guard_arg_domain("acosh", "values >= 1", args[0], arg0, ok, F_ONE);
                self.ctx.ins().acosh(arg0)
            }
            BuiltIn::asin => {
                let arg0 = self.lower_expr(args[0]);
                let mag = self.lower_fabs(arg0);
                let ok = self.ctx.ins().fle(mag, F_ONE);
                let not_nan = self.ctx.ins().feq(arg0, arg0);
                let ok = self.ctx.ins().iand(ok, not_nan);
                let arg0 =
                    self.guard_arg_domain("asin", "values in [-1, 1]", args[0], arg0, ok, F_ZERO);
                self.ctx.ins().asin(arg0)
            }
            BuiltIn::asinh => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().asinh(arg0)
            }
            BuiltIn::atan => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().atan(arg0)
            }
            BuiltIn::atan2 => {
                let arg0 = self.lower_expr(args[0]);
                let arg1 = self.lower_expr(args[1]);
                self.ctx.ins().atan2(arg0, arg1)
            }
            BuiltIn::atanh => {
                let arg0 = self.lower_expr(args[0]);
                let mag = self.lower_fabs(arg0);
                let ok = self.ctx.ins().flt(mag, F_ONE);
                let not_nan = self.ctx.ins().feq(arg0, arg0);
                let ok = self.ctx.ins().iand(ok, not_nan);
                let arg0 =
                    self.guard_arg_domain("atanh", "values in (-1, 1)", args[0], arg0, ok, F_ZERO);
                self.ctx.ins().atanh(arg0)
            }
            BuiltIn::cos => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().cos(arg0)
            }
            BuiltIn::cosh => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().cosh(arg0)
            }
            BuiltIn::exp => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().exp(arg0)
            }

            // `limexp` is implemented as a stateless cutoff-linearised exponential:
            // exp(x) below `ln(1e30)`, continued along its tangent line above it so
            // the value and derivative stay finite. This bounds the derivative and
            // prevents overflow (the practical benefit of `limexp`) while keeping
            // the value an exact function of the current argument.
            //
            // A *stateful* prev-iteration step-limiting version (pnjlim-style) was
            // deliberately NOT adopted: to keep the converged value correct it needs
            // SPICE's limiting-RHS correction (`lim_rhs = J(x_lim)(x_lim - x)`), and
            // OpenVAF's `lim_rhs` (see `sim_back/dae/builder.rs`) only applies to
            // values that are circuit *unknowns* -- `limexp`'s argument is a derived
            // quantity (e.g. `V/Vt`), so the correction is skipped and the DC value
            // comes out wrong (verified: a diode I-V sweep was incorrect at many
            // bias points). Doing it correctly would require extending `lim_rhs` to
            // limit derived arguments via the chain rule to the underlying unknowns.
            BuiltIn::limexp => {
                let arg0 = self.lower_expr(args[0]);
                let cut_off = self.ctx.fconst(1e30f64.ln());
                let off = self.ctx.fconst(1e30f64);

                let linearize = self.ctx.ins().fgt(arg0, cut_off);
                self.ctx.make_select(linearize, |func, linearize| {
                    if linearize {
                        let delta = func.ins().fsub(arg0, cut_off);
                        let lin = func.ins().fmul(off, delta);
                        func.ins().fadd(off, lin)
                    } else {
                        func.ins().exp(arg0)
                    }
                })
            }
            BuiltIn::floor => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().floor(arg0)
            }
            BuiltIn::hypot => {
                let arg0 = self.lower_expr(args[0]);
                let arg1 = self.lower_expr(args[1]);
                self.ctx.ins().hypot(arg0, arg1)
            }
            BuiltIn::ln => {
                let arg0 = self.lower_expr(args[0]);
                let ok = self.ctx.ins().fgt(arg0, F_ZERO);
                let arg0 =
                    self.guard_arg_domain("ln", "values > 0", args[0], arg0, ok, F_ONE);
                self.ctx.ins().ln(arg0)
            }
            // LRM 4.3.1: ln1p(x) = ln(1+x) and expm1(x) = e^x - 1, each with its
            // own opcode so the libm routine keeps the precision near x=0 that is
            // the reason the LRM lists them apart from ln/exp.
            BuiltIn::ln1p => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().ln1p(arg0)
            }
            BuiltIn::expm1 => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().expm1(arg0)
            }
            BuiltIn::sin => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().sin(arg0)
            }
            BuiltIn::sinh => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().sinh(arg0)
            }
            BuiltIn::sqrt => {
                let arg0 = self.lower_expr(args[0]);
                let ok = self.ctx.ins().fge(arg0, F_ZERO);
                let arg0 =
                    self.guard_arg_domain("sqrt", "values >= 0", args[0], arg0, ok, F_ZERO);
                self.ctx.ins().sqrt(arg0)
            }
            BuiltIn::tan => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().tan(arg0)
            }
            BuiltIn::tanh => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().tanh(arg0)
            }
            BuiltIn::clog2 => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().clog2(arg0)
            }
            BuiltIn::log10 | BuiltIn::log => {
                let arg0 = self.lower_expr(args[0]);
                let ok = self.ctx.ins().fgt(arg0, F_ZERO);
                let name = if builtin == BuiltIn::log { "log" } else { "log10" };
                let arg0 = self.guard_arg_domain(name, "values > 0", args[0], arg0, ok, F_ONE);
                self.ctx.ins().log(arg0)
            }
            BuiltIn::ceil => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().ceil(arg0)
            }

            BuiltIn::max => {
                let comparison = match_signature!(signature: MAX_REAL => InstBuilder::fgt, MAX_INT => InstBuilder::igt);
                let arg0 = self.lower_expr(args[0]);
                let arg1 = self.lower_expr(args[1]);
                let cond = comparison(self.ctx.ins(), arg0, arg1);
                self.lower_select_with(cond, |_| arg0, |_| arg1)
            }
            BuiltIn::min => {
                let comparison = match_signature!(signature: MAX_REAL => InstBuilder::flt, MAX_INT => InstBuilder::ilt);
                let arg0 = self.lower_expr(args[0]);
                let arg1 = self.lower_expr(args[1]);
                let cond = comparison(self.ctx.ins(), arg0, arg1);
                self.lower_select_with(cond, |_| arg0, |_| arg1)
            }
            BuiltIn::pow => {
                let arg0 = self.lower_expr(args[0]);
                let arg1 = self.lower_expr(args[1]);
                let arg0 = self.guard_pow_base(args[0], args[1], arg0, arg1);
                self.ctx.ins().pow(arg0, arg1)
            }

            BuiltIn::write => {
                self.ins_display(DisplayKind::Display, false, args, PrintDst::Console, None);
                GRAVESTONE
            }
            BuiltIn::display | BuiltIn::strobe | BuiltIn::monitor => {
                self.ins_display(DisplayKind::Display, true, args, PrintDst::Console, None);
                GRAVESTONE
            }
            BuiltIn::debug => {
                self.ins_display(DisplayKind::Debug, true, args, PrintDst::Console, None);
                GRAVESTONE
            }

            BuiltIn::warning => {
                self.ins_display(DisplayKind::Warn, true, args, PrintDst::Console, None);
                GRAVESTONE
            }
            BuiltIn::error => {
                self.ins_display(DisplayKind::Error, true, args, PrintDst::Console, None);
                GRAVESTONE
            }
            BuiltIn::info => {
                self.ins_display(DisplayKind::Info, true, args, PrintDst::Console, None);
                GRAVESTONE
            }

            // Enhancement-11: file-output system functions. Each takes the file
            // descriptor as its first argument (`args[0]`) and formats the rest
            // exactly like the matching console `$display`-family function, but
            // routes the text to the descriptor. `$fwrite` omits the trailing
            // newline; `$fstrobe`/`$fmonitor` are treated as `$fdisplay` (a
            // single write per evaluation -- see Enhancement-11.md).
            BuiltIn::fwrite => {
                let fd = self.lower_expr(args[0]);
                self.ins_display(DisplayKind::Display, false, &args[1..], PrintDst::File, Some(fd));
                GRAVESTONE
            }
            BuiltIn::fdisplay | BuiltIn::fstrobe | BuiltIn::fmonitor => {
                let fd = self.lower_expr(args[0]);
                self.ins_display(DisplayKind::Display, true, &args[1..], PrintDst::File, Some(fd));
                GRAVESTONE
            }
            BuiltIn::fdebug => {
                let fd = self.lower_expr(args[0]);
                self.ins_display(DisplayKind::Debug, true, &args[1..], PrintDst::File, Some(fd));
                GRAVESTONE
            }

            // Enhancement-11: string-formatting and file-reading functions.
            // `$swrite`/`$sformat` format into the destination string variable
            // (`args[0]`); the rest format exactly like `$write` (`$sformat`'s
            // format string is simply its first value argument). `$fgets` reads a
            // line into the destination string and returns its length. `$sscanf`/
            // `$fscanf` parse whitespace-delimited fields into their argument
            // variables. See Enhancement-11.md.
            BuiltIn::swrite | BuiltIn::sformat => {
                let dst_var = self.body.into_variable(args[0]);
                let s = self
                    .ins_display(DisplayKind::Display, false, &args[1..], PrintDst::String, None)
                    .unwrap();
                self.ctx.def_place(PlaceKind::Var(dst_var), s);
                GRAVESTONE
            }
            BuiltIn::fgets => {
                // $fgets(str, fd): read a line into `str`, return its length.
                let dst_var = self.body.into_variable(args[0]);
                let fd = self.lower_expr(args[1]);
                let line = self.ctx.call1(CallBackKind::Fgets, &[fd]);
                self.ctx.def_place(PlaceKind::Var(dst_var), line);
                self.ctx.call1(CallBackKind::StrLen, &[line])
            }
            BuiltIn::ferror => {
                // $ferror(fd, str): fill `str` with the error message, return the
                // error code.
                let fd = self.lower_expr(args[0]);
                let dst_var = self.body.into_variable(args[1]);
                let msg = self.ctx.call1(CallBackKind::FerrorMsg, &[fd]);
                self.ctx.def_place(PlaceKind::Var(dst_var), msg);
                self.ctx.call1(CallBackKind::FerrorCode, &[fd])
            }
            BuiltIn::sscanf => {
                let input = self.lower_expr(args[0]);
                self.lower_scanf(input, args[1], &args[2..])
            }
            BuiltIn::fscanf => {
                // Read one line from the descriptor, then scan it like $sscanf.
                let fd = self.lower_expr(args[0]);
                let input = self.ctx.call1(CallBackKind::Fgets, &[fd]);
                self.lower_scanf(input, args[1], &args[2..])
            }

            // Enhancement-12/215: connectivity-aliasing and plusarg functions. The
            // node/port alias functions still have no OSDI/ngspice mechanism and
            // lower to their LRM "mechanism-unavailable" constant (see
            // Enhancement-12.md). The plusarg functions ARE now served, through the
            // simparam string channel (Enhancement-215): ngspice injects each
            // command-line plusarg `+name[=value]` as two namespaced simparams --
            // numeric `$test$plusargs$name` = 1.0 (presence) and string
            // `$value$plusargs$name` = "value". The name/format is a compile-time
            // literal, so the namespaced key is built here.
            BuiltIn::test_plusargs => {
                // `$test$plusargs("name")` -> is `+name` (or `+name=...`) present?
                let name = self.body.as_literal(args[0]).unwrap().unwrap_str();
                let key = self.ctx.sconst(&format!("$test$plusargs${name}"));
                let present = self.ctx.call1(CallBackKind::SimParamOpt, &[key, F_ZERO]);
                // 1.0 present / 0.0 absent -> Bool
                self.ctx.ins().fne(present, F_ZERO)
            }
            BuiltIn::value_plusargs => {
                // `$value$plusargs("name=%fmt", var)`: if `+name=<v>` is present, put
                // <v> into `var` (parsed per the target's type) and return 1, else 0.
                // The plusarg key is the format text before the first `%`, with a
                // leading `+` and trailing `=`/whitespace stripped. ngspice provides
                // each plusarg's value on three op-dependent simparam channels --
                // presence ($test$plusargs$name = 1), the value as a number
                // ($valnum$plusargs$name) and as a string ($value$plusargs$name) --
                // so the value is read directly by target type, with no dependence on
                // the $sscanf global-cursor machinery (which the setup/eval
                // partitioner can split from its inputs).
                let fmt = self.body.as_literal(args[0]).unwrap().unwrap_str().to_owned();
                let name = fmt
                    .split('%')
                    .next()
                    .unwrap_or("")
                    .trim()
                    .trim_start_matches('+')
                    .trim_end_matches(|c| c == '=' || c == ' ');
                // `$value$plusargs` matches only the `name=value` form, so its
                // return keys off $valset (set iff a value was given), not the
                // plain presence that $test$plusargs uses.
                let present_key = self.ctx.sconst(&format!("$valset$plusargs${name}"));
                let present = self.ctx.call1(CallBackKind::SimParamOpt, &[present_key, F_ZERO]);

                let var = self.body.into_variable(args[1]);
                let val = match self.body.expr_type(args[1]) {
                    Type::String => {
                        let key = self.ctx.sconst(&format!("$value$plusargs${name}"));
                        let empty = self.ctx.sconst("");
                        self.ctx.call1(CallBackKind::SimParamStrOpt, &[key, empty])
                    }
                    Type::Integer => {
                        let key = self.ctx.sconst(&format!("$valnum$plusargs${name}"));
                        let num = self.ctx.call1(CallBackKind::SimParamOpt, &[key, F_ZERO]);
                        self.ctx.ins().ficast(num)
                    }
                    _ => {
                        let key = self.ctx.sconst(&format!("$valnum$plusargs${name}"));
                        self.ctx.call1(CallBackKind::SimParamOpt, &[key, F_ZERO])
                    }
                };
                self.ctx.def_place(PlaceKind::Var(var), val);
                // return 1 when the plusarg was present, else 0
                self.ctx.ins().fne(present, F_ZERO)
            }
            // `$analog_node_alias`/`$analog_port_alias` -> 0 (no alias created).
            BuiltIn::analog_node_alias | BuiltIn::analog_port_alias => ZERO,
            // `$simprobe(inst, quantity [, default])` -> the supplied default, or
            // 0.0 when the probe is unavailable and no default was given.
            BuiltIn::simprobe => {
                if args.len() >= 3 {
                    self.lower_expr(args[2])
                } else {
                    F_ZERO
                }
            }
            BuiltIn::fopen => {
                // $fopen(name) / $fopen(name, mode). A missing mode defaults to
                // "w" so the runtime always receives a (name, mode) pair.
                let name = self.lower_expr(args[0]);
                let mode = if args.len() > 1 {
                    self.lower_expr(args[1])
                } else {
                    self.ctx.sconst("w")
                };
                self.ctx.call1(CallBackKind::Fopen, &[name, mode])
            }
            BuiltIn::fclose => self.lower_file_op(FileOp::Close, args),
            BuiltIn::feof => self.lower_file_op(FileOp::Eof, args),
            BuiltIn::ftell => self.lower_file_op(FileOp::Tell, args),
            BuiltIn::rewind => self.lower_file_op(FileOp::Rewind, args),
            // Enhancement-107: `$fgetc(fd)` -- read one character.
            BuiltIn::fgetc => self.lower_file_op(FileOp::Getc, args),
            // Enhancement-108: `$ungetc(c, fd)` -- push a character back.
            BuiltIn::ungetc => self.lower_file_op(FileOp::Ungetc, args),
            BuiltIn::fseek => self.lower_file_op(FileOp::Seek, args),
            BuiltIn::fflush => {
                // $fflush() flushes all descriptors; $fflush(fd) flushes one.
                let op = if args.is_empty() { FileOp::FlushAll } else { FileOp::Flush };
                self.lower_file_op(op, args)
            }

            BuiltIn::fatal => {
                self.ins_display(DisplayKind::Fatal, true, args, PrintDst::Console, None);
                // Fatal code is 0 (used for translation MIR->IR)
                let call_args = vec![];
                self.ctx.call(CallBackKind::SetRetFlag(RetFlag::Abort), &call_args);
                // Enhancement-324: `$fatal` sets its return flag and CONTINUES, exactly
                // like `$finish`/`$stop` below. It used to emit `exit()` and then switch
                // lowering into a freshly created, predecessor-less "unreachable" block.
                // That was unsound for a compiled device: the OSDI eval function has a
                // mandatory epilogue (store residual/jacobian outputs) which the ABI
                // requires to run, and every ret-flag -- Abort, Finish, Stop -- is only a
                // flag the simulator inspects AFTER eval returns; none of them can
                // longjmp out of the middle of an evaluation. Terminating the MIR
                // function early therefore left the epilogue, and any statement written
                // after `$fatal`, stranded in a block with no incoming edges:
                //   * `$fatal(0); V(a) <+ 1.0;`  -- the contribution was lowered into the
                //     unreachable block, but stayed referenced by the contribution
                //     bookkeeping, so aggressive DCE hit an instruction that belongs to
                //     no block (`inst_block(inst).unwrap()`, dead_code_aggressive.rs).
                //   * `V(a) <+ 2.0; $fatal(0);`  -- the epilogue itself landed in the
                //     unreachable block, where the residual value does not dominate, so
                //     codegen read an `Undef` (`BuilderVal::get`, mir_llvm/builder.rs).
                // Both crashed the SHIPPED compiler. Setting the flag and falling through
                // keeps the CFG connected, so neither situation can arise.
                GRAVESTONE
            }
            BuiltIn::analysis => {
                // Enhancement-30: `analysis(arg1, arg2, ...)` is true if the current
                // analysis matches ANY listed name. OR the per-argument results together
                // (bitwise OR, not a sum: several flags can be set at once -- e.g. both
                // "static" and "dc" hold at an operating point -- so a sum could exceed 1).
                let mut acc: Option<Value> = None;
                for &arg in args {
                    let name = self.lower_expr(arg);
                    let hit = self.ctx.call1(CallBackKind::Analysis, &[name]);
                    acc = Some(match acc {
                        None => hit,
                        Some(prev) => self.ctx.ins().ior(prev, hit),
                    });
                }
                // `min_args == 1` guarantees at least one argument.
                acc.unwrap()
            }

            BuiltIn::noise_table
            | BuiltIn::noise_table_log
            | BuiltIn::white_noise
            | BuiltIn::ac_stim
            | BuiltIn::flicker_noise
                if self.ctx.no_equations =>
            {
                F_ZERO
            }

            // `ac_stim([name][, mag][, phase])` (Enhancement-51, completing the E-26
            // deferral): a small-signal AC stimulus source. Zero in the large-signal
            // domain; injects `mag∠phase` (phase in radians, defaults 1∠0) into the AC
            // RHS when the small-signal analysis matches `name` (default "ac"). Rides
            // the noise-source extraction pipeline via a dedicated callback per call
            // site, exactly like `white_noise`.
            BuiltIn::ac_stim => {
                let idx = self.ctx.num_noise_sources;
                self.ctx.num_noise_sources += 1;
                let name = if signature == AC_STIM_UNIT {
                    self.ctx.func.interner.get_or_intern("ac")
                } else {
                    let name = self.body.as_literal(args[0]).unwrap().unwrap_str();
                    self.ctx.func.interner.get_or_intern(name)
                };
                let mag = if signature == AC_STIM_UNIT || signature == AC_STIMT_NAME {
                    F_ONE
                } else {
                    self.lower_expr(args[1])
                };
                let phase = if signature == AC_STIM_NAME_MAG_PHASE {
                    self.lower_expr(args[2])
                } else {
                    F_ZERO
                };
                self.ctx.call1(CallBackKind::AcStim { name, idx }, &[mag, phase])
            }

            BuiltIn::white_noise => {
                // we create a dedicated callback for each noise source
                // by giving every source a unique index. Kind of ineffcient
                // but necessary to avoid accidental correlation/opimization
                // (for example white_noise(x) - white_noise(x) is not zero)
                let idx = self.ctx.num_noise_sources;
                self.ctx.num_noise_sources += 1;
                let name = if signature == WHITE_NOISE_NAME {
                    let name = self.body.as_literal(args[1]).unwrap().unwrap_str();
                    self.ctx.func.interner.get_or_intern(name)
                } else {
                    let name = format!("unnamed{idx}");
                    self.ctx.func.interner.get_or_intern(name)
                };
                let pwr = self.lower_noise_power(args[0]);
                self.ctx.call1(CallBackKind::WhiteNoise { name, idx }, &[pwr])
            }
            BuiltIn::flicker_noise => {
                // see above
                let idx = self.ctx.num_noise_sources;
                self.ctx.num_noise_sources += 1;
                let name = if signature == FLICKER_NOISE_NAME {
                    let name = self.body.as_literal(args[2]).unwrap().unwrap_str();
                    self.ctx.func.interner.get_or_intern(name)
                } else {
                    let name = format!("unnamed{idx}");
                    self.ctx.func.interner.get_or_intern(name)
                };
                let pwr = self.lower_noise_power(args[0]);
                let exp = self.lower_expr(args[1]);
                let (pwr, exp) = self.guard_flicker_args(pwr, exp); // Enhancement-506
                self.ctx.call1(CallBackKind::FlickerNoise { name, idx }, &[pwr, exp])
            }
            BuiltIn::noise_table | BuiltIn::noise_table_log => {
                // see above
                let idx = self.ctx.num_noise_sources;
                self.ctx.num_noise_sources += 1;
                let name = if matches!(signature, NOISE_TABLE_INLINE_NAME | NOISE_TABLE_FILE_NAME) {
                    let name = self.body.as_literal(args[1]).unwrap().unwrap_str();
                    self.ctx.func.interner.get_or_intern(name)
                } else {
                    let name = format!("unnamed{idx}");
                    self.ctx.func.interner.get_or_intern(name)
                };
                let log = builtin == BuiltIn::noise_table_log;
                let table_vals = self.noise_table_data(signature, args);
                let noise_table = NoiseTable::new(table_vals, log, name, idx);
                self.ctx.call1(CallBackKind::NoiseTable(Box::new(noise_table)), &[])
            }

            BuiltIn::table_model => self.lower_table_model(args),

            BuiltIn::abstime => self.ctx.use_param(ParamKind::Abstime),
            // Enhancement-59: $realtime aliases $abstime (no `timescale in Verilog-A)
            BuiltIn::realtime => self.ctx.use_param(ParamKind::Abstime),

            // Enhancement-104: $rtoi truncates toward zero (LRM), unlike the
            // implicit real->int cast which rounds. trunc(x) = (x<0) ? ceil(x) :
            // floor(x); the result is an exact integer-valued real, so ficast
            // (round-to-nearest) yields it exactly. $itor is a plain int->real.
            BuiltIn::rtoi => {
                let val = self.lower_expr(args[0]);
                let cond = self.ctx.ins().flt(val, F_ZERO);
                let trunc = self.lower_select_with(
                    cond,
                    |sel| sel.ctx.ins().ceil(val),
                    |sel| sel.ctx.ins().floor(val),
                );
                self.ctx.ins().ficast(trunc)
            }
            BuiltIn::itor => {
                let val = self.lower_expr(args[0]);
                self.ctx.ins().ifcast(val)
            }

            BuiltIn::ddt => {
                if self.ctx.no_equations {
                    return F_ZERO;
                }
                let arg = self.lower_expr(args[0]);
                self.ctx.call1(CallBackKind::TimeDerivative, &[arg])
            }

            BuiltIn::idt | BuiltIn::idtmod if self.ctx.no_equations => {
                match signature {
                    IDT_NO_IC => F_ZERO, // fair enough approximation
                    _ => self.lower_expr(args[1]),
                }
            }

            BuiltIn::idt => {
                let kind = match_signature! {
                    signature:
                        IDT_NO_IC => IdtKind::Basic,
                        IDT_IC => IdtKind::Ic,
                        // we currently do not support tolerance
                        IDT_IC_ASSERT | IDT_IC_ASSERT_TOL | IDT_IC_ASSERT_NATURE => IdtKind::Assert
                };

                self.lower_integral(kind, args)
            }

            BuiltIn::idtmod => {
                let kind = match_signature! {
                    signature:
                        IDTMOD_NO_IC => IdtKind::Basic,
                        IDTMOD_IC => IdtKind::Ic,
                        IDTMOD_IC_MODULUS => IdtKind::Modulus,
                        // we currently do not support tolerance
                        IDTMOD_IC_MODULUS_OFFSET
                        | IDTMOD_IC_MODULUS_OFFSET_TOL
                        | IDTMOD_IC_MODULUS_OFFSET_NATURE => IdtKind::ModulusOffset
                };

                self.lower_integral(kind, args)
            }

            BuiltIn::flow => {
                let res = match_signature! {
                    signature:
                        NATURE_ACCESS_NODES|NATURE_ACCESS_NODE_GND => self.nodes_from_args(
                            args,
                            |hi, lo| ParamKind::Current(CurrentKind::Unnamed{hi,lo})
                        ),
                        NATURE_ACCESS_BRANCH => {
                            let branch = self.body.into_branch(args[0]);
                            // A named branch declared over a port (`branch (<p>) name;`,
                            // LRM 3.7.2) *is* the port's flow: route it through the same
                            // Port current param as a direct `I(<p>)` so
                            // build_port_flow_equations defines it.
                            let kind = match branch.kind(self.ctx.db) {
                                hir::BranchKind::PortFlow(node) => CurrentKind::Port(node),
                                _ => CurrentKind::Branch(branch),
                            };
                            self.ctx.use_param(ParamKind::Current(kind))
                        },
                        NATURE_ACCESS_PORT_FLOW => self.ctx.use_param(ParamKind::Current(
                            CurrentKind::Port(self.body.into_port_flow(args[0]))
                        ))
                };
                // AB: Do not divide flow probe.
                //     Flow unknowns correspond to the flow of a single parallel instance.
                //     HIR equation describes a single parallel instance.
                //     Handle $mfactor at a lower level.
                // let mfactor = self.ctx.use_param(ParamKind::ParamSysFun(ParamSysFun::mfactor));
                // return self.ctx.ins().fdiv(res, mfactor);
                return res;
            }
            BuiltIn::potential => {
                match_signature! {
                    signature:
                        NATURE_ACCESS_NODES|NATURE_ACCESS_NODE_GND => self.nodes_from_args( args, |hi,lo|ParamKind::Voltage{hi,lo}),
                        NATURE_ACCESS_BRANCH => {
                            let branch = self.body.into_branch(args[0]).kind(self.ctx.db);
                            self.ctx.nodes(branch.unwrap_hi_node(), branch.lo_node(), |hi, lo| ParamKind::Voltage{ hi, lo })
                        }
                }
            }
            BuiltIn::vt => {
                // TODO make this a database input
                const KB: f64 = 1.3806488e-23;
                const Q: f64 = 1.602176565e-19;

                let fac = self.ctx.fconst(KB / Q);
                let temp = match args.get(0) {
                    Some(temp) => {
                        // Enhancement-509: an explicit absolute temperature from the
                        // deck. hir_ty refuses a literal `$vt(-300)` ("the absolute
                        // temperature must be greater than zero"); the same value as a
                        // `parameter` produced a NEGATIVE thermal voltage, which
                        // inverts every exponential built on it -- a conducting diode
                        // (-1.207e-04 A) became an open circuit (-6.0e-07 A, the shunt
                        // alone), silently and with exit code 0.
                        //
                        // The no-argument form is NOT guarded here: it reads the
                        // simulator's temperature, which ngspice already refuses below
                        // absolute zero ("Option temp = -300 C is at or below absolute
                        // zero; ignored, keeping 27 C").
                        let t = self.lower_expr(*temp);
                        let ok = self.ctx.ins().fgt(t, F_ZERO);
                        self.guard_arg_domain(
                            "$vt",
                            "an absolute temperature > 0",
                            *temp,
                            t,
                            ok,
                            F_ONE,
                        )
                    }
                    None => self.ctx.use_param(ParamKind::Temperature),
                };

                self.ctx.ins().fmul(fac, temp)
            }

            BuiltIn::ddx => {
                let val = self.lower_expr(args[0]);
                let unknown = self.lower_expr(args[1]);

                // Enhancement-327: the unknown does NOT always lower to a bare Param, so
                // unwrapping one unconditionally crashed the SHIPPED compiler ("Value is
                // not a parameter") on legal input. `LoweringCtx::nodes` can yield:
                //   * a Param        -- a forward-oriented probe, e.g. V(a,b) or V(a)
                //   * `fneg(param)`  -- a REVERSE-oriented probe, e.g. V(b,a) (the same
                //                       branch with the opposite reference direction, or
                //                       a probe whose high side is ground)
                //   * F_ZERO         -- a probe of ground only, which is not an unknown
                //                       of the DAE system at all
                // Both extra shapes are legal and have an obvious derivative, so they
                // must COMPILE rather than error: V(b,a) == -V(a,b), hence
                // df/dV(b,a) == -(df/dV(a,b)); and df/d(ground) == 0.
                let mut negate = false;
                let mut probe = unknown;
                if let Some(inst) = self.ctx.dfg().value_def(probe).inst() {
                    if let InstructionData::Unary { opcode: Opcode::Fneg, arg } =
                        self.ctx.dfg().insts[inst]
                    {
                        negate = true;
                        probe = arg;
                    }
                }

                match self.ctx.dfg().value_def(probe).as_param() {
                    // Not an unknown of the system (ground, or a probe that collapsed to
                    // a constant): the derivative is identically zero.
                    None => F_ZERO,
                    Some(param) => {
                        let call = if signature == DDX_POT {
                            match self.ctx.param_kind(param).pot_node() {
                                Some(node) => CallBackKind::NodeDerivative(node),
                                // a single-node potential that is not a plain node
                                // potential cannot be an unknown either
                                None => return F_ZERO,
                            }
                        } else {
                            CallBackKind::Derivative(param)
                        };
                        let res = self.ctx.call1(call, &[val]);
                        if negate {
                            self.ctx.ins().fneg(res)
                        } else {
                            res
                        }
                    }
                }
            }
            BuiltIn::temperature => self.ctx.use_param(ParamKind::Temperature),
            BuiltIn::simparam => {
                let arg0 = self.lower_expr(args[0]);
                match_signature! {signature:
                    SIMPARAM_NO_DEFAULT => self.ctx.call1(CallBackKind::SimParam, &[arg0]),
                    SIMPARAM_DEFAULT => {
                        let arg1 = self.lower_expr(args[1]);
                        self.ctx.call1(CallBackKind::SimParamOpt, &[arg0, arg1])
                    }
                }
            }
            BuiltIn::simparam_str => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.call1(CallBackKind::SimParamStr, &[arg0])
            }
            // Enhancement-398: a parameter a `paramset` bound WAS given -- by the
            // paramset. It is a localparam, so it has no runtime given-flag and
            // `ParamGiven` resolved to false, which meant a model gating on
            // `$param_given` took its DEFAULT branch while running the
            // paramset's value. That is the standard CMC idiom for "did the user
            // specify this, or is this my default?", so every such derivation
            // silently took the wrong branch through a paramset.
            BuiltIn::param_given => {
                let param = self.body.into_parameter(args[0]);
                if param.is_paramset_bound(self.ctx.db) {
                    self.ctx.iconst(1)
                } else {
                    self.ctx.use_param(ParamKind::ParamGiven { param })
                }
            }
            BuiltIn::port_connected => {
                self.ctx.use_param(ParamKind::PortConnected { port: self.body.into_node(args[0]) })
            }
            BuiltIn::bound_step => {
                // Enhancement-504: a non-positive step bound must never be written.
                //
                // The field this writes is shared with Enhancement-24's sentinel,
                // where a NEGATIVE value does not mean "bound the step to this"
                // but "a $discontinuity happened here". A model that passes a
                // negative to $bound_step therefore did not merely ask for
                // something meaningless -- it announced a discontinuity on every
                // evaluation, and the transient never returned.
                //
                // hir_ty's require_positive refuses a negative it can SEE, but it
                // only sees a literal or a localparam; the ordinary case is a
                // `parameter` overridden from the deck, which the compiler cannot
                // refuse. So a non-positive or non-finite bound is dropped here
                // and the incumbent bound stands, which is what "no constraint
                // from this call" has always meant (the place defaults to
                // INFINITY). Zero is dropped for the same reason: a zero-length
                // step is not a bound a solver can honour.
                let step_size = self.lower_expr(args[0]);
                let zero = self.ctx.fconst(0.0);
                let usable = self.ctx.ins().fgt(step_size, zero); // false for 0, <0 and NaN
                let cur = self.ctx.use_place(PlaceKind::BoundStep);
                let bound = self
                    .ctx
                    .make_select(usable, |_, branch| if branch { step_size } else { cur });
                self.ctx.def_place(PlaceKind::BoundStep, bound);
                GRAVESTONE
            }

            BuiltIn::limit if signature == LIMIT_BUILTIN_FUNCTION && !self.ctx.no_equations => {
                let new_val = self.lower_expr(args[0]);
                let state = self.ctx.start_limit(new_val);
                let prev_val = self.ctx.use_param(ParamKind::PrevState(state));
                let name = self.body.as_literal(args[1]).unwrap().unwrap_str();
                let name = self.ctx.func.interner.get_or_intern(name);
                let mut call_args = vec![new_val, prev_val];
                call_args.extend(args[2..].iter().map(|arg| self.lower_expr(*arg)));

                let enable_lim = self.ctx.use_param(ParamKind::EnableLim);
                let res = self.ctx.make_select(enable_lim, |func, lim| {
                    if lim {
                        func.call1(
                            CallBackKind::BuiltinLimit { name, num_args: args.len() as u32 },
                            &call_args,
                        )
                    } else {
                        new_val
                    }
                });

                self.ctx.finish_limit(state, res)
            }
            BuiltIn::discontinuity => {
                // AB: Negative literals are represented as UnaryOp::Neg(Literal)
                //     We have a function for that now.
                //
                // Enhancement-395: the argument is OPTIONAL -- the LRM writes
                // `$discontinuity [ ( constant_expression ) ]` -- and `args[0]`
                // was indexed unconditionally, so a bare `$discontinuity;` (or
                // `$discontinuity();`) panicked the compiler in release at
                // hir_lower/src/expr.rs. The arity table permits zero arguments,
                // so validation never caught it. Omitting the degree means 0,
                // the LRM's default: a step discontinuity in the value itself.
                // Enhancement-508: fold a named constant, and honour a run-time one.
                //
                // `as_literalsignedint` reads a LITERAL and nothing else, so a
                // `localparam integer d = -1;` did not fold -- and -1 is
                // Enhancement-24's sentinel for *no discontinuity*, so the branch
                // below took the announce path instead of the do-nothing one and
                // bounded the timestep on every crossing (168 output rows against
                // 132). `eval_const_real` folds the localparam chain.
                //
                // A `parameter` degree cannot be folded at all, and REFUSING one
                // would be wrong: Enhancement-504's own model writes
                // `parameter integer disc = -1; ... if (disc >= 0)
                // $discontinuity(disc);`, which is the deck-supplied route working
                // as designed. The degree only selects a branch, and that branch
                // can be selected at RUN TIME -- which is this audit's own rule: a
                // value that feeds a runtime decision may be a parameter, only a
                // COMPILE-TIME ARTIFACT may not. So a non-constant degree emits the
                // announcement under a run-time `degree != -1` test rather than
                // unconditionally.
                let degree = if args.is_empty() {
                    Some(0)
                } else {
                    self.body
                        .as_literalsignedint(&args[0])
                        .or_else(|| self.eval_const_real(args[0]).map(|v| v as i32))
                };
                if self.ctx.inside_lim && Some(-1) == degree {
                    self.ctx.call(CallBackKind::LimDiscontinuity, &[]);
                } else if degree.is_none() && !self.ctx.inside_lim {
                    // Enhancement-508: the degree is only known at run time. Announce
                    // exactly when it is not the -1 sentinel. `SetRetFlag` inside a
                    // conditional is the shape Enhancement-505 made op-dependent and
                    // Enhancement-506's `runtime_fatal` already relies on.
                    let deg = self.lower_expr(args[0]);
                    let deg = match self.body.expr_type(args[0]) {
                        Type::Integer => self.ctx.ins().ifcast(deg),
                        _ => deg,
                    };
                    let minus_one = self.ctx.fconst(-1.0);
                    let announce = self.ctx.ins().fne(deg, minus_one);
                    self.ctx.make_cond(announce, |ctx, is_announce| {
                        if is_announce {
                            let sentinel = ctx.fconst(-1.0);
                            ctx.def_place(PlaceKind::BoundStep, sentinel);
                            ctx.call(CallBackKind::SetRetFlag(RetFlag::Discont), &[]);
                        }
                    });
                } else if degree != Some(-1) {
                    // `$discontinuity(n)` for n >= 0 (Enhancement-24): announce a discontinuity of
                    // degree `n` so the simulator limits the transient timestep rather than
                    // extrapolating across the event. Implemented via the (proven) `bound_step`
                    // eval output: writing a negative sentinel signals ngspice's `OSDItrunc` to
                    // clamp the next timestep to the last accepted step. (The eval-return-flag path
                    // used by `$finish`/`$stop` is not honoured by ngspice's timestep control.)
                    let sentinel = self.ctx.fconst(-1.0);
                    self.ctx.def_place(PlaceKind::BoundStep, sentinel);
                    // Enhancement-55: additionally raise the DISCONT eval-return
                    // flag so the simulator can REJECT the current step and retry
                    // with a smaller one (the sentinel only bounds the NEXT step).
                    self.ctx.call(CallBackKind::SetRetFlag(RetFlag::Discont), &[]);
                }
                GRAVESTONE
            }
            BuiltIn::finish => {
                // Finish code is 1 (used for translation MIR->IR)
                let call_args = vec![];
                self.ctx.call(CallBackKind::SetRetFlag(RetFlag::Finish), &call_args);
                GRAVESTONE
            }

            BuiltIn::stop => {
                // Stop code is 2 (used for translation MIR->IR)
                let call_args = vec![];
                self.ctx.call(CallBackKind::SetRetFlag(RetFlag::Stop), &call_args);
                GRAVESTONE
            }

            BuiltIn::absdelay => {
                let y_expr = self.lower_expr(args[0]);
                let mut td = self.lower_expr(args[1]);
                if signature == ABSDELAY_MAX {
                    let tdmax = self.lower_expr(args[2]);
                    let use_td = self.ctx.ins().fle(td, tdmax);
                    td = self.lower_select_with(use_td, |_| td, |_| tdmax);
                }
                self.lower_delay(y_expr, td)
            }
            BuiltIn::limit => self.lower_expr(args[0]),

            BuiltIn::slew => self.lower_slew(args, signature),
            BuiltIn::transition => self.lower_transition(args, signature),

            BuiltIn::laplace_nd | BuiltIn::laplace_np | BuiltIn::laplace_zd
            | BuiltIn::laplace_zp => self.lower_laplace(builtin, args),

            BuiltIn::zi_nd | BuiltIn::zi_np | BuiltIn::zi_zd | BuiltIn::zi_zp => {
                self.lower_zi(builtin, args)
            }

            BuiltIn::last_crossing => self.lower_last_crossing(args, signature),

            // Enhancement-10: `$random`/`$arandom` and the `$dist_*`/`$rdist_*`
            // statistical-distribution system functions. Each lowers to a pure
            // `osdi_rng_*` runtime callback (see `RngFun`).
            //
            // Return types follow OpenVAF's builtin signature table: `$random`,
            // `$arandom` and -- since Enhancement-376 -- every `$dist_*` form are
            // `Integer`, while the `$rdist_*` family is `Real`. That is the LRM
            // split, and it is the reason the `$rdist_*` family exists at all.
            //
            // `osdi_rng_*` always returns a double, so every integer-typed form
            // ends in `ficast`. Where the draw is not already integral it is
            // ROUNDED FIRST (`rng_round_real` = floor(x+0.5), which is also correct
            // for negatives -- `$dist_t` and a zero-mean `$dist_normal` need that);
            // `ficast` then truncates an exactly-integral double, so it is
            // lossless. `UniformInt` and `Poisson` are already integral and are
            // only cast.
            //
            // Before Enhancement-376 these rounded but stayed `Real`, which made
            // LRM-conformant code such as `$display("%d", $dist_uniform(s,10,20))`
            // a compile error. Changing the signature table alone was NOT enough:
            // the lowering still produced a real value, which every downstream
            // integer consumer then read as 0.
            //
            // The `$dist_*` integer parameters are coerced to real for the shared
            // real-argument callbacks via `lower_num_as_real`.
            BuiltIn::random | BuiltIn::arandom => {
                let seed = self.lower_rng_seed(args);
                let r = self.lower_rng(expr, RngFun::Random, seed, &[]);
                self.ctx.ins().ficast(r)
            }
            BuiltIn::rdist_uniform => {
                let seed = self.lower_expr(args[0]);
                let a = self.lower_expr(args[1]);
                let b = self.lower_expr(args[2]);
                let b = self.clamp_upper_bound(a, b);          // Enhancement-505
                self.lower_rng(expr, RngFun::Uniform, seed, &[a, b])
            }
            // Enhancement-506: the INTEGER siblings below take Enhancement-505's
            // clamps too. `hir_ty` validates the two spellings together -- one arm
            // serves `rdist_normal | dist_normal` -- so a LITERAL out-of-domain
            // argument was refused for both, and only the ordinary deck-supplied
            // route reached the run time. There the clamps had gone to the
            // `$rdist_*` arms alone, so `$dist_exponential(seed, mean)` with a
            // deck-set mean of -1 returned deviates in -10..0: every sample
            // NEGATIVE, from a distribution whose support is [0, inf), while its
            // real sibling clamped to 0. `$dist_normal` returned the exact
            // NEGATION of the correct distribution and `$dist_uniform(s, 10, 0)`
            // drew from reversed bounds that `$rdist_uniform` refuses.
            BuiltIn::dist_uniform => {
                let seed = self.lower_expr(args[0]);
                let a = self.lower_num_as_real(args[1]);
                let b = self.lower_num_as_real(args[2]);
                let b = self.clamp_upper_bound(a, b);          // Enhancement-506
                // `UniformInt` already returns an integral (but real) value.
                let r = self.lower_rng(expr, RngFun::UniformInt, seed, &[a, b]);
                self.ctx.ins().ficast(r)
            }
            BuiltIn::rdist_normal => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                let sdev = self.lower_expr(args[2]);
                let sdev = self.clamp_non_negative(sdev);      // Enhancement-505
                self.lower_rng(expr, RngFun::Normal, seed, &[mean, sdev])
            }
            BuiltIn::dist_normal => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                let sdev = self.lower_num_as_real(args[2]);
                let sdev = self.clamp_non_negative(sdev);      // Enhancement-506
                let r = self.lower_rng(expr, RngFun::Normal, seed, &[mean, sdev]);
                let rr = self.rng_round_real(r);
                self.ctx.ins().ficast(rr)
            }
            BuiltIn::rdist_exponential => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                let mean = self.clamp_non_negative(mean);      // Enhancement-505
                self.lower_rng(expr, RngFun::Exponential, seed, &[mean])
            }
            BuiltIn::dist_exponential => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                let mean = self.clamp_non_negative(mean);      // Enhancement-506
                let r = self.lower_rng(expr, RngFun::Exponential, seed, &[mean]);
                let rr = self.rng_round_real(r);
                self.ctx.ins().ficast(rr)
            }
            BuiltIn::rdist_poisson => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                let mean = self.clamp_non_negative(mean);      // Enhancement-505
                // stays REAL: $rdist_* is the real-valued family (Enhancement-376)
                self.lower_rng(expr, RngFun::Poisson, seed, &[mean])
            }
            BuiltIn::dist_poisson => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                let mean = self.clamp_non_negative(mean);      // Enhancement-506
                // `Poisson` already returns an integral (but real) count.
                let r = self.lower_rng(expr, RngFun::Poisson, seed, &[mean]);
                self.ctx.ins().ficast(r)
            }
            BuiltIn::rdist_chi_square => {
                let seed = self.lower_expr(args[0]);
                let dof = self.lower_expr(args[1]);
                self.lower_rng(expr, RngFun::ChiSquare, seed, &[dof])
            }
            BuiltIn::dist_chi_square => {
                let seed = self.lower_expr(args[0]);
                let dof = self.lower_num_as_real(args[1]);
                let r = self.lower_rng(expr, RngFun::ChiSquare, seed, &[dof]);
                let rr = self.rng_round_real(r);
                self.ctx.ins().ficast(rr)
            }
            BuiltIn::rdist_t => {
                let seed = self.lower_expr(args[0]);
                let dof = self.lower_expr(args[1]);
                self.lower_rng(expr, RngFun::StudentT, seed, &[dof])
            }
            BuiltIn::dist_t => {
                let seed = self.lower_expr(args[0]);
                let dof = self.lower_num_as_real(args[1]);
                let r = self.lower_rng(expr, RngFun::StudentT, seed, &[dof]);
                let rr = self.rng_round_real(r);
                self.ctx.ins().ficast(rr)
            }
            BuiltIn::rdist_erlang => {
                let seed = self.lower_expr(args[0]);
                let k = self.lower_expr(args[1]);
                let mean = self.lower_expr(args[2]);
                self.lower_rng(expr, RngFun::Erlang, seed, &[k, mean])
            }
            BuiltIn::dist_erlang => {
                let seed = self.lower_expr(args[0]);
                let k = self.lower_num_as_real(args[1]);
                let mean = self.lower_num_as_real(args[2]);
                let r = self.lower_rng(expr, RngFun::Erlang, seed, &[k, mean]);
                let rr = self.rng_round_real(r);
                self.ctx.ins().ficast(rr)
            }

        }
    }

    /// Lowers a file-descriptor operation (`$fclose`/`$feof`/`$ftell`/`$rewind`/
    /// `$fseek`/`$fflush`, Enhancement-11): every argument is an integer, and the
    /// runtime callback returns an integer status/result.
    fn lower_file_op(&mut self, op: FileOp, args: &[ExprId]) -> Value {
        let call_args: Vec<Value> = args.iter().map(|&a| self.lower_expr(a)).collect();
        self.ctx.call1(CallBackKind::FileOp(op), &call_args)
    }

    /// Lowers the field-parsing shared by `$sscanf`/`$fscanf` (Enhancement-11):
    /// begins a parse over `input`, then pulls one whitespace-delimited field per
    /// target variable (the runtime parses each token by the variable's type, not
    /// by the format string) and stores it. Returns the number of successful
    /// conversions. `var_args` are the destination variable references.
    fn lower_scanf(&mut self, input: Value, fmt: ExprId, var_args: &[ExprId]) -> Value {
        self.ctx.call(CallBackKind::ScanBegin, &[input]);
        // Enhancement-105: the conversion character of each field selects the
        // integer base -- `%h` hex, `%o` octal, `%b` binary; anything else keeps
        // strtol's base-0 auto-detection. The format string is normally a
        // literal; if it is not, every field falls back to the default
        // `Int`/`Real`/`Str` chosen from the destination variable's type.
        let convs: Vec<char> = match self.body.as_literal(fmt) {
            Some(Literal::String(s)) => scanf_conversion_chars(s),
            _ => Vec::new(),
        };
        for (i, &arg) in var_args.iter().enumerate() {
            // Enhancement-507: the value the destination already holds. It is
            // passed INTO the scanner, which hands it straight back when the
            // field does not convert, so an unmatched argument is left alone as
            // C and IEEE 1364 require.
            //
            // It must be read with `read_variable`, the same call an ordinary
            // variable read lowers to. The destination arrives here as an OUTPUT
            // reference, so `lower_expr` on it is not a read at all and produced
            // a module that segfaulted the simulator the moment the variable had
            // not already been assigned; `use_place(PlaceKind::Var)` did the
            // same. The value is passed as an ARGUMENT rather than selected on a
            // separate "did it match" callback: that version needed two extra
            // blocks per destination and had the same fault, which is E-505's
            // lesson about adding control flow around a call whose operands live
            // elsewhere.
            let var = self.body.into_variable(arg);
            let kind = match self.body.expr_type(arg) {
                Type::Integer => match convs.get(i) {
                    // `%h`/`%H` is the Verilog hex conversion; `%x`/`%X` (the C
                    // spelling) is accepted too for convenience.
                    Some('h' | 'H' | 'x' | 'X') => ScanKind::IntHex,
                    Some('o' | 'O') => ScanKind::IntOct,
                    Some('b' | 'B') => ScanKind::IntBin,
                    _ => ScanKind::Int,
                },
                Type::Real => ScanKind::Real,
                Type::String => ScanKind::Str,
                ty => unreachable!("invalid $sscanf target type {ty:?}"),
            };
            // The fallback is the destination's current value -- but ONLY when
            // the variable already has one in this function. Reading a variable
            // that has never been assigned declares `PlaceKind::Var`, whose
            // initialiser is `ParamKind::HiddenState`: it turns the destination
            // into persistent instance state the backend does not provide for a
            // scanf target, and the generated module segfaults the simulator the
            // first time such a model is evaluated. `get_place` answers exactly
            // the question that distinguishes the two, and where there is no
            // prior definition the "previous value" IS the implicit zero, so
            // handing the scanner a zero is not an approximation.
            let prev = match self.ctx.get_place(PlaceKind::Var(var)) {
                Some(place) => self.ctx.func.use_var(place),
                None => match kind {
                    ScanKind::Real => F_ZERO,
                    ScanKind::Str => self.ctx.sconst(""),
                    _ => self.ctx.iconst(0),
                },
            };
            let val = self.ctx.call1(CallBackKind::Scan(kind), &[prev]);
            self.ctx.def_place(PlaceKind::Var(var), val);
        }
        self.ctx.call1(CallBackKind::ScanCount, &[])
    }

    /// Lowers the (optional) seed argument shared by `$random`/`$arandom`: the
    /// seedless forms have no argument and default to `0` (the per-call-site salt
    /// added in `lower_rng` still decorrelates distinct call sites). The seeded
    /// and const-seed forms both carry the seed as `args[0]`.
    fn lower_rng_seed(&mut self, args: &[ExprId]) -> Value {
        if args.is_empty() {
            self.ctx.iconst(0)
        } else {
            self.lower_expr(args[0])
        }
    }

    /// Lowers a numeric distribution parameter and guarantees a real (`double`)
    /// value for the `osdi_rng_*` callback. Whether `lower_expr` yields an integer
    /// or a real depends on the matched signature's argument requirement (the
    /// `$dist_*` forms are nominally integer, but at least one upstream const-seed
    /// signature mixes in a `Val(Real)`), so the coercion is driven by the actual
    /// post-lowering type rather than the builtin family.
    fn lower_num_as_real(&mut self, arg: ExprId) -> Value {
        let is_int = match self.body.needs_cast(arg) {
            Some((_, dst)) => matches!(dst, Type::Integer),
            None => matches!(self.body.expr_type(arg), Type::Integer),
        };
        let val = self.lower_expr(arg);
        if is_int {
            self.ctx.ins().ifcast(val)
        } else {
            val
        }
    }

    /// Emits the `osdi_rng_*` callback for `fun`. The call arguments are
    /// `(seed, salt, real_params...)` where `salt` is the call `ExprId` (a stable,
    /// unique per-call-site constant that decorrelates independent draws). Returns
    /// the raw real result; integer-returning builtins cast/round it themselves.
    /// Enhancement-395: advances the caller's seed VARIABLE, giving the seed the
    /// `inout` semantics the LRM specifies for every `$random`/`$dist_*` form.
    ///
    /// Without this the draw was a pure function of `(seed, salt)`, and `salt` is
    /// a per-CALL-SITE constant -- so a call inside a loop had loop-invariant
    /// arguments, was hoisted, and returned THE SAME VALUE on every iteration. A
    /// Monte-Carlo loop drew N identical samples. Distinct call sites differed
    /// (distinct salt), which is exactly what hid it: straight-line model code
    /// looked correct.
    ///
    /// The advance is the classic LCG step, computed in the model rather than
    /// through a new callback so the OSDI ABI is untouched. `osdi_rng_state`
    /// avalanche-mixes `(seed, salt)`, so consecutive LCG seeds decorrelate fully.
    /// Writing the variable also makes the draw genuinely loop-variant, which is
    /// what stops it being hoisted.
    fn lower_rng(
        &mut self,
        expr: ExprId,
        fun: RngFun,
        seed: Value,
        real_params: &[Value],
    ) -> Value {
        let salt = self.ctx.iconst(u32::from(expr) as i32);
        let mut cb_args = Vec::with_capacity(2 + real_params.len());
        cb_args.push(seed);
        cb_args.push(salt);
        cb_args.extend_from_slice(real_params);
        self.ctx.call1(CallBackKind::Rng(fun), &cb_args)
    }

    /// Rounds a real random draw to the nearest integer (round half up) for the
    /// integer-valued `$dist_*` forms. The result stays a *real* value because
    /// OpenVAF types every `$dist_*` function as `Real` (see the lowering block
    /// above) -- only the numeric value is quantised to an integer.
    fn rng_round_real(&mut self, val: Value) -> Value {
        let half = self.ctx.fconst(0.5);
        let shifted = self.ctx.ins().fadd(val, half);
        self.ctx.ins().floor(shifted)
    }

    /// Lowers `last_crossing(expr[, dir])`: returns the simulation time of the most recent
    /// zero-crossing of `expr`'s value (`dir < 0`: falling only, `dir > 0`: rising only,
    /// `dir == 0`/omitted: either direction).
    ///
    /// Like `absdelay`, this needs the simulator's own accepted-timepoint history (the crossing
    /// time is a function of the entire past trajectory of `expr`, not something derivable from
    /// its instantaneous value) -- so the pattern mirrors `absdelay` exactly: a synthetic input
    /// node `y_synth` whose resistive residual enforces `V(y_synth) = expr` (so the simulator can
    /// read `expr`'s converged value at each accepted timepoint via the OSDI node mapping), and
    /// an output node `z` whose row is left entirely unstamped here -- the simulator fills it in
    /// (`OsdiLastCrossingInfo`, mirroring `OsdiAbsDelayInfo`). Unlike `absdelay`'s output, `z`'s
    /// value has zero sensitivity to `y_synth` almost everywhere (the crossing time is locally
    /// constant in time between crossings), so -- unlike absdelay -- the simulator never needs to
    /// stamp a `J[z, y]` coupling term, only `J[z, z] = -1` and the crossing-time RHS.
    fn lower_last_crossing(&mut self, args: &[ExprId], signature: hir::Signature) -> Value {
        let watched = self.lower_expr(args[0]);
        let dir = if signature == LAST_CROSSING_DIRECTION {
            // `dir` is `Val(Integer)` per the signature; the storage place is
            // `Real`-typed (like all other simulator-read instance-data fields),
            // so it needs an explicit int->real cast here.
            let dir_int = self.lower_expr(args[1]);
            let dir = self.ctx.ins().ifcast(dir_int);
            self.guard_event_direction("last_crossing", dir) // Enhancement-506
        } else {
            debug_assert_eq!(signature, LAST_CROSSING_NO_DIRECTION);
            F_ZERO
        };

        let idx = self.ctx.intern.last_crossing_equations.len() as u32;
        let (eq_y, y_val) =
            self.ctx.implicit_equation(ImplicitEquationKind::LastCrossingInput(idx));
        let (eq_z, z_val) =
            self.ctx.implicit_equation(ImplicitEquationKind::LastCrossingOutput(idx));
        self.ctx.intern.last_crossing_equations.push((eq_y, eq_z));

        let resist_y = self.ctx.ins().fsub(watched, y_val);
        self.ctx.def_resist_residual(resist_y, eq_y);

        self.ctx.def_place(PlaceKind::LastCrossingDirection(idx), dir);

        z_val
    }

    /// Lowers the shared `absdelay`-style pure delay: a synthetic input node enforcing
    /// `V(y_synth) = y_expr`, and an output node whose equation row is stamped entirely by
    /// the simulator via history lookup at `now - td`. Shared by `absdelay()` directly and by
    /// `transition()`'s delay stage.
    fn lower_delay(&mut self, y_expr: Value, td: Value) -> Value {
        let delay_idx = self.ctx.intern.absdelay_equations.len() as u32;

        // Synthetic input node: equation V(y_synth) = y_expr
        let (eq_y, y_val) =
            self.ctx.implicit_equation(ImplicitEquationKind::AbsDelayInput(delay_idx));
        // Output node: equation stamped entirely by the simulator (history lookup)
        let (eq_z, z_val) =
            self.ctx.implicit_equation(ImplicitEquationKind::AbsDelayOutput(delay_idx));

        self.ctx.intern.absdelay_equations.push((eq_y, eq_z));

        // Resistive residual for eq_y: y_expr - V(y_synth) = 0
        let resist_y = self.ctx.ins().fsub(y_expr, y_val);
        self.ctx.def_resist_residual(resist_y, eq_y);

        // Store td so the simulator can read it during matrix stamping
        self.ctx.def_place(PlaceKind::AbsDelayTime(delay_idx), td);

        // The delay result is V(z); eq_z's equation is handled by the simulator
        z_val
    }

    /// Lowers `slew(x[, max_pos_rate[, max_neg_rate]])`.
    ///
    /// Verilog-AMS defines `slew` as an ideal rate limiter: the output tracks `x` exactly
    /// whenever the required rate of change is within bounds, and otherwise ramps at the
    /// bound. That ideal (non-smooth, "bang-bang") behavior is not directly expressible as a
    /// well-posed continuous residual (the DC operating point would be left undetermined by a
    /// pure `dy/dt = clamp(...)` formulation, since any `y` satisfies `dy/dt = 0` at DC).
    /// Instead this uses the standard modeling trick of a saturating tracking loop:
    /// `dy/dt = clamp(K*(x - y), -max_neg_rate, max_pos_rate)` for a large gain `K`. This is
    /// well-posed at DC (`y = x` uniquely, since `K` is large) and reproduces the rate-limited
    /// ramp whenever `x` moves faster than the bound allows, converging to the ideal limiter as
    /// `K -> infinity`.
    fn lower_slew(&mut self, args: &[ExprId], signature: hir::Signature) -> Value {
        let x = self.lower_expr(args[0]);
        if signature == SLEW_NO_MAX {
            return x;
        }
        // LRM sign convention: `max_pos_slew_rate` shall be positive and
        // `max_neg_slew_rate` NEGATIVE (`slew(V(in), 1e6, -1e6)`), and with a
        // single rate its absolute value bounds both directions. Taking |.| of
        // each argument (Enhancement-61) is exact for conformant inputs and
        // also tolerates the positive-magnitude spelling: before this, an
        // LRM-conformant negative third argument was negated into a POSITIVE
        // lower clamp bound, turning the tracking loop into a `+max_neg_rate`
        // runaway ramp that ignored the input entirely.
        let (pos_max, neg_max) = if signature == SLEW_POS_MAX {
            let rate = self.lower_expr(args[1]);
            (rate, rate)
        } else {
            debug_assert_eq!(signature, SLEW_NEG_MAX);
            (self.lower_expr(args[1]), self.lower_expr(args[2]))
        };
        let pos_max = self.lower_fabs(pos_max);
        let neg_max = self.lower_fabs(neg_max);
        let idx = self.ctx.intern.implicit_equations.len() as u32;
        self.lower_rate_limited_track(x, pos_max, neg_max, ImplicitEquationKind::Slew(idx))
    }

    /// |x| via neg/lt/select (MIR has no fabs instruction).
    /// Is this argument fixed for the whole run (Enhancement-509)?
    fn is_param_derived(&self, expr: ExprId) -> bool {
        param_derived_in_body(self.ctx.db, self.body, expr, 0) == Some(true)
    }

    /// Enhancement-509: refuse an out-of-domain argument that came from the DECK.
    ///
    /// `hir_ty` refuses these domains when it can SEE the value -- a literal or a
    /// `localparam` -- with a message that names the builtin, the value and the
    /// domain. The identical value written on a model card is a `parameter`,
    /// which is deliberately not folded (Enhancement-426: the deck may replace
    /// it), so it reached libm untouched and came back `nan`/`inf`. In an
    /// operating-point variable that is silent with exit code 0; in a residual it
    /// surfaces as "Timestep too small; cause unrecorded" -- naming neither this
    /// model nor this call, which is the same complaint Enhancement-504 records.
    ///
    /// `ok` must be FALSE for NaN as well (`fgt`/`fge` both are, `flt` negated is
    /// not -- Enhancement-502's trap), and `safe` is substituted only so this one
    /// evaluation stamps finite numbers; the abort flag is read after eval
    /// returns (Enhancement-324).
    ///
    /// Only emitted for a parameter-derived argument. A runtime quantity is left
    /// alone on purpose: `sqrt(V(p,n))` goes briefly negative during Newton
    /// iteration in working models, and refusing that would break them.
    fn guard_arg_domain(
        &mut self,
        name: &str,
        domain: &str,
        arg: ExprId,
        val: Value,
        ok: Value,
        safe: Value,
    ) -> Value {
        if !self.is_param_derived(arg) {
            return val;
        }
        let msg = format!("{name}: the argument is outside the domain of {name} ({domain}); it is");
        self.ctx.make_select(ok, |ctx, branch| {
            if branch {
                val
            } else {
                ctx.runtime_fatal(&msg, Some(val));
                safe
            }
        })
    }

    /// Enhancement-509: the two real-`pow` domain holes, guarded for a
    /// deck-supplied base/exponent.
    ///
    /// `hir_ty` refuses both for a value it can see: a negative base with a
    /// fractional exponent (no real root) and a zero base with a negative
    /// exponent (a division by zero). Enhancement-489 added the same pair for the
    /// `**` spelling because it lowers through a DIFFERENT path; both call this.
    /// Returns a safe base, so the exponent is left exactly as written.
    fn guard_pow_base(&mut self, base_e: ExprId, exp_e: ExprId, base: Value, exp: Value) -> Value {
        // BOTH operands have to be fixed for the run (the condition tests them
        // together), and at least one has to carry a deck value -- `pow(q, 0.5)`
        // with a parameter base and a literal exponent is the ordinary spelling
        // of the finding, so requiring a parameter on both sides would miss it.
        let (b, e) = (
            param_derived_in_body(self.ctx.db, self.body, base_e, 0),
            param_derived_in_body(self.ctx.db, self.body, exp_e, 0),
        );
        let guard = match (b, e) {
            (Some(b_param), Some(e_param)) => b_param || e_param,
            _ => false,
        };
        if !guard {
            return base;
        }
        let base_neg = self.ctx.ins().flt(base, F_ZERO);
        let exp_floor = self.ctx.ins().floor(exp);
        let exp_frac = self.ctx.ins().fne(exp_floor, exp);
        let bad_root = self.ctx.ins().iand(base_neg, exp_frac);

        let base_zero = self.ctx.ins().feq(base, F_ZERO);
        let exp_neg = self.ctx.ins().flt(exp, F_ZERO);
        let bad_div = self.ctx.ins().iand(base_zero, exp_neg);

        let bad = self.ctx.ins().ior(bad_root, bad_div);
        let ok = self.ctx.ins().inot(bad);
        let msg = "pow: the base has no real power for this exponent; the base is";
        self.ctx.make_select(ok, |ctx, branch| {
            if branch {
                base
            } else {
                ctx.runtime_fatal(msg, Some(base));
                F_ONE
            }
        })
    }

    fn lower_fabs(&mut self, x: Value) -> Value {
        let neg = self.ctx.ins().fneg(x);
        let is_neg = self.ctx.ins().flt(x, F_ZERO);
        self.lower_select_with(is_neg, |_| neg, |_| x)
    }

    /// Lowers `transition(x[, td[, trise[, tfall[, tol]]]])` as a delayed
    /// (`` `lower_delay ``), rate-limited (`` `lower_rate_limited_track ``) tracking loop:
    /// `slew(absdelay(x, td), 1/trise, 1/tfall)`. `trise`/`tfall` are transition *times* in the
    /// LRM (time to ramp across a full-scale change), so they are converted to rates by
    /// assuming a unit-amplitude transition (`rate = 1/t`) -- exact for the common case of a
    /// comparator-style 0/1 input, an approximation for arbitrary-amplitude inputs. `tol`, when
    /// present, is accepted for signature compatibility but has no numerical effect (same
    /// convention as `laplace_*`'s trailing tolerance argument).
    fn lower_transition(&mut self, args: &[ExprId], signature: hir::Signature) -> Value {
        // the input is Real-typed since Enhancement-49 (integer inputs arrive
        // through the standard implicit promotion) -- no manual cast
        let x = self.lower_expr(args[0]);
        // `` `default_transition `` (Enhancement-47): when the rise/fall
        // arguments are omitted, ramp with the directive's time instead of
        // switching instantaneously (0, the LRM default without a directive).
        let t_default = self.ctx.db.default_transition();
        if signature == TRANSITION_NO_ARGS {
            if t_default <= 0.0 {
                return x;
            }
            let rate = self.ctx.fconst(1.0 / t_default);
            let idx = self.ctx.intern.implicit_equations.len() as u32;
            return self.lower_rate_limited_track(
                x,
                rate,
                rate,
                ImplicitEquationKind::Transition(idx),
            );
        }

        let td = self.lower_expr(args[1]);
        let delayed = self.lower_delay(x, td);
        if signature == TRANSITION_DELAY {
            if t_default <= 0.0 {
                return delayed;
            }
            let rate = self.ctx.fconst(1.0 / t_default);
            let idx = self.ctx.intern.implicit_equations.len() as u32;
            return self.lower_rate_limited_track(
                delayed,
                rate,
                rate,
                ImplicitEquationKind::Transition(idx),
            );
        }

        let trise = self.lower_expr(args[2]);
        let tfall = if signature == TRANSITION_DELAY_RISET {
            trise
        } else {
            debug_assert!(
                signature == TRANSITION_DELAY_RISET_FALLT
                    || signature == TRANSITION_DELAY_RISET_FALLT_TOL
            );
            self.lower_expr(args[3])
        };
        // Enhancement-504: a negative rise/fall time must not reach the reciprocal.
        //
        // `pos_max` is 1/trise and bounds `dy/dt` from ABOVE in the tracking loop
        // below; with a negative trise that bound goes negative and the clamp is
        // inverted, so the loop integrates AWAY from the input instead of towards
        // it. A 0->1 signal then reached -24 V, and it is unbounded -- -120 V over
        // a longer run, and larger still as |trise| shrinks, because the runaway
        // rate is 1/|trise|.
        //
        // hir_ty's require_non_negative already refuses a negative it can SEE, but
        // it only sees a literal or a localparam. The ordinary case is a model
        // whose `parameter real tr = 0.5n` is overridden from the deck, which the
        // compiler cannot refuse (a default is the author's business) and which
        // nothing checked afterwards.
        //
        // Clamped to zero rather than to |trise|: zero is the projection onto the
        // domain the LRM states, it is already what `transition` means with the
        // argument omitted, and 1/0 = +inf disables the rate limit exactly as an
        // instantaneous transition should. Guessing that a negative time "meant"
        // its magnitude would be inventing intent. `slew` needs no such clamp --
        // it applies lower_fabs to both rates just above, for its own reasons.
        let t_zero = self.ctx.fconst(0.0);
        let trise = {
            let pos = self.ctx.ins().fgt(trise, t_zero);   // false for 0 and for NaN
            self.ctx.make_select(pos, |_, branch| if branch { trise } else { t_zero })
        };
        let tfall = {
            let pos = self.ctx.ins().fgt(tfall, t_zero);
            self.ctx.make_select(pos, |_, branch| if branch { tfall } else { t_zero })
        };
        let f_one = self.ctx.fconst(1.0);
        let pos_max = self.ctx.ins().fdiv(f_one, trise);
        let neg_max = self.ctx.ins().fdiv(f_one, tfall);

        let idx = self.ctx.intern.implicit_equations.len() as u32;
        self.lower_rate_limited_track(delayed, pos_max, neg_max, ImplicitEquationKind::Transition(idx))
    }

    /// Shared saturating tracking-loop realization for `slew`/`transition`: a single implicit
    /// state `y` with `dy/dt = clamp(K*(x - y), -neg_max, pos_max)`. See `lower_slew` for the
    /// numerical rationale.
    fn lower_rate_limited_track(
        &mut self,
        x: Value,
        pos_max: Value,
        neg_max: Value,
        kind: ImplicitEquationKind,
    ) -> Value {
        // Enhancement-512: the tracking gain is RELATIVE to the transition rate,
        // not a fixed absolute constant.
        //
        // The loop is `dy/dt = clamp(K*(x-y), -neg_max, +pos_max)`. While the
        // clamp is saturated this is an exact linear ramp at the LRM's rate; it
        // releases once the remaining gap falls below `rate/K`, and the rest of
        // the swing is a first-order tail with tau = 1/K. With K a fixed 1e9/s
        // that gap was `1/(K*trise)` -- which depends on how fast the transition
        // is, so the operator was effectively exact for a microsecond edge and
        // materially wrong for a nanosecond one:
        //
        //     trise    linear part    value at delay+trise  (LRM: 1.0)
        //      3 ns       66.7%            0.8774
        //     30 ns       96.7%            0.9873
        //      3 us      ~100%             1.000039
        //
        // (the shortfall is e^-1/(K*trise), measured 0.877382 against 0.877374
        // predicted at 3 ns). `default_transition` pins the 1 us case, deep
        // inside the correct region, which is why it never surfaced there.
        //
        // Setting K = TRACK_C * rate makes the released gap `1/TRACK_C` at EVERY
        // speed, so the linear fraction is scale-invariant and the tail is a
        // fixed fraction of the transition rather than a fixed 1 ns.
        //
        // TRACK_C is 1e3 by measurement, not by taste, and the trade-off is real
        // in BOTH directions. The released gap 1/TRACK_C bounds the endpoint
        // error, so a larger constant looks better in isolation -- but it also
        // shortens the tail's time constant (tau = trise/TRACK_C) and a stiffer
        // loop costs accuracy at a realistic timestep, through truncation error
        // at the corner where the ramp meets the tail. Measured on
        // Enhancement-47's plateau check, which samples three arities at once:
        //
        //     TRACK_C     plateau (want 0.875)
        //       1e3           0.875      (passes, 1e-6 tolerance)
        //       1e4           0.874940
        //       1e5           0.874766
        //
        // So it gets WORSE above 1e3, not better. At 1e3 the endpoint error is
        // 2e-5..4e-4 across five decades of trise (it was 12.3% at 3 ns), the
        // settled value is exactly 1.0, and timepoint counts and runtime are
        // unchanged. Do not raise this without re-running `defaulttransition`.
        const TRACK_C: f64 = 1.0e3;
        // Enhancement-504 clamps a negative rise/fall time to ZERO, whose
        // reciprocal is +inf -- that is how an instantaneous transition disables
        // the rate limit. `TRACK_C * inf` is inf, and `inf * 0.0` is NaN, so the
        // gain has to stay finite for that case: it falls back to the fixed
        // 1e9/s this loop used before, which is exactly the behaviour E-504's
        // suite measured for an instantaneous transition. A merely FAST finite
        // rate is far below the guard (trise = 1 ps gives 1e15) and is untouched.
        const TRACK_GAIN_INF: f64 = 1.0e9;
        const HUGE: f64 = 1.0e300;

        let (eq, y) = self.ctx.implicit_equation(kind);
        let c = self.ctx.fconst(TRACK_C);
        let huge = self.ctx.fconst(HUGE);
        let g_inf = self.ctx.fconst(TRACK_GAIN_INF);
        let diff = self.ctx.ins().fsub(x, y);
        let finite_gain = |s: &mut Self, k: Value| {
            let ok = s.ctx.ins().flt(k, huge);      // false for +inf and for NaN
            s.lower_select_with(ok, |_| k, |_| g_inf)
        };
        // ONE gain for both directions, taken from the FASTER rate. A gain that
        // switched with the sign of `x - y` was tried and rejected: it makes the
        // loop dynamics jump exactly at the crossing point, and an asymmetric
        // `transition(x, td, 0.5n, -0.5n)` -- one edge instantaneous, the other
        // finite -- then overshot to 1.01 and recovered on the far slower
        // fallback gain, which is a regression against Enhancement-504's suite.
        // Taking the faster rate makes the slower direction stiffer than it
        // needs to be, which costs the integrator nothing measurable here and
        // *reduces* overshoot, since the ringing amplitude is bounded by the gap
        // at which the clamp releases (`rate/K`).
        let faster = self.ctx.ins().fgt(pos_max, neg_max);
        let rate_max = self.lower_select_with(faster, |_| pos_max, |_| neg_max);
        let gain = self.ctx.ins().fmul(c, rate_max);
        let gain = finite_gain(self, gain);
        let rate = self.ctx.ins().fmul(gain, diff);

        let neg_max = self.ctx.ins().fneg(neg_max);
        let too_low = self.ctx.ins().flt(rate, neg_max);
        let rate = self.lower_select_with(too_low, |_| neg_max, |_| rate);
        let too_high = self.ctx.ins().fgt(rate, pos_max);
        let rate = self.lower_select_with(too_high, |_| pos_max, |_| rate);

        // In DC the filter is an identity (`y = x`, the LRM's static behavior);
        // the rate-limited form must not be used there -- a saturated clamp has
        // a zero derivative w.r.t. `y`, so the DC Jacobian diagonal vanished
        // and the operating point was singular whenever the input started a
        // full swing away from `y` (Enhancement-47).
        let enable_integration = self.ctx.use_param(ParamKind::EnableIntegration);
        let track = self.ctx.ins().fneg(rate);
        let identity = self.ctx.ins().fsub(y, x);
        let resist = self.lower_select_with(enable_integration, |_| track, |_| identity);
        self.ctx.def_resist_residual(resist, eq);
        let react = self.lower_select_with(enable_integration, |_cx| y, |cx| cx.ctx.fconst(0.0));
        self.ctx.def_react_residual(react, eq);

        y
    }

    /// Lowers `laplace_nd`/`laplace_np`/`laplace_zd`/`laplace_zp(in, num_or_zero, den_or_pole
    /// [, tol|nature])`.
    ///
    /// The transfer function `H(s) = num(s)/den(s)` is converted at compile time into an
    /// equivalent controllable-canonical-form state-space realization (a small system of
    /// first-order ODEs), reusing the same `idt`-style implicit-equation + resistive/reactive
    /// residual machinery as the `idt()` builtin. The output is then a purely algebraic
    /// combination of the resulting state values, so this needs no special-casing anywhere
    /// downstream (`sim_back`/`osdi` treat the states as ordinary implicit unknowns).
    /// The optional trailing tolerance/nature argument is accepted for signature compatibility
    /// but has no effect: the realization is an exact algebraic transformation, not an
    /// approximation that could benefit from an error tolerance.
    /// Enhancement-506: the spelling the AUTHOR used, for a run-time diagnostic.
    /// `laplace_state_space` is shared by all four `laplace_*` forms and, through
    /// `lower_zi`, by all four `zi_*` forms, so a hardcoded name would point the
    /// author at a function their source does not mention -- the defect
    /// Enhancement-396 fixed for `noise_table_log` and Enhancement-506 fixes for
    /// the `$dist_*` family.
    fn filter_builtin_name(kind: BuiltIn) -> &'static str {
        match kind {
            BuiltIn::laplace_nd => "laplace_nd",
            BuiltIn::laplace_np => "laplace_np",
            BuiltIn::laplace_zd => "laplace_zd",
            BuiltIn::laplace_zp => "laplace_zp",
            BuiltIn::zi_nd => "zi_nd",
            BuiltIn::zi_np => "zi_np",
            BuiltIn::zi_zd => "zi_zd",
            _ => "zi_zp",
        }
    }

    fn lower_laplace(&mut self, kind: BuiltIn, args: &[ExprId]) -> Value {
        let input = self.lower_expr(args[0]);

        let num_is_roots = matches!(kind, BuiltIn::laplace_zd | BuiltIn::laplace_zp);
        let den_is_roots = matches!(kind, BuiltIn::laplace_np | BuiltIn::laplace_zp);

        let num = self.lower_coeff_elems(args[1]);
        let den = self.lower_coeff_elems(args[2]);

        let num = if num_is_roots { self.laplace_roots_to_poly(&num) } else { num };
        let den = if den_is_roots { self.laplace_roots_to_poly(&den) } else { den };

        self.laplace_state_space(Self::filter_builtin_name(kind), input, &num, &den)
    }

    /// Lowers an array-valued expression to its element `Value`s, in ascending order. Used by
    /// every context that consumes a whole array as a value: `laplace_*`/`zi_*` coefficient
    /// arguments, whole-array function arguments, and (Enhancement-33) `case` discriminants
    /// and case items. Two shapes are accepted (see `hir_ty::inference::infere_array_arg`):
    /// a bare reference to a module-body array variable, read directly via
    /// `ctx.read_variable` per element (no array-literal `ExprId`s exist for this case at
    /// all); or an ordinary array-literal expression (`'{a, b, c}'`/`{a, b, c}`), whose
    /// elements are lowered individually via `lower_expr` (falling back to treating the whole
    /// expression as a single-element array if it's neither — defensive, not expected to
    /// trigger given the type-level requirements).
    pub(crate) fn lower_array_elems(&mut self, expr: ExprId) -> Vec<Value> {
        self.lower_array_elems_impl(expr, false)
    }

    /// Like `lower_array_elems`, but every returned Value is guaranteed to be a real
    /// (double). A `laplace_*`/`zi_*` coefficient vector is real-valued (LRM 9.19), yet an
    /// array literal may hold integer-looking literals — `laplace_nd(x, '{1}, '{-p, 1})` —
    /// whose elements lower to *integer* Values. Feeding an integer into the float
    /// `fmul`/`fsub` of the state-space realization builds mixed-type MIR that the const
    /// evaluator panics on (`eval_binary` has no (Int, Float) case), so an integer-looking
    /// coefficient crashed the compiler. Cast each array-literal/concat element to real up
    /// front.
    ///
    /// This once claimed "(a whole-array *variable* reference is already real by its
    /// declaration, so the var-ref path needs no cast)". That does not hold for an *integer*
    /// array variable -- `integer c[0:0]; ... laplace_nd(V(a,b), c, '{1.0})` -- whose element
    /// reads are i32 and hit the very same mixed-type MIR ("invalid operation fdiv Int(1)
    /// .."). The var-ref path is coerced too, from the variable's declared type.
    fn lower_coeff_elems(&mut self, expr: ExprId) -> Vec<Value> {
        self.lower_array_elems_impl(expr, true)
    }

    pub(crate) fn lower_array_elems_impl(&mut self, expr: ExprId, coerce_real: bool) -> Vec<Value> {
        // When inference coerces a *whole array* -- an integer-literal `case` item tested
        // against a real discriminant, say -- `expect()` records the cast on the ARRAY
        // EXPRESSION itself. But every whole-array consumer comes through here, and this
        // function decomposes the array and lowers each element on its own, so
        // `lower_expr`'s `needs_cast()` never sees that cast: it was silently dead. That is
        // why one defect -- an integer value reaching a float MIR op, which the const
        // evaluator has no case for ("invalid operation feq/fmul Int(..) Float(..)") --
        // kept coming back in each new array context. Honouring the recorded cast here, at
        // the single chokepoint, makes inference's intent effective for every consumer
        // instead of requiring each call site to remember to ask.
        //
        // `coerce_real` remains for consumers whose element type is fixed by the language
        // rather than by an inferred cast (a `laplace_*`/`zi_*` coefficient vector is real
        // per LRM 9.19, and its inference records no cast).
        let coerce_real = coerce_real
            || matches!(self.body.needs_cast(expr), Some((_, dst)) if *dst.base_type() == Type::Real);

        // An array PARAMETER argument (LRM 4.5.1) -- the read-only twin of the
        // array-variable case below. Elements are parameter reads rather than
        // variable reads; everything downstream sees the same flat value list.
        if let Some(params) = self.body.array_param_ref(expr) {
            let mut res = Vec::with_capacity(params.len());
            for param in params {
                let val = self.ctx.use_param(ParamKind::Param(param));
                res.push(if coerce_real && param.ty(self.ctx.db) == Type::Integer {
                    self.ctx.ins().ifcast(val)
                } else {
                    val
                });
            }
            return res;
        }

        if let Some(vars) = self.body.array_var_ref(expr) {
            let mut res = Vec::with_capacity(vars.len());
            for var in vars {
                let val = self.ctx.read_variable(var);
                // An integer array variable's reads are i32; a real-valued consumer
                // (a laplace_*/zi_* coefficient vector) needs them as doubles.
                res.push(if coerce_real && var.ty(self.ctx.db) == Type::Integer {
                    self.ctx.ins().ifcast(val)
                } else {
                    val
                });
            }
            return res;
        }

        // Enhancement-34: a `{...}` concatenation / `{n{...}}` replication flattens its
        // operands in order — whole-array variables contribute element reads, nested
        // concatenations/aggregates recurse, scalars lower to a single value — and the
        // flattened list is repeated `n` times (the count is a validated integer literal).
        if let Expr::Concat { rep, elems } = self.body.get_expr(expr) {
            let elems = elems.to_vec();
            let mut unit = Vec::with_capacity(elems.len());
            for e in elems {
                if self.body.array_var_ref(e).is_some()
                    || matches!(self.body.get_expr(e), Expr::Concat { .. } | Expr::Array(_))
                {
                    unit.extend(self.lower_array_elems_impl(e, coerce_real));
                } else if coerce_real {
                    unit.push(self.lower_num_as_real(e));
                } else {
                    unit.push(self.lower_expr(e));
                }
            }
            let rep_cnt = rep
                .and_then(|r| match self.body.as_literal(r) {
                    Some(Literal::Int(n)) => Some(*n as usize),
                    _ => None,
                })
                .unwrap_or(1);
            if rep_cnt > 1 {
                let base = unit.clone();
                for _ in 1..rep_cnt {
                    unit.extend(base.iter().copied());
                }
            }
            return unit;
        }

        let elem_ids: Vec<ExprId> = match self.body.get_expr(expr) {
            Expr::Array(elems) => elems.to_vec(),
            _ => vec![expr],
        };
        elem_ids
            .iter()
            .map(|&e| if coerce_real { self.lower_num_as_real(e) } else { self.lower_expr(e) })
            .collect()
    }

    /// Expands a list of **complex** roots into ascending-power *real* polynomial coefficients
    /// of `Π_k (1 - s/r_k)`, i.e. `poly[i]` is the coefficient of `s^i`.
    ///
    /// This is the LAPLACE normalisation, in which the root DIVIDES. The z-domain forms need
    /// `Π_k (1 - rho_k * z^-1)`, in which it MULTIPLIES -- see [`Self::zi_roots_to_poly`].
    /// Enhancement-405: this header used to say `Π (s - r_k)`, describing behaviour that
    /// E-395 had already replaced one comment further down.
    ///
    /// Enhancement-31: per the Verilog-AMS LRM the pole/zero vectors of the `*_zp`/`*_np`/`*_zd`
    /// forms hold **(real, imaginary) pairs** -- element `2k` is the real part and `2k+1` the
    /// imaginary part of root `k`. The product is formed with full complex arithmetic (each
    /// coefficient carried as a `(re, im)` pair of `Value`s) and only the **real** coefficients
    /// are returned. For a physical (real-coefficient) transfer function the roots come in
    /// conjugate pairs, so the imaginary parts of the product cancel to zero -- taking the real
    /// part both realises that and harmlessly drops floating round-off. A trailing unpaired
    /// element (odd-length vector) is treated as a purely real root, so a lone real root may
    /// still be written `'{r}` as well as `'{r, 0}`.
    fn laplace_roots_to_poly(&mut self, roots: &[Value]) -> Vec<Value> {
        // Coefficients as (real, imaginary) `Value`s, ascending powers; start at `1 + 0j`.
        let mut re = vec![F_ONE];
        let mut im = vec![F_ZERO];
        let mut k = 0;
        while k < roots.len() {
            let rr = roots[k];
            let ri = if k + 1 < roots.len() { roots[k + 1] } else { F_ZERO };
            k += 2;

            // Enhancement-395: each root contributes the NORMALIZED factor
            // `(1 - s/r)`, not `(s - r)`.
            //
            // LRM 4.5.11.1-4.5.11.3 spell the zero/pole products as
            // `prod(1 - s/(rho_r + j*rho_i))`. This built `prod(s - r)`, so the
            // whole transfer function came out scaled by `prod(-zeta)/prod(-rho)`
            // -- for a single pole at -1e4 the DC gain was 1e4x too small, and
            // for two poles 2e8x. `laplace_nd` was unaffected (it takes
            // coefficients, so no normalization question arises), which is why
            // only the three ROOT-taking forms were wrong. The z-domain form is
            // `1 - z^-1*rho`, where the root MULTIPLIES rather than divides.
            //
            // Enhancement-405: that last sentence used to end "The `zi_*` family
            // is separate and already correct" -- but `lower_zi` called straight
            // into THIS function, so every zi_np/zi_zp pole and every zi_zd/zi_zp
            // zero came out RECIPROCATED (a pole written 0.5 landed at z=2, DC
            // gain -1 against 2). They use `zi_roots_to_poly` now.
            //
            // The LRM's own exception is handled too: "If a root is zero, then
            // the term associated with it is implemented as s, rather than
            // (1 - s/r)". That cannot be folded into the general formula (it
            // would divide by zero), and the roots are runtime values here, so
            // the two forms are selected at runtime. When the roots are
            // constants -- overwhelmingly the common case -- the optimiser
            // folds the select away.
            let n = re.len();
            let mut nre = vec![F_ZERO; n + 1];
            let mut nim = vec![F_ZERO; n + 1];

            // is_zero = (rr == 0) && (ri == 0)
            let rr_z = self.ctx.ins().feq(rr, F_ZERO);
            let ri_z = self.ctx.ins().feq(ri, F_ZERO);
            let is_zero = crate::stmt::bool_and(self.ctx, rr_z, ri_z);

            // 1/r = conj(r)/|r|^2, guarded so the zero-root branch cannot produce
            // a NaN that the select would then have to discard.
            let rr2 = self.ctx.ins().fmul(rr, rr);
            let ri2 = self.ctx.ins().fmul(ri, ri);
            let mag2 = self.ctx.ins().fadd(rr2, ri2);
            let inv_re = self.fdiv_guarded(rr, mag2);
            let ri_neg = self.ctx.ins().fneg(ri);
            let inv_im = self.fdiv_guarded(ri_neg, mag2);

            for i in 0..n {
                // (1/r) * P[i]
                let a = self.ctx.ins().fmul(inv_re, re[i]);
                let b = self.ctx.ins().fmul(inv_im, im[i]);
                let q_re = self.ctx.ins().fsub(a, b);
                let c = self.ctx.ins().fmul(inv_re, im[i]);
                let d = self.ctx.ins().fmul(inv_im, re[i]);
                let q_im = self.ctx.ins().fadd(c, d);

                // normalized: P[i] carried down, -(P/r)[i] carried up one degree
                let up_re = self.ctx.ins().fneg(q_re);
                let up_im = self.ctx.ins().fneg(q_im);

                // zero root: the factor is a bare `s`, i.e. P[i] shifts up and
                // contributes nothing at its own degree.
                let (pr, pi) = (re[i], im[i]);
                let low_re = self.ctx.make_select(is_zero, move |_c, z| if z { F_ZERO } else { pr });
                let low_im = self.ctx.make_select(is_zero, move |_c, z| if z { F_ZERO } else { pi });
                let hi_re = self.ctx.make_select(is_zero, move |_c, z| if z { pr } else { up_re });
                let hi_im = self.ctx.make_select(is_zero, move |_c, z| if z { pi } else { up_im });

                nre[i] = self.ctx.ins().fadd(nre[i], low_re);
                nim[i] = self.ctx.ins().fadd(nim[i], low_im);
                nre[i + 1] = self.ctx.ins().fadd(nre[i + 1], hi_re);
                nim[i + 1] = self.ctx.ins().fadd(nim[i + 1], hi_im);
            }
            re = nre;
            im = nim;
        }
        re
    }

    /// Enhancement-405: expands **complex** z-domain roots into ascending-power *real*
    /// coefficients of `Π_k (1 - rho_k * w)`, where `w = z^-1`.
    ///
    /// The z-domain counterpart of [`Self::laplace_roots_to_poly`], differing in the one way
    /// that matters: the root **multiplies** `z^-1` rather than dividing `s`. Calling the
    /// Laplace version here -- which is what `lower_zi` used to do -- reciprocates every pole
    /// and zero, so `zi_zp` given a pole at 0.5 built a filter with its pole at z = 2 (DC gain
    /// -1, where the same filter written with `zi_nd` coefficients gives 2).
    ///
    /// Roots arrive as `(real, imaginary)` pairs exactly as in the Laplace form, and a trailing
    /// unpaired element is a purely real root. Only the real parts of the product are returned;
    /// for a physical filter the roots come in conjugate pairs and the imaginary parts cancel.
    ///
    /// There is deliberately no zero-root special case. The LRM's `(1 - s/r)` exception exists
    /// because that form divides by the root; `(1 - rho*w)` does not, and at `rho = 0` it is
    /// simply `1`.
    fn zi_roots_to_poly(&mut self, roots: &[Value]) -> Vec<Value> {
        // coefficients as (real, imaginary), ascending powers of w; start at `1 + 0j`
        let mut re = vec![F_ONE];
        let mut im = vec![F_ZERO];
        let mut k = 0;
        while k < roots.len() {
            let rr = roots[k];
            let ri = if k + 1 < roots.len() { roots[k + 1] } else { F_ZERO };
            k += 2;

            let n = re.len();
            let mut nre = vec![F_ZERO; n + 1];
            let mut nim = vec![F_ZERO; n + 1];
            for i in 0..n {
                // P[i] carries down unchanged ...
                nre[i] = self.ctx.ins().fadd(nre[i], re[i]);
                nim[i] = self.ctx.ins().fadd(nim[i], im[i]);

                // ... and -(rho * P[i]) carries up one degree in w
                let a = self.ctx.ins().fmul(rr, re[i]);
                let b = self.ctx.ins().fmul(ri, im[i]);
                let q_re = self.ctx.ins().fsub(a, b);
                let c = self.ctx.ins().fmul(rr, im[i]);
                let d = self.ctx.ins().fmul(ri, re[i]);
                let q_im = self.ctx.ins().fadd(c, d);

                let up_re = self.ctx.ins().fneg(q_re);
                let up_im = self.ctx.ins().fneg(q_im);
                nre[i + 1] = self.ctx.ins().fadd(nre[i + 1], up_re);
                nim[i + 1] = self.ctx.ins().fadd(nim[i + 1], up_im);
            }
            re = nre;
            im = nim;
        }
        re
    }

    /// Builds a controllable-canonical-form state-space realization of `H(s) = num(s)/den(s)`
    /// (both ascending-power coefficient lists, `den` non-empty) driven by `input`, and returns
    /// the algebraic output value `y`.
    fn laplace_state_space(
        &mut self,
        name: &str,
        input: Value,
        num: &[Value],
        den: &[Value],
    ) -> Value {
        // Enhancement-405: the `den` non-empty precondition above is enforced by hir_ty, but
        // an unguarded `- 1` here is one caller away from the underflow that hung `lower_zi`.
        let n = den.len().saturating_sub(1);
        let a_n = den.get(n).copied().unwrap_or(F_ONE);

        if n == 0 {
            // No dynamics: H(s) is a constant gain num[0]/den[0].
            let b0 = num.first().copied().unwrap_or(F_ZERO);
            let gain = self.ctx.ins().fdiv(b0, a_n);
            return self.ctx.ins().fmul(gain, input);
        }

        // Enhancement-506: `a_n` divides every coefficient below, and nothing
        // checked it once it came from the deck.
        //
        // hir_ty refuses a literal whose highest-order denominator coefficient is
        // zero -- "the denominator has a highest-order coefficient of zero, so its
        // effective order is 0 rather than N" -- but it sees only a literal or a
        // localparam. Written as `'{1, d1}` with `d1` a deck-set parameter, the
        // same filter compiled clean and then divided by zero here, so every
        // normalized coefficient became inf or NaN and the user got six lines of
        // gmin- and source-stepping failure ending in "Timestep too small; cause
        // unrecorded" -- a convergence report for a structurally invalid filter
        // the compiler can already name exactly.
        //
        // The order `n` is fixed when the state space is built, so the effective
        // order cannot be reduced here; substituting a small epsilon would only
        // hide the mistake behind a stiff parasitic pole. The run time therefore
        // says what the compiler says and aborts, and substitutes 1 purely so this
        // one evaluation stamps finite numbers into the matrix -- the flag is
        // inspected after eval returns, never in the middle of it.
        let a_n_abs = self.lower_fabs(a_n);
        let a_n_ok = self.ctx.ins().fgt(a_n_abs, F_ZERO); // false for 0 and NaN
        let a_n_msg = format!(
            "{name}: the denominator's highest-order coefficient must not be zero, but is"
        );
        let a_n = self.ctx.make_select(a_n_ok, |ctx, branch| {
            if branch {
                a_n
            } else {
                ctx.runtime_fatal(&a_n_msg, Some(a_n));
                F_ONE
            }
        });

        // Normalized (monic) denominator coefficients a_bar_i = den[i] / a_n, i in 0..n.
        let a_bar: Vec<Value> =
            (0..n).map(|i| self.ctx.ins().fdiv(den[i], a_n)).collect();

        // Direct feedthrough d = num[n] / a_n, present only if num is exactly proper (deg == n).
        let d = if num.len() == n + 1 {
            self.ctx.ins().fdiv(num[n], a_n)
        } else {
            F_ZERO
        };

        // c_i = (b_i - d * den[i]) / a_n, i in 0..n, with b_i = num[i] (0 if out of range).
        let c: Vec<Value> = (0..n)
            .map(|i| {
                let b_i = num.get(i).copied().unwrap_or(F_ZERO);
                let d_a_i = self.ctx.ins().fmul(d, den[i]);
                let numer = self.ctx.ins().fsub(b_i, d_a_i);
                self.ctx.ins().fdiv(numer, a_n)
            })
            .collect();

        // n state implicit equations, each an idt-style reactive/resistive residual pair.
        let mut states = Vec::with_capacity(n);
        for _ in 0..n {
            let idx = self.ctx.intern.implicit_equations.len() as u32;
            let state =
                self.ctx.implicit_equation(ImplicitEquationKind::LaplaceState(idx));
            states.push(state);
        }

        for i in 0..n {
            let (eq, _) = states[i];
            let resist = if i + 1 < n {
                // dx_i/dt = x_{i+1}  =>  resistive residual = -x_{i+1}
                self.ctx.ins().fneg(states[i + 1].1)
            } else {
                // dx_{n-1}/dt = u - sum_j a_bar_j * x_j  =>  resistive residual = (sum) - u
                let mut acc = F_ZERO;
                for j in 0..n {
                    let term = self.ctx.ins().fmul(a_bar[j], states[j].1);
                    acc = self.ctx.ins().fadd(acc, term);
                }
                self.ctx.ins().fsub(acc, input)
            };
            self.ctx.def_resist_residual(resist, eq);
            self.ctx.def_react_residual(states[i].1, eq);
        }

        // y = sum_i c_i * x_i + d * u
        let mut y = F_ZERO;
        for i in 0..n {
            let term = self.ctx.ins().fmul(c[i], states[i].1);
            y = self.ctx.ins().fadd(y, term);
        }
        let du = self.ctx.ins().fmul(d, input);
        self.ctx.ins().fadd(y, du)
    }

    /// Lowers `zi_nd`/`zi_np`/`zi_zd`/`zi_zp(in, num_or_zero, den_or_pole, T[, tol[, nature]])`.
    ///
    /// Unlike `laplace_*`, a z-domain filter is inherently a *sampled-data* system: exact
    /// semantics require the simulator to hold the output between samples taken every `T`
    /// seconds, which needs dedicated per-timestep/breakpoint support in the simulator runtime
    /// (OSDI + the underlying SPICE engine) that does not exist in this codebase. Implementing
    /// that is out of scope here (tracked as follow-up work); instead this applies the standard
    /// bilinear (Tustin) transform `z^-1 = (1 - sT/2)/(1 + sT/2)` to convert the z-domain
    /// transfer function into an equivalent *continuous* s-domain transfer function at
    /// MIR-generation time (the coefficient arithmetic itself runs at simulation time, since the
    /// z-domain coefficients/`T` may be arbitrary runtime expressions, not just literals), then
    /// reuses the exact same `laplace_state_space` continuous-time state-space realization as
    /// `laplace_*`. This exactly preserves the filter's pole/zero mapping and low-frequency
    /// (DC/near-DC) behavior, at the cost of not reproducing true zero-order-hold/aliasing
    /// behavior near the Nyquist rate (`1/T`) -- a documented approximation, not full LRM
    /// fidelity.
    fn lower_zi(&mut self, kind: BuiltIn, args: &[ExprId]) -> Value {
        let input = self.lower_expr(args[0]);

        let num_is_roots = matches!(kind, BuiltIn::zi_zd | BuiltIn::zi_zp);
        let den_is_roots = matches!(kind, BuiltIn::zi_np | BuiltIn::zi_zp);

        let num = self.lower_coeff_elems(args[1]);
        let den = self.lower_coeff_elems(args[2]);

        let num = if num_is_roots { self.zi_roots_to_poly(&num) } else { num };
        let den = if den_is_roots { self.zi_roots_to_poly(&den) } else { den };

        // Enhancement-506: the sampling period decides the whole bilinear map, and
        // nothing checked it once it came from the deck.
        //
        // hir_ty refuses a literal `T <= 0` ("the sampling period must be greater
        // than zero", Enhancement-420) but sees only a literal or a localparam. A
        // model whose `parameter real T = 1n` is overridden to a negative value --
        // the ordinary route -- reached `w = (1 - s*T/2)/(1 + s*T/2)` with the map
        // INVERTED, which reflects every pole across the imaginary axis: the filter
        // became unstable and ran to 1.2e+240 over 60 ns, with exit code 0 and not
        // one diagnostic. A bounded-but-wrong substitute would only trade a visibly
        // absurd number for an invisibly wrong one, and there is no honest value to
        // project a non-positive sampling period onto, so the run time says exactly
        // what the compiler says and aborts.
        let t = self.lower_expr(args[3]);
        let t_ok = self.ctx.ins().fgt(t, F_ZERO); // false for 0, negatives and NaN
        let t_msg = format!(
            "{}: the sampling period must be greater than zero, but is",
            Self::filter_builtin_name(kind)
        );
        let t = self.ctx.make_select(t_ok, |ctx, branch| {
            if branch {
                t
            } else {
                ctx.runtime_fatal(&t_msg, Some(t));
                // Finite, so this one evaluation stamps sane numbers; the flag is
                // inspected after eval returns (Enhancement-324).
                F_ONE
            }
        });
        let f_half = self.ctx.fconst(0.5);
        let half_t = self.ctx.ins().fmul(t, f_half);

        // Enhancement-405: `den.len() - 1` UNDERFLOWED to usize::MAX on an empty denominator
        // (`zi_nd(x, '{1.0}, '{}, T, 0)`), and the bilinear expansion below then looped over
        // 0..=usize::MAX -- an unbounded hang that reached tens of GB of RSS before being
        // killed. `num` beside it was already saturating. hir_ty rejects an empty coefficient
        // list with a real diagnostic now; this keeps lowering itself total either way.
        let n = den.len().saturating_sub(1).max(num.len().saturating_sub(1));
        let num_s = self.bilinear_transform(&num, n, half_t);
        let den_s = self.bilinear_transform(&den, n, half_t);

        self.laplace_state_space(Self::filter_builtin_name(kind), input, &num_s, &den_s)
    }

    /// Converts the coefficients (ascending powers of `w = z^-1`, LRM order) of a degree-`n`
    /// z-domain polynomial `P(w)` into the coefficients (ascending powers of `s`) of the
    /// equivalent s-domain polynomial under the bilinear substitution `w = (1 - x)/(1 + x)`,
    /// `x = s * half_t` (`half_t = T/2`).
    ///
    /// `P(w) * (1+x)^n = sum_k p_k * (1-x)^k * (1+x)^(n-k) =: Q(x)`, a degree-`n` polynomial in
    /// `x` whose coefficients are themselves fixed (compile-time-known) integer linear
    /// combinations of the `p_k` -- the `(1-x)^k*(1+x)^(n-k)` binomial expansions depend only on
    /// `n`/`k`/`i`, not on any runtime value, so those combination weights are plain `f64`
    /// constants baked into the generated arithmetic. `Q(x)`'s coefficient of `x^i` is then
    /// converted to a coefficient of `s^i` via `x^i = half_t^i * s^i`.
    fn bilinear_transform(&mut self, poly: &[Value], n: usize, half_t: Value) -> Vec<Value> {
        let mut half_t_pow = vec![F_ONE];
        for _ in 0..n {
            half_t_pow.push(self.ctx.ins().fmul(*half_t_pow.last().unwrap(), half_t));
        }

        (0..=n)
            .map(|i| {
                let mut q_i = F_ZERO;
                for k in 0..=n {
                    let Some(&p_k) = poly.get(k) else { continue };
                    let weight = binomial_bilinear_weight(n, k, i);
                    if weight != 0.0 {
                        let c = self.ctx.fconst(weight);
                        let term = self.ctx.ins().fmul(p_k, c);
                        q_i = self.ctx.ins().fadd(q_i, term);
                    }
                }
                self.ctx.ins().fmul(q_i, half_t_pow[i])
            })
            .collect()
    }

    fn lower_integral(&mut self, kind: IdtKind, args: &[ExprId]) -> Value {
        let (equation, val) = self.ctx.implicit_equation(ImplicitEquationKind::Idt(kind));

        let enable_integral = self.ctx.use_param(ParamKind::EnableIntegration);
        let residual = if kind.has_ic() {
            if kind.has_assert() {
                // Enhancement-52: the previous formulation pinned `val = ic`
                // algebraically during reset with the reactive residual jumping
                // from the integrated charge to `ic` -- the transient
                // integrator's d/dt term saw that jump as an impulse
                // (exactly the E-27 idtmod failure mode), which made
                // self-resetting integrators (`idt(1, 0, V(out) > 1)`) ring
                // and run away. Keep the charge SMOOTH instead: the reactive
                // residual is always `val`, and reset is a stiff first-order
                // decay toward `ic` (`dval/dt = -K*(val - ic)`, K = 1e9 --
                // the slew/transition tracking gain), so both the reset onset
                // and the release are continuous in the stored charge.
                // Decay gain: tau = 1/K = 10us reset time constant. The
                // conditional bound_step below keeps the transient integrator
                // inside the decay's stability region (lambda*h ~ 2, where the
                // trapezoidal method is deadbeat rather than ringing); once the
                // output has settled at `ic` the bound is released, so long
                // holds simulate at full speed.
                const RESET_GAIN: f64 = 1.0e5;
                let resist = self.lower_select_with(
                    enable_integral,
                    |mut s| {
                        let assert = s.lower_expr(args[2]);
                        let in_reset = s.ctx.ins().fne(assert, F_ZERO);
                        s.lower_select_with(
                            in_reset,
                            |mut r| {
                                let ic = r.lower_expr(args[1]);
                                let dev = r.ctx.ins().fsub(val, ic);
                                let gain = r.ctx.fconst(RESET_GAIN);
                                let resist = r.ctx.ins().fmul(gain, dev);

                                // bound the step while the decay is active
                                // (|dev| via neg/lt/select -- MIR has no fabs)
                                let neg_dev = r.ctx.ins().fneg(dev);
                                let dev_neg = r.ctx.ins().flt(dev, F_ZERO);
                                let abs_dev =
                                    r.lower_select_with(dev_neg, |_| neg_dev, |_| dev);
                                let neg_ic = r.ctx.ins().fneg(ic);
                                let ic_neg = r.ctx.ins().flt(ic, F_ZERO);
                                let abs_ic = r.lower_select_with(ic_neg, |_| neg_ic, |_| ic);
                                let one = r.ctx.fconst(1.0);
                                let scale = r.ctx.ins().fadd(one, abs_ic);
                                let tol = r.ctx.fconst(1.0e-6);
                                let thresh = r.ctx.ins().fmul(tol, scale);
                                let active = r.ctx.ins().fgt(abs_dev, thresh);
                                let bound = r.ctx.fconst(2.0 / RESET_GAIN);
                                let inf = r.ctx.fconst(f64::INFINITY);
                                let step = r.lower_select_with(active, |_| bound, |_| inf);
                                r.ctx.def_place(PlaceKind::BoundStep, step);

                                resist
                            },
                            |mut i| {
                                let arg = i.lower_expr(args[0]);
                                i.ctx.ins().fneg(arg)
                            },
                        )
                    },
                    |mut d| {
                        // DC / IC phase: pin `val = ic` (react is ignored here,
                        // and charge = val = ic hands over continuously)
                        let ic = d.lower_expr(args[1]);
                        d.ctx.ins().fsub(val, ic)
                    },
                );
                self.ctx.def_resist_residual(resist, equation);
                self.ctx.def_react_residual(val, equation);
                return val;
            }

            self.lower_multi_select(enable_integral, |mut ctx, branch| {
                if branch {
                    // Enhancement-27: always integrate the DAE state UNBOUNDED here. For `idtmod`
                    // the modulo wrap is applied to the *returned value* (below), not to the state.
                    // Wrapping the state inside the residual makes the reactive residual jump by
                    // `modulus` at each wrap, so the transient integrator's d/dt term (which uses the
                    // previous reactive residual, ~modulus) blows up -- the wrap diverged before this
                    // fix (integrator got stuck / shot to ~q/dt).
                    let arg = ctx.lower_expr(args[0]);
                    [ctx.ctx.ins().fneg(arg), val]
                } else {
                    // Enhancement-28: during the IC / DC-operating-point phase the reactive residual
                    // (the integrator's stored charge) must be `ic`, not zero. The resistive term
                    // (`val - ic`) pins `val = ic` at DC, but if the charge is left at 0 then when
                    // transient integration turns on the integrator restarts from 0 -- so the initial
                    // condition was applied at DC but silently lost in transient (the ramp started from
                    // 0 instead of `ic`). Storing charge = `ic` makes the transient continue from `ic`
                    // (and an `assert` reset likewise restores the integrator to `ic`).
                    let ic = ctx.lower_expr(args[1]);
                    [ctx.ctx.ins().fsub(val, ic), ic]
                }
            })
        } else {
            let arg = self.lower_expr(args[0]);
            [self.ctx.ins().fneg(arg), val]
        };

        self.ctx.def_resist_residual(residual[0], equation);
        self.ctx.def_react_residual(residual[1], equation);

        // Enhancement-27: `idtmod` returns the (unbounded) integral wrapped into
        // `[offset, offset+modulus)`:  offset + floor_mod(val - offset, modulus), where
        // floor_mod(x, m) = x - m*floor(x/m) stays in `[0, m)` even for negative x. The DAE
        // *state* keeps integrating smoothly (above); only this returned value wraps. Also fixes
        // the offset argument, which previously read `args[2]` (the modulus) instead of `args[3]`.
        if kind.has_modulus() {
            let modulus = self.lower_expr(args[2]);
            let offset = if kind.has_offset() { self.lower_expr(args[3]) } else { F_ZERO };
            let shifted = self.ctx.ins().fsub(val, offset);
            let quot = self.ctx.ins().fdiv(shifted, modulus);
            let whole = self.ctx.ins().floor(quot);
            let whole_mod = self.ctx.ins().fmul(whole, modulus);
            let rem = self.ctx.ins().fsub(shifted, whole_mod);
            let wrapped = self.ctx.ins().fadd(rem, offset);
            // Enhancement-504: a modulus that is not strictly positive wraps
            // nothing. hir_ty refuses one it can SEE ("the modulus must be
            // greater than zero"), but only a literal or a localparam; from a
            // deck-overridden `parameter` a zero modulus reached the division
            // above, made the returned value NaN, and took the whole analysis
            // down with "Timestep too small; cause unrecorded" -- a message
            // naming neither this model nor this call. Fall back to the
            // UNWRAPPED integral, which is exactly what `idtmod` means with no
            // modulus supplied, so the model keeps running and the value stays
            // finite.
            let zero = self.ctx.fconst(0.0);
            let usable = self.ctx.ins().fgt(modulus, zero); // false for 0, <0 and NaN
            self.ctx.make_select(usable, |_, branch| if branch { wrapped } else { val })
        } else {
            val
        }
    }

    pub fn resolved_ty(&self, expr: ExprId) -> Type {
        self.body
            .needs_cast(expr)
            .map(|(_, dst)| dst.to_owned())
            .unwrap_or_else(|| self.body.expr_type(expr))
    }

    pub fn lower_body(&mut self, body: Body, i: usize) -> Value {
        let expr = body.borrow().get_entry_expr(i);
        BodyLoweringCtx { ctx: self.ctx, body: body.borrow(), path: self.path }.lower_expr(expr)
    }
}

/// `C(n, k)`, computed via the multiplicative formula to avoid factorial overflow for the
/// small `n` (filter order) expected here.
fn binomial(n: usize, k: usize) -> f64 {
    if k > n {
        return 0.0;
    }
    let k = k.min(n - k);
    let mut result = 1.0f64;
    for i in 0..k {
        result = result * (n - i) as f64 / (i + 1) as f64;
    }
    result
}

/// Coefficient of `x^i` in `(1-x)^k * (1+x)^(n-k)`, used by `bilinear_transform` to build the
/// compile-time-known combination weights for the Tustin substitution.
fn binomial_bilinear_weight(n: usize, k: usize, i: usize) -> f64 {
    let n_k = n - k;
    let a_lo = i.saturating_sub(n_k);
    let a_hi = k.min(i);
    let mut sum = 0.0f64;
    for a in a_lo..=a_hi {
        let b = i - a;
        let sign = if a % 2 == 0 { 1.0 } else { -1.0 };
        sum += sign * binomial(k, a) * binomial(n_k, b);
    }
    sum
}

/// Enhancement-105: extract the ordered list of `$sscanf`/`$fscanf` conversion
/// characters (`d`, `h`, `o`, `b`, `g`, `s`, ...) from a format string, one per
/// consumed argument. `%%` is a literal percent and `%m`/`%M` take no argument,
/// so both are skipped; flags/width/precision between `%` and the conversion
/// are ignored. Used to pick the integer base of each scanned field.
fn scanf_conversion_chars(fmt: &str) -> Vec<char> {
    let mut out = Vec::new();
    let mut chars = fmt.chars();
    while let Some(c) = chars.next() {
        if c != '%' {
            continue;
        }
        let mut d = match chars.next() {
            Some(d) => d,
            None => break,
        };
        // skip any flags / width / precision prefix
        while matches!(d, '-' | '+' | ' ' | '#' | '0'..='9' | '.' | '*') {
            d = match chars.next() {
                Some(d) => d,
                None => return out,
            };
        }
        match d {
            '%' | 'm' | 'M' => {} // no argument consumed
            _ => out.push(d),
        }
    }
    out
}

/// Enhancement-392: see `MAX_RUNTIME_TABLE` on the lowering impl.
pub(crate) const MAX_RUNTIME_TABLE: usize = 256;

/// Batcher's odd-even merge sort network for `n` inputs: the (lo, hi) index pairs
/// of a compare-exchange sequence that sorts any input, in a fixed order known at
/// compile time. O(n log^2 n) comparators against the O(n^2) of a bubble network.
fn batcher_network(n: usize) -> Vec<(usize, usize)> {
    let mut pairs = Vec::new();
    let mut p = 1;
    while p < n {
        let mut k = p;
        while k >= 1 {
            let mut j = k % p;
            while j + k < n {
                for i in 0..k.min(n.saturating_sub(j + k)) {
                    if (i + j) / (p * 2) == (i + j + k) / (p * 2) {
                        pairs.push((i + j, i + j + k));
                    }
                }
                j += 2 * k;
            }
            k /= 2;
        }
        p *= 2;
    }
    pairs
}

/// Fold `expr` to a number if its value is fixed when the model is compiled,
/// following `localparam` references into their own bodies.
///
/// See `BodyLoweringCtx::eval_const_real_at` for why this matters: the callers
/// build compile-time tables and turn `None` into `0.0`, so anything this
/// cannot fold becomes a silent zero entry.
/// Is `expr` fixed for the whole run, and does it involve a DECK-overridable
/// parameter?
///
/// * `None`          -- not fixed for the run (a probe, a variable, time, ...)
/// * `Some(false)`   -- fixed, but built only from literals and `localparam`s
/// * `Some(true)`    -- fixed, and an overridable `parameter` takes part
///
/// Enhancement-509 emits a domain check only for `Some(true)`, and the three
/// cases are all load-bearing:
///
/// `None` must not be guarded. `sqrt(V(p,n))` legitimately sees a negative
/// argument during Newton iteration, and refusing that would break working
/// models -- the overreach Enhancement-508 had to take back on
/// `$discontinuity`.
///
/// `Some(false)` must not be guarded either. `hir_ty` already refuses those at
/// compile time with a better message, so a run-time check adds nothing -- and
/// emitting one folds the whole condition to a constant, which is how this first
/// version CRASHED the compiler: `mir_opt`'s constant evaluator has no case for
/// `iand`/`ior` on two constant booleans (fixed alongside, but the guard should
/// not be creating that shape in the first place).
///
/// `Some(true)` is precisely the route the compiler cannot see: the value is
/// unknown when the model is compiled and fixed once the card has been read, so
/// a check on it tests the same number at every evaluation and cannot misfire.
///
/// Deliberately the same shape as `const_real_in_body`, one step weaker: that
/// folds what is known when the model is COMPILED (so never a `parameter`), this
/// accepts anything constant once the model card is READ.
fn param_derived_in_body(
    db: &CompilationDB,
    body: BodyRef<'_>,
    expr: ExprId,
    depth: u32,
) -> Option<bool> {
    // Enhancement-510: see hir_ty -- the two folders must accept the same set.
    if depth > 512 {
        return None;
    }
    if let Some(lit) = body.as_literal(expr) {
        return matches!(lit, Literal::Float(_) | Literal::Int(_)).then_some(false);
    }
    match body.get_expr(expr) {
        Expr::UnaryOp { expr: inner, op } => {
            if matches!(op, UnaryOp::Neg | UnaryOp::Identity) {
                param_derived_in_body(db, body, inner, depth + 1)
            } else {
                None
            }
        }
        Expr::BinaryOp { lhs, rhs, op } => {
            if !matches!(
                op,
                BinaryOp::Addition
                    | BinaryOp::Subtraction
                    | BinaryOp::Multiplication
                    | BinaryOp::Division
            ) {
                return None;
            }
            let l = param_derived_in_body(db, body, lhs, depth + 1)?;
            let r = param_derived_in_body(db, body, rhs, depth + 1)?;
            Some(l || r)
        }
        // A `localparam` is fixed at compile time, so it carries no deck value; a
        // `parameter` is the one the model card may replace.
        Expr::Read(Ref::Parameter(param)) => Some(!param.is_local(db)),
        _ => None,
    }
}

fn const_real_in_body(
    db: &CompilationDB,
    body: BodyRef<'_>,
    expr: ExprId,
    depth: u32,
) -> Option<f64> {
    // Enhancement-510: see hir_ty -- the two folders must accept the same set.
    if depth > 512 {
        return None;
    }
    if let Some(lit) = body.as_literal(expr) {
        return match lit {
            Literal::Float(f) => Some((*f).into()),
            Literal::Int(i) => Some(*i as f64),
            _ => None,
        };
    }
    match body.get_expr(expr) {
        Expr::UnaryOp { expr: inner, op } => match op {
            UnaryOp::Neg => Some(-const_real_in_body(db, body, inner, depth)?),
            UnaryOp::Identity => const_real_in_body(db, body, inner, depth),
            _ => None,
        },
        Expr::BinaryOp { lhs, rhs, op } => {
            let l = const_real_in_body(db, body, lhs, depth)?;
            let r = const_real_in_body(db, body, rhs, depth)?;
            match op {
                BinaryOp::Addition => Some(l + r),
                BinaryOp::Subtraction => Some(l - r),
                BinaryOp::Multiplication => Some(l * r),
                BinaryOp::Division if r != 0.0 => Some(l / r),
                _ => None,
            }
        }
        // A `localparam` is fixed at compile time and never externally
        // overridable, so its default IS its value. A `parameter` is not folded:
        // the model card may replace it.
        Expr::Read(Ref::Parameter(param)) => {
            if !param.is_local(db) {
                return None;
            }
            let init = param.init(db);
            let default = param.default(db);
            const_real_in_body(db, init.borrow(), default, depth + 1)
        }
        _ => None,
    }
}
