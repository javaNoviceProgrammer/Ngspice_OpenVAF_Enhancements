use hir::builtin::{
    FLICKER_NOISE_NAME, NOISE_TABLE_FILE, NOISE_TABLE_FILE_NAME, NOISE_TABLE_INLINE,
    NOISE_TABLE_INLINE_NAME, TABLE_MODEL_1D_ARR, TABLE_MODEL_1D_ARR_CTRL, TABLE_MODEL_1D_FILE,
    TABLE_MODEL_1D_FILE_CTRL, TABLE_MODEL_2D_FILE, TABLE_MODEL_2D_FILE_CTRL, TABLE_MODEL_3D_FILE,
    TABLE_MODEL_3D_FILE_CTRL, WHITE_NOISE_NAME,
};
use hir::signatures::{
    ABSDELAY_MAX, ABS_INT, ABS_REAL, BOOL_EQ, DDX_POT, IDTMOD_IC, IDTMOD_IC_MODULUS,
    IDTMOD_IC_MODULUS_OFFSET, IDTMOD_IC_MODULUS_OFFSET_NATURE, IDTMOD_IC_MODULUS_OFFSET_TOL,
    IDTMOD_NO_IC, IDT_IC, IDT_IC_ASSERT, IDT_IC_ASSERT_NATURE, IDT_IC_ASSERT_TOL, IDT_NO_IC,
    INT_EQ, INT_OP, LAST_CROSSING_DIRECTION, LAST_CROSSING_NO_DIRECTION, LIMIT_BUILTIN_FUNCTION,
    MAX_INT, MAX_REAL, NATURE_ACCESS_BRANCH,
    NATURE_ACCESS_NODES, NATURE_ACCESS_NODE_GND, NATURE_ACCESS_PORT_FLOW, REAL_EQ, REAL_OP,
    SIMPARAM_DEFAULT, SIMPARAM_NO_DEFAULT, SLEW_NEG_MAX, SLEW_NO_MAX, SLEW_POS_MAX, STR_EQ,
    TRANSITION_DELAY, TRANSITION_DELAY_RISET, TRANSITION_DELAY_RISET_FALLT,
    TRANSITION_DELAY_RISET_FALLT_TOL, TRANSITION_NO_ARGS,
};
use hir::{Body, BuiltIn, Expr, ExprId, Literal, /*ParamSysFun,*/ Ref, ResolvedFun, Type};
use mir::builder::InstBuilder;
use mir::{Opcode, Value, FALSE, F_ONE, F_ZERO, GRAVESTONE, INFINITY, TRUE, ZERO};
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
        if let Some((elems, dims, indices)) = self.body.dynamic_index(expr) {
            let mut res = self.lower_dynamic_index_read(&elems, &dims, &indices);
            if let Some((src, dst)) = self.body.needs_cast(expr) {
                res = self.ctx.insert_cast(res, &src, dst);
            }
            self.ctx.set_srcloc(old_loc);
            return res;
        }

        let mut res = match self.body.get_expr(expr) {
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
            UnaryOp::BitNegate => self.ctx.ins().ineg(arg_),
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
        todo!("arrays")
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

    /// Lowers a dynamic-index array read `c[i]` / `m[i][j]` to a runtime select chain over the
    /// element variables: `elems[0]` is the default and each `elems[k]` is chosen when the flat
    /// runtime position equals `k`.
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
            BinaryOp::Power => Opcode::Pow,

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
                let func_elems = arg.array_elems(self.ctx.db);
                let caller_elems = self.body.array_var_ref(*expr).unwrap_or_default();
                for (&p_i, &c_i) in func_elems.iter().zip(&caller_elems) {
                    let val = self.ctx.read_variable(c_i);
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
        if let Some(lit) = self.body.as_literal(expr) {
            return match lit {
                Literal::Float(f) => Some((*f).into()),
                Literal::Int(i) => Some(*i as f64),
                _ => None,
            };
        }
        match self.body.get_expr(expr) {
            Expr::UnaryOp { expr: inner, op } => match op {
                UnaryOp::Neg => Some(-self.eval_const_real(inner)?),
                UnaryOp::Identity => self.eval_const_real(inner),
                _ => None,
            },
            _ => None,
        }
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
                if let (Ok(f), Ok(p)) = (a.parse::<f64>(), b.parse::<f64>()) {
                    out.push((f, p));
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
                let fname = self.body.as_literal(args[0]).unwrap().unwrap_str();
                self.read_noise_table_file(fname)
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
                if let Ok(v) = tok.parse::<f64>() {
                    out.push(v);
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
        let sizes: Vec<usize> =
            (0..ndim).map(|_| it.next().map(|v| v as usize)).collect::<Option<_>>()?;
        if sizes.iter().any(|&s| s == 0) {
            return None;
        }
        let mut axes = Vec::with_capacity(ndim);
        for &sz in &sizes {
            axes.push((0..sz).map(|_| it.next()).collect::<Option<Vec<f64>>>()?);
        }
        let total: usize = sizes.iter().product();
        let tensor = (0..total).map(|_| it.next()).collect::<Option<Vec<f64>>>()?;
        Some((axes, tensor))
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

    /// Lowers `$table_model(x1[, x2, x3], <data>[, "ctrl"])` to differentiable MIR: reads the
    /// compile-time grid (inline array or data file), lowers each coordinate, and multilinearly
    /// interpolates via `interp_nd`, so `mir_autodiff` supplies the per-axis slope as the Jacobian.
    fn lower_table_model(&mut self, signature: hir::Signature, args: &[ExprId]) -> Value {
        // (ndim, is_file, has_ctrl) for each declared signature variant
        let (ndim, is_file, has_ctrl) = match signature {
            TABLE_MODEL_1D_ARR => (1, false, false),
            TABLE_MODEL_1D_ARR_CTRL => (1, false, true),
            TABLE_MODEL_1D_FILE => (1, true, false),
            TABLE_MODEL_1D_FILE_CTRL => (1, true, true),
            TABLE_MODEL_2D_FILE => (2, true, false),
            TABLE_MODEL_2D_FILE_CTRL => (2, true, true),
            TABLE_MODEL_3D_FILE => (3, true, false),
            TABLE_MODEL_3D_FILE_CTRL => (3, true, true),
            _ => (1, false, false),
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
                let (negate, comparison, zero) = match_signature!(signature:
                    ABS_REAL => (Opcode::Fneg, Opcode::Flt,  F_ZERO),
                    ABS_INT => (Opcode::Ineg, Opcode::Ilt, ZERO)
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
                    |_| val,
                )
            }
            BuiltIn::acos => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().acos(arg0)
            }
            BuiltIn::acosh => {
                let arg0 = self.lower_expr(args[0]);
                self.ctx.ins().acosh(arg0)
            }
            BuiltIn::asin => {
                let arg0 = self.lower_expr(args[0]);
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
                self.ctx.ins().ln(arg0)
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
                self.lower_scanf(input, &args[2..])
            }
            BuiltIn::fscanf => {
                // Read one line from the descriptor, then scan it like $sscanf.
                let fd = self.lower_expr(args[0]);
                let input = self.ctx.call1(CallBackKind::Fgets, &[fd]);
                self.lower_scanf(input, &args[2..])
            }

            // Enhancement-12: connectivity-aliasing and plusarg functions. The
            // OSDI/ngspice target has no command-line plusargs, no generic
            // simulator probe and no runtime hierarchical node aliasing, so each
            // lowers to its LRM "mechanism-unavailable" result: a constant, with
            // no runtime callback or ngspice change. See Enhancement-12.md.
            //
            // `$test_plusargs`/`$value_plusargs` -> false (no plusarg is present).
            BuiltIn::test_plusargs | BuiltIn::value_plusargs => FALSE,
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
                self.ctx.ins().exit();

                // Create unreachable block for the remainder of iftrue (after $fatal).
                // Seal it (it is the replacement of the original iftrue block).
                // Because it has no incoming edges it will be removed from MIR.
                let unreachable_bb = self.ctx.create_block();
                self.ctx.switch_to_block(unreachable_bb);
                self.ctx.seal_block(unreachable_bb);

                GRAVESTONE
            }
            BuiltIn::analysis => {
                let arg = self.lower_expr(args[0]);
                self.ctx.call1(CallBackKind::Analysis, &[arg])
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
                let pwr = self.lower_expr(args[0]);
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
                let pwr = self.lower_expr(args[0]);
                let exp = self.lower_expr(args[1]);
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

            BuiltIn::table_model => self.lower_table_model(signature, args),

            BuiltIn::abstime => self.ctx.use_param(ParamKind::Abstime),

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
                        NATURE_ACCESS_BRANCH => self.ctx.use_param(ParamKind::Current(
                            CurrentKind::Branch(self.body.into_branch(args[0]))
                        )),
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
                    Some(temp) => self.lower_expr(*temp),
                    None => self.ctx.use_param(ParamKind::Temperature),
                };

                self.ctx.ins().fmul(fac, temp)
            }

            BuiltIn::ddx => {
                let val = self.lower_expr(args[0]);
                let unknown = self.lower_expr(args[1]);
                let call = if signature == DDX_POT {
                    // TODO how to handle gnd nodes?
                    let node = self.ctx.unwrap_node(unknown);
                    CallBackKind::NodeDerivative(node)
                } else {
                    CallBackKind::Derivative(self.ctx.dfg().value_def(unknown).unwrap_param())
                };
                self.ctx.call1(call, &[val])
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
            BuiltIn::param_given => self
                .ctx
                .use_param(ParamKind::ParamGiven { param: self.body.into_parameter(args[0]) }),
            BuiltIn::port_connected => {
                self.ctx.use_param(ParamKind::PortConnected { port: self.body.into_node(args[0]) })
            }
            BuiltIn::bound_step => {
                let step_size = self.lower_expr(args[0]);
                self.ctx.def_place(PlaceKind::BoundStep, step_size);
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
                if self.ctx.inside_lim && Some(-1) == self.body.as_literalsignedint(&args[0]) {
                    self.ctx.call(CallBackKind::LimDiscontinuity, &[]);
                } else {
                    // TODO implement support for discontinuity?
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
            // Return types follow OpenVAF's builtin signature table: `$random`
            // and `$arandom` are `Integer` (the real callback result is cast to
            // int with `ficast`), while *every* `$dist_*`/`$rdist_*` function is
            // typed `Real`. The LRM nonetheless specifies the `$dist_*` (as
            // opposed to `$rdist_*`) forms as integer-valued, so those round the
            // real draw to the nearest integer while keeping it a real value
            // (`rng_round_real`). The `$dist_*` integer parameters are coerced to
            // real for the shared real-argument callbacks via `lower_num_as_real`.
            BuiltIn::random | BuiltIn::arandom => {
                let seed = self.lower_rng_seed(args);
                let r = self.lower_rng(expr, RngFun::Random, seed, &[]);
                self.ctx.ins().ficast(r)
            }
            BuiltIn::rdist_uniform => {
                let seed = self.lower_expr(args[0]);
                let a = self.lower_expr(args[1]);
                let b = self.lower_expr(args[2]);
                self.lower_rng(expr, RngFun::Uniform, seed, &[a, b])
            }
            BuiltIn::dist_uniform => {
                let seed = self.lower_expr(args[0]);
                let a = self.lower_num_as_real(args[1]);
                let b = self.lower_num_as_real(args[2]);
                // `UniformInt` already returns an integral (but real) value.
                self.lower_rng(expr, RngFun::UniformInt, seed, &[a, b])
            }
            BuiltIn::rdist_normal => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                let sdev = self.lower_expr(args[2]);
                self.lower_rng(expr, RngFun::Normal, seed, &[mean, sdev])
            }
            BuiltIn::dist_normal => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                let sdev = self.lower_num_as_real(args[2]);
                let r = self.lower_rng(expr, RngFun::Normal, seed, &[mean, sdev]);
                self.rng_round_real(r)
            }
            BuiltIn::rdist_exponential => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                self.lower_rng(expr, RngFun::Exponential, seed, &[mean])
            }
            BuiltIn::dist_exponential => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                let r = self.lower_rng(expr, RngFun::Exponential, seed, &[mean]);
                self.rng_round_real(r)
            }
            BuiltIn::rdist_poisson => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_expr(args[1]);
                self.lower_rng(expr, RngFun::Poisson, seed, &[mean])
            }
            BuiltIn::dist_poisson => {
                let seed = self.lower_expr(args[0]);
                let mean = self.lower_num_as_real(args[1]);
                // `Poisson` already returns an integral (but real) count.
                self.lower_rng(expr, RngFun::Poisson, seed, &[mean])
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
                self.rng_round_real(r)
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
                self.rng_round_real(r)
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
                self.rng_round_real(r)
            }

            _ => unreachable!(),
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
    fn lower_scanf(&mut self, input: Value, var_args: &[ExprId]) -> Value {
        self.ctx.call(CallBackKind::ScanBegin, &[input]);
        for &arg in var_args {
            let var = self.body.into_variable(arg);
            let kind = match self.body.expr_type(arg) {
                Type::Integer => ScanKind::Int,
                Type::Real => ScanKind::Real,
                Type::String => ScanKind::Str,
                ty => unreachable!("invalid $sscanf target type {ty:?}"),
            };
            let val = self.ctx.call1(CallBackKind::Scan(kind), &[]);
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
            self.ctx.ins().ifcast(dir_int)
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
        let (pos_max, neg_max) = if signature == SLEW_POS_MAX {
            let rate = self.lower_expr(args[1]);
            (rate, rate)
        } else {
            debug_assert_eq!(signature, SLEW_NEG_MAX);
            (self.lower_expr(args[1]), self.lower_expr(args[2]))
        };
        let idx = self.ctx.intern.implicit_equations.len() as u32;
        self.lower_rate_limited_track(x, pos_max, neg_max, ImplicitEquationKind::Slew(idx))
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
        let x_int = self.lower_expr(args[0]);
        let x = self.ctx.ins().ifcast(x_int);
        if signature == TRANSITION_NO_ARGS {
            return x;
        }

        let td = self.lower_expr(args[1]);
        let delayed = self.lower_delay(x, td);
        if signature == TRANSITION_DELAY {
            return delayed;
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
        // Large but finite tracking gain (1/s); see `lower_slew` doc comment.
        const TRACK_GAIN: f64 = 1.0e9;

        let (eq, y) = self.ctx.implicit_equation(kind);
        let gain = self.ctx.fconst(TRACK_GAIN);
        let diff = self.ctx.ins().fsub(x, y);
        let rate = self.ctx.ins().fmul(gain, diff);

        let neg_max = self.ctx.ins().fneg(neg_max);
        let too_low = self.ctx.ins().flt(rate, neg_max);
        let rate = self.lower_select_with(too_low, |_| neg_max, |_| rate);
        let too_high = self.ctx.ins().fgt(rate, pos_max);
        let rate = self.lower_select_with(too_high, |_| pos_max, |_| rate);

        let resist = self.ctx.ins().fneg(rate);
        self.ctx.def_resist_residual(resist, eq);
        self.ctx.def_react_residual(y, eq);

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
    fn lower_laplace(&mut self, kind: BuiltIn, args: &[ExprId]) -> Value {
        let input = self.lower_expr(args[0]);

        let num_is_roots = matches!(kind, BuiltIn::laplace_zd | BuiltIn::laplace_zp);
        let den_is_roots = matches!(kind, BuiltIn::laplace_np | BuiltIn::laplace_zp);

        let num = self.lower_laplace_array_arg(args[1]);
        let den = self.lower_laplace_array_arg(args[2]);

        let num = if num_is_roots { self.laplace_roots_to_poly(&num) } else { num };
        let den = if den_is_roots { self.laplace_roots_to_poly(&den) } else { den };

        self.laplace_state_space(input, &num, &den)
    }

    /// Lowers a `num`/`den` (or `zero`/`pole`) argument of a `laplace_*` call to its element
    /// `Value`s, in ascending order. Two shapes are accepted (see `hir_ty::inference::
    /// infere_laplace_array_arg`): a bare reference to a module-body array variable, read
    /// directly via `ctx.read_variable` per element (no array-literal `ExprId`s exist for this
    /// case at all); or an ordinary array-literal expression (`'{a, b, c}'`/`{a, b, c}`), whose
    /// elements are lowered individually via `lower_expr` (falling back to treating the whole
    /// expression as a single-element array if it's neither — defensive, not expected to
    /// trigger given the type-level `ArrayAnyLength` requirement).
    fn lower_laplace_array_arg(&mut self, expr: ExprId) -> Vec<Value> {
        if let Some(vars) = self.body.array_var_ref(expr) {
            return vars.iter().map(|&var| self.ctx.read_variable(var)).collect();
        }

        let elem_ids: Vec<ExprId> = match self.body.get_expr(expr) {
            Expr::Array(elems) => elems.to_vec(),
            _ => vec![expr],
        };
        elem_ids.iter().map(|&e| self.lower_expr(e)).collect()
    }

    /// Expands a list of roots `[r0, r1, ...]` into ascending-power polynomial coefficients of
    /// `(s - r0)(s - r1)...`, i.e. `poly[i]` is the coefficient of `s^i`.
    fn laplace_roots_to_poly(&mut self, roots: &[Value]) -> Vec<Value> {
        let mut poly = vec![F_ONE];
        for &root in roots {
            let n = poly.len();
            let mut next = Vec::with_capacity(n + 1);
            for i in 0..=n {
                let rp = if i < n {
                    Some(self.ctx.ins().fmul(root, poly[i]))
                } else {
                    None
                };
                let term = match (i >= 1 && i - 1 < n, rp) {
                    (true, Some(rp)) => self.ctx.ins().fsub(poly[i - 1], rp),
                    (true, None) => poly[i - 1],
                    (false, Some(rp)) => self.ctx.ins().fneg(rp),
                    (false, None) => F_ZERO,
                };
                next.push(term);
            }
            poly = next;
        }
        poly
    }

    /// Builds a controllable-canonical-form state-space realization of `H(s) = num(s)/den(s)`
    /// (both ascending-power coefficient lists, `den` non-empty) driven by `input`, and returns
    /// the algebraic output value `y`.
    fn laplace_state_space(&mut self, input: Value, num: &[Value], den: &[Value]) -> Value {
        let n = den.len() - 1;
        let a_n = den[n];

        if n == 0 {
            // No dynamics: H(s) is a constant gain num[0]/den[0].
            let b0 = num.first().copied().unwrap_or(F_ZERO);
            let gain = self.ctx.ins().fdiv(b0, a_n);
            return self.ctx.ins().fmul(gain, input);
        }

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

        let num = self.lower_laplace_array_arg(args[1]);
        let den = self.lower_laplace_array_arg(args[2]);

        let num = if num_is_roots { self.laplace_roots_to_poly(&num) } else { num };
        let den = if den_is_roots { self.laplace_roots_to_poly(&den) } else { den };

        let t = self.lower_expr(args[3]);
        let f_half = self.ctx.fconst(0.5);
        let half_t = self.ctx.ins().fmul(t, f_half);

        let n = (den.len() - 1).max(num.len().saturating_sub(1));
        let num_s = self.bilinear_transform(&num, n, half_t);
        let den_s = self.bilinear_transform(&den, n, half_t);

        self.laplace_state_space(input, &num_s, &den_s)
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

        let mut enable_integral = self.ctx.use_param(ParamKind::EnableIntegration);
        let residual = if kind.has_ic() {
            if kind.has_assert() {
                enable_integral = self.lower_select_with(
                    enable_integral,
                    |mut s| {
                        let assert = s.lower_expr(args[2]);
                        s.ctx.ins().feq(assert, F_ZERO)
                    },
                    |_| FALSE,
                )
            }

            self.lower_multi_select(enable_integral, |mut ctx, branch| {
                if branch {
                    if kind.has_modulus() {
                        let modulus = ctx.lower_expr(args[2]);
                        let (min, max) = if kind.has_offset() {
                            let offset = ctx.lower_expr(args[2]);
                            (offset, ctx.ctx.ins().fadd(offset, modulus))
                        } else {
                            (F_ZERO, modulus)
                        };
                        let too_large = ctx.ctx.ins().fgt(val, max);
                        ctx.lower_multi_select(too_large, |mut ctx, too_large| {
                            if too_large {
                                [ctx.ctx.ins().fsub(val, min), F_ZERO]
                            } else {
                                let too_small = ctx.ctx.ins().flt(val, min);
                                ctx.lower_multi_select(too_small, |mut ctx, too_small| {
                                    if too_small {
                                        [ctx.ctx.ins().fsub(val, min), F_ZERO]
                                    } else {
                                        let arg = ctx.lower_expr(args[0]);
                                        [ctx.ctx.ins().fneg(arg), val]
                                    }
                                })
                            }
                        })
                    } else {
                        let arg = ctx.lower_expr(args[0]);
                        [ctx.ctx.ins().fneg(arg), val]
                    }
                } else {
                    let ic = ctx.lower_expr(args[1]);
                    [ctx.ctx.ins().fsub(val, ic), F_ZERO]
                }
            })
        } else {
            let arg = self.lower_expr(args[0]);
            [self.ctx.ins().fneg(arg), val]
        };

        self.ctx.def_resist_residual(residual[0], equation);
        self.ctx.def_react_residual(residual[1], equation);

        val
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
