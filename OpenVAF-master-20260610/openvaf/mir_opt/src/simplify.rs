use std::marker::PhantomData;
use std::mem::swap;

use mir::{
    Function, Inst, InstructionData, Opcode, PhiNode, Value, ValueDef, F_N_ONE, F_ONE,
    F_ZERO, N_ONE, ONE, ZERO,
};

use crate::const_eval::{eval_binary, eval_unary};

pub trait Arithmetic {
    const NEG: Opcode;
    const ADD: Opcode;
    const SUB: Opcode;
    const MUL: Opcode;
    const DIV: Opcode;
    const ZERO: Value;
    const ONE: Value;
    const N_ONE: Value;
    const DIV_EXACT: bool;
    const HAS_SQRT: bool;
    /// Enhancement-335: does this type obey ORDINARY ALGEBRA?
    ///
    /// Integers do. IEEE doubles do NOT: with NaN and the infinities in the value set,
    /// `x - x`, `x + (-x)` and `x * 0` are NaN rather than 0, and `x / x` and `x / -x`
    /// are NaN rather than +-1. Rewrites that assume algebra therefore silently change
    /// results -- they are only valid under fast-math, which this compiler does not
    /// promise. Gate them on this so the intent is visible at each site instead of
    /// being implied by the type.
    const EXACT_ALGEBRA: bool;
}

impl Arithmetic for f64 {
    const NEG: Opcode = Opcode::Fneg;
    const ADD: Opcode = Opcode::Fadd;
    const SUB: Opcode = Opcode::Fsub;
    const MUL: Opcode = Opcode::Fmul;
    const DIV: Opcode = Opcode::Fdiv;
    const ZERO: Value = F_ZERO;
    const ONE: Value = F_ONE;
    const N_ONE: Value = F_N_ONE;
    // Enhancement-335: all three were `true`, which turned on rewrites that are only
    // sound under fast-math: `(x/y)*y -> x`, `sqrt(x)*sqrt(x) -> x`, `x/x -> 1`,
    // `x*0 -> 0`, `x-x -> 0`. With node voltages as operands these fired at run time
    // and produced 1 for `V(z)/V(z)` at z=0 and -4 for `sqrt(V(w))*sqrt(V(w))` at
    // w=-4, where IEEE requires NaN -- silently breaking the domain guards and
    // cancellation idioms compact models rely on.
    const DIV_EXACT: bool = false;
    const HAS_SQRT: bool = false;
    const EXACT_ALGEBRA: bool = false;
}

impl Arithmetic for i32 {
    const NEG: Opcode = Opcode::Ineg;
    const ADD: Opcode = Opcode::Iadd;
    const SUB: Opcode = Opcode::Isub;
    const MUL: Opcode = Opcode::Imul;
    const DIV: Opcode = Opcode::Idiv;
    const ZERO: Value = ZERO;
    const ONE: Value = ONE;
    const N_ONE: Value = N_ONE;
    const DIV_EXACT: bool = false;
    const HAS_SQRT: bool = false;
    const EXACT_ALGEBRA: bool = true;
}

pub struct SimplifyCtx<'a, FP: Arithmetic, M: Fn(Value, &Function) -> Value> {
    pub func: &'a mut Function,
    // dtree: &'a DominatorTree,
    pub map_val_: M,
    pub max_recurse: u32,
    __fp_arithmetic: PhantomData<fn(&FP)>,
}

