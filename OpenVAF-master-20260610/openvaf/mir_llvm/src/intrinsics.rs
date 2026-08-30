use llvm_sys::{LLVMType as Type, LLVMValue as Value};

use crate::CodegenCx;

impl<'a, 'll> CodegenCx<'a, 'll> {
    pub fn intrinsic(&self, name: &'static str) -> Option<(&'ll Type, &'ll Value)> {
        if let Some(res) = self.intrinsics.borrow().get(name) {
            return Some(*res);
        }

        macro_rules! ifn {
            ($name:expr, fn($($arg:expr),* ;...) -> $ret:expr) => (
                if name == $name {
                    return Some(self.insert_intrinsic($name, &[$($arg),*], $ret, true));
                }
            );
            ($name:expr, fn($($arg:expr),*) -> $ret:expr) => (
                if name == $name {
                    return Some(self.insert_intrinsic($name, &[$($arg),*], $ret, false));
                }
            );
        }

        // let void = self.ty_void();
        let t_bool = self.ty_bool();
        let t_i32 = self.ty_int();
        let t_isize = self.ty_size();
        let t_f64 = self.ty_double();
        let t_str = self.ty_ptr();

        ifn!("llvm.pow.f64", fn(t_f64, t_f64) -> t_f64);
        ifn!("llvm.sqrt.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.sin.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.cos.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.exp.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.log.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.log10.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.log2.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.floor.f64", fn(t_f64) -> t_f64);
        // Enhancement-103: `ceil` was emitted by the codegen (`llvm.ceil.f64`)
        // but never registered here, so `ceil(x)` of any non-constant argument
        // crashed the compiler ("intrinsic llvm.ceil.f64 not found"). `floor`
        // above was registered; this is its missing sibling.
        ifn!("llvm.ceil.f64", fn(t_f64) -> t_f64);
        ifn!("llvm.fabs.f64", fn(t_f64) -> t_f64);
        // Enhancement-289: `llvm.ctlz` is an OVERLOADED intrinsic, so its name must carry the type
        // suffix -- `llvm.ctlz.i32`. Declaring the bare name produced a module LLVM
        // rejects ("Intrinsic name not mangled correctly for type arguments! Should
        // be: llvm.ctlz.i32"), the same shape of bug as the `hypot` arity above, and
        // likewise invisible in release because the verifier is a `debug_assert!`.
        // This backs `$clog2`.
        ifn!("llvm.ctlz.i32", fn(t_i32, t_bool) -> t_i32);

        // not technically intrinsics but part of the C standard library
        // TODO link custom mathematical functions
        ifn!("tan", fn(t_f64) -> t_f64);
        ifn!("acos", fn(t_f64) -> t_f64);
        ifn!("asin", fn(t_f64) -> t_f64);
        ifn!("atan", fn(t_f64) -> t_f64);
        ifn!("atan2", fn(t_f64, t_f64) -> t_f64);
        ifn!("sqrt", fn(t_f64) -> t_f64);
        ifn!("cosh", fn(t_f64) -> t_f64);
        ifn!("sinh", fn(t_f64) -> t_f64);
        ifn!("tanh", fn(t_f64) -> t_f64);
        ifn!("acosh", fn(t_f64) -> t_f64);
        ifn!("asinh", fn(t_f64) -> t_f64);
        ifn!("atanh", fn(t_f64) -> t_f64);
        // Enhancement-510: `log1p`/`expm1` are REQUESTED by the builder
        // (`Opcode::Ln1p`/`Opcode::Expm1`) but were never declared here, so
        // `cx.intrinsic("log1p")` returned None and codegen hit its own
        // `unreachable!("intrinsic log1p not found")`. Any `ln1p(x)`/`expm1(x)`
        // whose argument is not constant-folded away CRASHED the compiler
        // outright -- both spellings, in every context. The LRM lists these
        // apart from ln/exp precisely for their precision near zero, which is
        // why the builder asks for libm rather than `ln(1+x)`/`exp(x)-1`.
        ifn!("log1p", fn(t_f64) -> t_f64);
        ifn!("expm1", fn(t_f64) -> t_f64);

        if name == "hypot" {
            let name = if self.target.options.is_like_windows { "_hypot" } else { "hypot" };
            // Enhancement-288: `hypot` is BINARY -- like its neighbour `atan2` above, and unlike every
            // single-argument entry in this table. Declaring it `fn(f64) -> f64` while
            // `builder.rs` emits a two-argument call produced invalid LLVM IR
            // ("Incorrect number of arguments passed to called function!"). The module
            // verifier that would have caught this sits behind a `debug_assert!`, so
            // release builds emitted the malformed call instead of reporting it.
            return Some(self.insert_intrinsic(name, &[t_f64, t_f64], t_f64, false));
        }

        ifn!("strcmp", fn(t_str, t_str) -> t_i32);
        ifn!("llvm.lround.i32.f64", fn(t_f64) -> t_i32);

        if name == "snprintf" {
            return Some(self.insert_intrinsic("snprintf", &[t_str, t_isize, t_str], t_i32, true));
        }

        // ifn!("llvm.lifetime.start.p0i8", fn(t_i64, i8p) -> void);
        // ifn!("llvm.lifetime.end.p0i8", fn(t_i64, i8p) -> void);

        // ifn!("llvm.expect.i1", fn(i1, i1) -> i1);
        // ifn!("llvm.eh.typeid.for", fn(i8p) -> t_i32);
        // ifn!("llvm.localescape", fn(...) -> void);
        // ifn!("llvm.localrecover", fn(i8p, i8p, t_i32) -> i8p);

        // ifn!("llvm.assume", fn(i1) -> void);
        // ifn!("llvm.prefetch", fn(i8p, t_i32, t_i32, t_i32) -> void);

        // // This isn't an "LLVM intrinsic", but LLVM's optimization passes
        // // recognize it like one and we assume it exists in `core::slice::cmp`
        // ifn!("memcmp", fn(i8p, i8p, t_isize) -> t_i32);

        // // variadic intrinsics
        // ifn!("llvm.va_start", fn(i8p) -> void);
        // ifn!("llvm.va_end", fn(i8p) -> void);
        // ifn!("llvm.va_copy", fn(i8p, i8p) -> void);

        None
    }

    fn insert_intrinsic(
        &self,
        name: &'static str,
        args: &[&'ll Type],
        ret: &'ll Type,
        variadic: bool,
    ) -> (&'ll Type, &'ll Value) {
        let fn_ty =
            if variadic { self.ty_variadic_func(args, ret) } else { self.ty_func(args, ret) };
        let f = self.get_func_by_name(name).unwrap_or_else(|| self.declare_ext_fn(name, fn_ty));
        self.intrinsics.borrow_mut().insert(name, (fn_ty, f));
        (fn_ty, f)
    }
}