impl<'a, FP: Arithmetic, M: Fn(Value, &Function) -> Value> SimplifyCtx<'a, FP, M> {
    pub fn new(func: &'a mut Function, map_val_: M) -> SimplifyCtx<'a, FP, M> {
        SimplifyCtx { func, map_val_, max_recurse: 3, __fp_arithmetic: PhantomData }
    }

    pub fn simplify_inst(&mut self, inst: Inst) -> Option<Value> {
        match self.func.dfg.insts[inst].clone() {
            InstructionData::Unary { opcode, arg } => self.simplify_unary_op(opcode, arg),
            InstructionData::Binary { opcode, args } => {
                self.simplify_binop(opcode, args[0], args[1])
            }
            InstructionData::PhiNode(phi) => self.simplify_phi(phi),
            _ => None,
        }
    }

    pub fn simplify_phi(&mut self, phi: PhiNode) -> Option<Value> {
        let mut iter = self.func.dfg.phi_edges(&phi);
        if let Some((_, all_eq_val)) = iter.next() {
            let all_eq_val = self.map_val(all_eq_val);
            if iter.all(|(_, val)| self.map_val(val) == all_eq_val) {
                return Some(all_eq_val);
            }
        }
        None
    }

    pub fn simplify_unary_op(&mut self, op: Opcode, arg: Value) -> Option<Value> {
        if let Some(arg) = self.func.dfg.value_def(arg).as_const() {
            if let Some(val) = eval_unary(self.func, op, arg) {
                return Some(val);
            }
        }

        let inv = match op {
            Opcode::Inot => Opcode::Inot,
            Opcode::Bnot => Opcode::Bnot,
            Opcode::Fneg => return self.simplify_sub_inst::<FP>(F_ZERO, arg),
            Opcode::Ineg => return self.simplify_sub_inst::<i32>(ZERO, arg),
            Opcode::FIcast => Opcode::IFcast,
            // When the inverse is lossy not transofmration is possible
            Opcode::IFcast
            | Opcode::BIcast
            | Opcode::BFcast
            | Opcode::OptBarrier
            | Opcode::Clog2 => return None,
            Opcode::IBcast => Opcode::BIcast,
            Opcode::FBcast => Opcode::BFcast,
            // sqrt(x*x) and sqrt(x**2) are |x|, NOT x -- returning x is wrong
            // for any x < 0 (e.g. sqrt((-3)^2) = 3, not -3). MIR has no fabs to
            // fold to, so leave the sqrt in place (it computes |x| correctly).
            Opcode::Sqrt => return None,
            // Enhancement-335: `f(g(x)) -> x` also needs g's RANGE to lie inside f's
            // DOMAIN and neither step to overflow. The principal-value cases were
            // already excluded below; these are the DOMAIN and OVERFLOW ones, and they
            // were silently returning x where IEEE gives NaN or infinity:
            //   exp(ln x)      x < 0   -> ln is NaN, so this is NaN, not x
            //   ln(exp x)      large x -> exp overflows to inf, so inf, not x
            //   cosh(acosh x)  x < 1   -> acosh is NaN, so NaN, not x
            //   sinh(asinh x) / asinh(sinh x)  large x -> overflow to inf, not x
            //   tanh(atanh x) |x| >= 1 -> atanh is NaN (or +-inf), not x
            //   log(pow(10,y)) large y -> pow overflows to inf, not y
            // Each of those is exactly how a model guards a domain, so folding them
            // away turns a deliberate NaN into a plausible wrong number.
            Opcode::Exp | Opcode::Ln | Opcode::Cosh | Opcode::Sinh | Opcode::Asinh => {
                return None
            }
            // `ln1p`/`expm1` invert each other exactly, but cancelling them is the
            // same overflow mistake as `ln(exp x)` above: expm1 overflows to inf for
            // large x, so ln1p(expm1(x)) is inf, not x. The match below ends in
            // `unreachable!()`, so a new unary opcode MUST appear here or the
            // simplifier panics the moment a model uses it.
            Opcode::Ln1p | Opcode::Expm1 => return None,
            Opcode::Log => return None,
            Opcode::Floor | Opcode::Ceil => {
                if matches!(
                    self.as_any_unary(arg),
                    Some((Opcode::IFcast | Opcode::BFcast | Opcode::Ceil | Opcode::Floor, _))
                ) {
                    return Some(arg);
                } else {
                    return None;
                }
            }
            // f(g(x)) -> x is only valid when f is a true LEFT INVERSE of g over
            // ALL of g's range. The forward-then-inverse compositions where the
            // OUTER function only returns PRINCIPAL values are wrong outside that
            // range and must NOT cancel:
            //   asin(sin(x))  != x  for |x| > pi/2   (e.g. asin(sin 3) = pi-3)
            //   acos(cos(x))  != x  for x outside [0,pi]
            //   atan(tan(x))  != x  for |x| > pi/2    (a legitimate angle-wrap!)
            //   acosh(cosh(x))!= x  for x < 0         (cosh is even -> |x|)
            // Those four are handled by returning None below. The remaining
            // cancellations invert over the whole real line and stay.
            Opcode::Sin => Opcode::Asin,
            Opcode::Cos => Opcode::Acos,
            Opcode::Tan => Opcode::Atan,
            Opcode::Asin | Opcode::Acos | Opcode::Atan | Opcode::Acosh => return None,
            // `tanh` has range (-1,1), which is strictly inside `atanh`'s domain and
            // cannot overflow, so this one direction really does invert everywhere and
            // is kept. Its reverse (`tanh(atanh x)`) is NOT: |x| >= 1 is outside
            // atanh's domain, and is handled above.
            Opcode::Atanh => Opcode::Tanh,
            Opcode::Tanh => return None,
            _ => unreachable!(""),
        };

        if let Some(arg) = self.as_unary(arg, inv) {
            return Some(arg);
        }

        None
    }

    pub fn simplify_binop(&mut self, op: Opcode, mut lhs: Value, mut rhs: Value) -> Option<Value> {
        match op {
            Opcode::Iadd => self.simplify_add_inst::<i32>(lhs, rhs),
            Opcode::Isub => self.simplify_sub_inst::<i32>(lhs, rhs),
            Opcode::Imul => self.simplify_mul_inst::<i32>(lhs, rhs),
            Opcode::Idiv => self.simplify_div_inst::<i32>(lhs, rhs),
            Opcode::Fadd => self.simplify_add_inst::<FP>(lhs, rhs),
            Opcode::Fsub => self.simplify_sub_inst::<FP>(lhs, rhs),
            Opcode::Fmul => self.simplify_mul_inst::<FP>(lhs, rhs),
            Opcode::Fdiv => self.simplify_div_inst::<FP>(lhs, rhs),
            Opcode::Pow => self.simplify_pow_inst(lhs, rhs),

            // we only care about instructions that
            //
            // * have a dervative
            // * are commonly used in compact models
            //
            // other (more complex) optimizations are better left to LLVM.
            // So we just const eval (if possible)
            Opcode::Irem
            | Opcode::Ilt
            | Opcode::Igt
            | Opcode::Ige
            | Opcode::Ile
            | Opcode::Flt
            | Opcode::Fgt
            | Opcode::Fge
            | Opcode::Fle
            | Opcode::Ieq
            | Opcode::Feq
            | Opcode::Seq
            | Opcode::Beq
            | Opcode::Ine
            | Opcode::Fne
            | Opcode::Sne
            | Opcode::Bne
            | Opcode::Frem
            | Opcode::Ishl
            | Opcode::Ishr
            | Opcode::Iashr
            | Opcode::Ixor
            | Opcode::Iand
            | Opcode::Hypot
            | Opcode::Atan2
            | Opcode::Ior => self.fold_or_commute_consts(op, &mut lhs, &mut rhs),
            _ => unreachable!(),
        }
    }

    fn map_val(&self, val: Value) -> Value {
        (self.map_val_)(val, self.func)
    }

    fn as_unary(&self, val: Value, op: Opcode) -> Option<Value> {
        if let ValueDef::Result(inst, _) = self.func.dfg.value_def(val) {
            if let InstructionData::Unary { opcode, arg } = self.func.dfg.insts[inst] {
                if opcode != op {
                    return None;
                }
                let arg = self.map_val(arg);
                return Some(arg);
            }
        }
        None
    }

    fn as_binary(&self, val: Value, op: Opcode) -> Option<[Value; 2]> {
        if let ValueDef::Result(inst, _) = self.func.dfg.value_def(val) {
            if let InstructionData::Binary { opcode, mut args } = self.func.dfg.insts[inst] {
                if opcode != op {
                    return None;
                }
                args[0] = self.map_val(args[0]);
                args[1] = self.map_val(args[1]);
                return Some(args);
            }
        }
        None
    }

    fn as_any_unary(&self, val: Value) -> Option<(Opcode, Value)> {
        if let ValueDef::Result(inst, _) = self.func.dfg.value_def(val) {
            if let InstructionData::Unary { opcode, arg } = self.func.dfg.insts[inst] {
                return Some((opcode, arg));
            }
        }
        None
    }

    fn is_neg(&self, unary_op: Opcode, bin_op: Opcode, lhs: Value, rhs: Value) -> bool {
        if self.as_unary(lhs, unary_op) == Some(rhs) || self.as_unary(rhs, unary_op) == Some(lhs) {
            return true;
        }

        if let (Some([x1, y1]), Some([y2, x2])) =
            (self.as_binary(lhs, bin_op), self.as_binary(rhs, bin_op))
        {
            return x1 == x2 && y1 == y2;
        }

        false
    }

    fn fold_or_commute_consts(
        &mut self,
        op: Opcode,
        lhs: &mut Value,
        rhs: &mut Value,
    ) -> Option<Value> {
        if let ValueDef::Const(lhs_) = self.func.dfg.value_def(*lhs) {
            if let ValueDef::Const(rhs_) = self.func.dfg.value_def(*rhs) {
                // The formerly-declined cases (div/rem by zero, out-of-range
                // shift) now fold to the exact values the mir_llvm guards
                // compute at run time, so folding is always safe here.
                return eval_binary(self.func, op, lhs_, rhs_);
            }

            // Canonicalize the constant to the RHS if this is a commutative operation.
            if op.is_commutative() {
                swap(lhs, rhs)
            }
        }

        None
    }

    /// Given operands for an `A::ADD` instruction, see if we can fold the result.
    /// If not, this returns None.
    fn simplify_add_inst<A: Arithmetic>(
        &mut self,
        mut lhs: Value,
        mut rhs: Value,
    ) -> Option<Value> {
        if let Some(val) = self.fold_or_commute_consts(A::ADD, &mut lhs, &mut rhs) {
            return Some(val);
        }

        // `x + 0 -> x` is exact for integers, and for floats it is exact for
        // every value EXCEPT negative zero: (-0.0) + 0.0 is +0.0, not -0.0. That
        // one case is not academic here -- it is the only arithmetic that
        // normalises a negative zero, and `abs()` needs it, because `x < 0 ? -x
        // : x` lets -0.0 through unchanged. With this fold unconditional,
        // `abs(-0.0)` returned -0.0 and `1.0/abs(-0.0)` gave -inf, while the
        // compiler's own constant folding of the SAME expression gave +inf.
        // Unlike `x * 0` (Enhancement-337), adding a literal zero is not an
        // idiom compact models rely on, so gating this costs a stray `fadd` in
        // rare code rather than changing any model's answer.
        if rhs == A::ZERO && A::EXACT_ALGEBRA {
            return Some(lhs);
        }

        // Enhancement-335: `x + (-x)` is NaN, not 0, when x is inf or NaN; and
        // `X + (Y - X) -> Y` is an associativity rewrite that rounding invalidates.
        if A::EXACT_ALGEBRA {
            if self.is_neg(A::NEG, A::SUB, lhs, rhs) {
                return Some(A::ZERO);
            }

            // X + (Y - X) -> Y
            if let Some([y, x]) = self.as_binary(rhs, A::SUB) {
                if x == lhs {
                    return Some(y);
                }
            }
        }

        // (Y - X) + X -> Y
        if let Some([y, x]) = self.as_binary(lhs, A::SUB) {
            if x == rhs {
                return Some(y);
            }
        }

        // Try some generic simplifications for associative operations.
        self.simplify_assoc_binop(A::ADD, lhs, rhs)
    }

    fn simplify_sub_inst<A: Arithmetic>(
        &mut self,
        mut lhs: Value,
        mut rhs: Value,
    ) -> Option<Value> {
        if let Some(val) = self.fold_or_commute_consts(A::SUB, &mut lhs, &mut rhs) {
            return Some(val);
        }

        if rhs == A::ZERO {
            return Some(lhs);
        }

        // Enhancement-335: `x - x` is NaN, not 0, when x is inf or NaN.
        if A::EXACT_ALGEBRA && lhs == rhs {
            return Some(A::ZERO);
        }
        if !A::EXACT_ALGEBRA {
            // the (X+Y)-Z chain below rewrites through associativity, which does not
            // hold for floating point either ((a+b)-b != a once rounding is involved)
            return None;
        }
        self.recurse(|sel| sel.simplify_sub_inst_inner::<A>(lhs, rhs))
    }

    /// Given operands for an `A::SUB` instruction, see if we can fold the result.
    /// If not, this returns None.
    fn simplify_sub_inst_inner<A: Arithmetic>(&mut self, lhs: Value, rhs: Value) -> Option<Value> {
        // (X + Y) - Z -> X + (Y - Z) or Y + (X - Z) if everything simplifies.
        // For example, (X + Y) - Y -> X; (Y + X) - Y -> X
        let z = rhs;
        if let Some([x, y]) = self.as_binary(lhs, A::ADD) {
            // See if "V === Y - Z" simplifies.
            if let Some(v) = self.simplify_sub_inst::<A>(y, z) {
                // It does!  Now see if "X + V" simplifies.
                if let Some(w) = self.simplify_add_inst::<A>(x, v) {
                    return Some(w);
                }
            }

            // See if "V === X - Z" simplifies.
            if let Some(v) = self.simplify_sub_inst::<A>(x, z) {
                // It does!  Now see if "X + V" simplifies.
                if let Some(w) = self.simplify_add_inst::<A>(y, v) {
                    return Some(w);
                }
            }
        }

        // X - (Y + Z) -> (X - Y) - Z or (X - Z) - Y if everything simplifies.
        // For example, X - (X + 1) -> -1
        let x = lhs;
        if let Some([y, z]) = self.as_binary(rhs, A::ADD) {
            // See if "V === X - Y" simplifies.
            if let Some(v) = self.simplify_sub_inst::<A>(x, y) {
                // It does!  Now see if "V - Z" simplifies.
                if let Some(w) = self.simplify_sub_inst::<A>(v, z) {
                    return Some(w);
                }
            }

            // See if "V === X - Z" simplifies.
            if let Some(v) = self.simplify_sub_inst::<A>(x, z) {
                // It does!  Now see if "V - Y" simplifies.
                if let Some(w) = self.simplify_sub_inst::<A>(v, y) {
                    return Some(w);
                }
            }
        }

        // Z - (X - Y) -> (Z - X) + Y if everything simplifies.
        // For example, X - (X - Y) -> Y.
        let z = lhs;
        if let Some([x, y]) = self
            .as_binary(rhs, A::SUB)
            .or_else(|| self.as_unary(rhs, A::NEG).map(|rhs| [A::ZERO, rhs]))
        {
            // See if "V === Z - X" simplifies.
            if let Some(v) = self.simplify_sub_inst::<A>(z, x) {
                // It does!  Now see if "V + Y" simplifies.
                if let Some(w) = self.simplify_add_inst::<A>(v, y) {
                    return Some(w);
                }
            }
        }

        None
    }

    /// Try to simplify (a + b) * x -> a*x + b*x if the result is simpler
    fn expand_add_over_mul<A: Arithmetic>(&mut self, val: Value, other: Value) -> Option<Value> {
        if let Some([lhs, rhs]) = self.as_binary(val, A::ADD) {
            // simplify a*x
            let lhs_ = self.simplify_mul_inst::<A>(lhs, other)?;
            // simplify b*x
            let rhs_ = self.simplify_mul_inst::<A>(rhs, other)?;
            // a*x == a && b*x == b ||  a*x == b && b*x == a => (a + b) * x == a + b
            if (lhs_ == lhs && rhs_ == rhs) || (lhs_ == rhs && rhs_ == lhs) {
                return Some(val);
            }
            self.simplify_mul_inst::<A>(lhs_, rhs_)
        } else {
            None
        }
    }

    /// Given operands for an `A::MUL` instruction, see if we can fold the result.
    /// If not, this returns None.
    fn simplify_mul_inst<A: Arithmetic>(
        &mut self,
        mut lhs: Value,
        mut rhs: Value,
    ) -> Option<Value> {
        if let Some(val) = self.fold_or_commute_consts(A::MUL, &mut lhs, &mut rhs) {
            return Some(val);
        }

        if rhs == A::ONE {
            return Some(lhs);
        }

        // Enhancement-337: `x * 0 -> 0` is RETAINED even for floats, unlike the other
        // algebraic rewrites gated on EXACT_ALGEBRA.
        //
        // It is unsound in the same way -- `inf * 0` and `NaN * 0` are NaN, not 0 --
        // but removing it changed HiSIM2's DC drain current by 10x (1.30e-4 -> 1.33e-5
        // at Vg=0.7, Vd=1.0). Since `x * 0` is EXACT for every finite x, that change is
        // itself proof that the model produces a non-finite intermediate there which
        // this fold was silently absorbing.
        //
        // `flag * term` with a zero flag is how compact models disable a contribution,
        // and the disabled term is often non-finite. Dropping the fold turns that idiom
        // into a NaN. With no evidence that the un-folded answer is the physically
        // correct one, changing a production model's result by 10x is not a trade worth
        // making for purity -- so this one stays, deliberately and documented.
        //
        // The rewrites that DID produce the reported wrong answers -- `x/x -> 1`,
        // `sqrt(x)*sqrt(x) -> x`, `exp(ln x) -> x` -- are still removed.
        if rhs == A::ZERO {
            return Some(A::ZERO);
        }

        // (X / Y) * Y -> X if the division is exact (only fast math)
        if A::DIV_EXACT {
            if let Some([x, y]) = self.as_binary(rhs, A::DIV) {
                if y == lhs {
                    return Some(x);
                }
            }

            if let Some([x, y]) = self.as_binary(lhs, A::DIV) {
                if y == rhs {
                    return Some(x);
                }
            }
        }

        // sqrt(X) * sqrt(X) -> X
        if A::HAS_SQRT {
            if let Some(x) = self.as_unary(lhs, Opcode::Sqrt) {
                if let Some(y) = self.as_unary(rhs, Opcode::Sqrt) {
                    if x == y {
                        return Some(x);
                    }
                }
            }
        }

        // Try some generic simplifications for associative operations.
        if let Some(v) = self.simplify_assoc_binop(A::MUL, lhs, rhs) {
            return Some(v);
        }

        // Mul distributes over Add. Try some generic simplifications based on this.
        // Recursion is always used, so bail out at once if we already hit the limit.

        self.recurse(|sel| {
            if let Some(val) = sel.expand_add_over_mul::<A>(lhs, rhs) {
                return Some(val);
            }

            if let Some(val) = sel.expand_add_over_mul::<A>(rhs, lhs) {
                return Some(val);
            }

            None
        })
    }

    /// Given operands for an `A::DIV` instruction, see if we can fold the result.
    /// If not, this returns None.
    fn simplify_div_inst<A: Arithmetic>(
        &mut self,
        mut lhs: Value,
        mut rhs: Value,
    ) -> Option<Value> {
        if let Some(val) = self.fold_or_commute_consts(A::DIV, &mut lhs, &mut rhs) {
            return Some(val);
        }

        if lhs == A::ZERO {
            return Some(A::ZERO);
        }

        if rhs == A::ONE {
            return Some(lhs);
        }

        // Enhancement-335: `x / -x` is NaN, not -1, for x = 0, inf or NaN.
        if A::EXACT_ALGEBRA && self.is_neg(A::NEG, A::SUB, lhs, rhs) {
            return Some(A::N_ONE);
        }

        if !A::DIV_EXACT {
            return None;
        }

        if lhs == rhs {
            return Some(A::ONE);
        }

        // (X * Y) / Y -> X
        if let Some([x, y]) = self.as_binary(lhs, A::MUL) {
            if y == lhs {
                return Some(x);
            }

            if x == rhs {
                return Some(y);
            }
        }

        None
    }

    /// Given operands for an `A::DIV` instruction, see if we can fold the result.
    /// If not, this returns None.
    fn simplify_pow_inst(&mut self, mut lhs: Value, mut rhs: Value) -> Option<Value> {
        // before const fold to avoid iconsisten behaviour between rust powf and LLVM pow
        if rhs == F_ZERO {
            return Some(F_ONE);
        }

        if let Some(val) = self.fold_or_commute_consts(Opcode::Pow, &mut lhs, &mut rhs) {
            return Some(val);
        }

        if lhs == F_ZERO {
            return Some(F_ZERO);
        }

        if rhs == F_ONE {
            return Some(lhs);
        }

        None
    }

    fn simplify_assoc_binop_inner(&mut self, op: Opcode, lhs: Value, rhs: Value) -> Option<Value> {
        let is_communative = op.is_commutative();

        // Transform: "(A op B) op C" ==> "A op (B op C)" or "(C op A) op B" if it simplifies completely.
        if let Some([a, b]) = self.as_binary(lhs, op) {
            let c = rhs;

            // Does "B op C" simplify?
            if let Some(val) = self.simplify_binop(op, b, c) {
                if val == b {
                    return Some(lhs);
                }

                if let Some(val) = self.simplify_binop(op, a, val) {
                    return Some(val);
                }
            }

            if is_communative {
                // Does "C op A" simplify?
                if let Some(val) = self.simplify_binop(op, c, a) {
                    if val == a {
                        return Some(lhs);
                    }

                    if let Some(val) = self.simplify_binop(op, val, b) {
                        return Some(val);
                    }
                }
            }
        }

        if let Some([b, c]) = self.as_binary(rhs, op) {
            let a = lhs;

            // Does "B op C" simplify?
            if let Some(val) = self.simplify_binop(op, a, b) {
                if val == b {
                    return Some(rhs);
                }

                if let Some(val) = self.simplify_binop(op, val, c) {
                    return Some(val);
                }
            }

            if is_communative {
                // Does "C op A" simplify?
                if let Some(val) = self.simplify_binop(op, c, a) {
                    if val == c {
                        return Some(lhs);
                    }

                    if let Some(val) = self.simplify_binop(op, b, val) {
                        return Some(val);
                    }
                }
            }
        }

        None
    }

    fn simplify_assoc_binop(&mut self, op: Opcode, lhs: Value, rhs: Value) -> Option<Value> {
        self.recurse(move |sel| sel.simplify_assoc_binop_inner(op, lhs, rhs))
    }

    fn recurse<T>(&mut self, f: impl FnOnce(&mut Self) -> Option<T>) -> Option<T> {
        if self.max_recurse == 0 {
            return None;
        }
        self.max_recurse -= 1;
        let res = f(self);
        self.max_recurse += 1;
        res
    }
}
