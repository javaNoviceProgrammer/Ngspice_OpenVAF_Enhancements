use core::ffi::c_uint;
use std::ptr::NonNull;

use llvm_sys::core::{
    LLVMAddIncoming, LLVMBuildAdd, LLVMBuildBr, LLVMBuildCondBr, LLVMBuildICmp, LLVMBuildLoad2,
    LLVMBuildPhi, LLVMGetBasicBlockParent, LLVMGetInsertBlock,
    LLVMAppendBasicBlockInContext, LLVMBuildCall2, LLVMBuildFAdd, LLVMBuildFCmp, LLVMBuildFDiv,
    LLVMBuildFMul, LLVMBuildFSub, LLVMBuildGEP2, LLVMBuildRetVoid, LLVMBuildSelect, LLVMBuildStore,
    LLVMCreateBuilderInContext, LLVMDisposeBuilder, LLVMGetParam, LLVMPositionBuilderAtEnd,
};
use llvm_sys::LLVMIntPredicate::LLVMIntULT;
use llvm_sys::LLVMRealPredicate;
use mir_llvm::UNNAMED;
use sim_back::dae::NoiseSourceKind;
use stdx::iter::zip;
use typed_index_collections::TiVec;

use crate::compilation_unit::OsdiCompilationUnit;
#[derive(Debug, Clone, Copy)]
pub enum JacobianLoadType {
    Tran,
    Resist,
    React,
}

impl JacobianLoadType {
    const fn dst_reactive(self) -> bool {
        matches!(self, JacobianLoadType::React)
    }

    const fn read_resistive(self) -> bool {
        matches!(self, JacobianLoadType::Resist | JacobianLoadType::Tran)
    }

    const fn read_reactive(self) -> bool {
        matches!(self, JacobianLoadType::React | JacobianLoadType::Tran)
    }

    const fn name(self) -> &'static str {
        match self {
            JacobianLoadType::Tran => "tran",
            JacobianLoadType::Resist => "resist",
            JacobianLoadType::React => "react",
        }
    }
}

impl<'ll> OsdiCompilationUnit<'_, '_, 'll> {
    /// Emit the LLVM IR that evaluates a `noise_table`/`noise_table_log` power
    /// spectral density at run time for a given `freq`.
    ///
    /// `vals` are the sorted pairs produced by `hir_lower::NoiseTable::new`
    /// (Enhancement-109):
    ///  * `noise_table` (`log == false`): raw `(f, power)` -- the lookup key is
    ///    the raw frequency and the interpolation is piecewise LINEAR in `f`
    ///    (LRM 4.6.4.3).
    ///  * `noise_table_log` (`log == true`): `(log10 f, log10 power)` -- the key
    ///    is `log10(freq)`, the interpolation is linear in that space, and the
    ///    result is exponentiated (`10^v`), giving the LRM 4.6.4.4 log-log
    ///    formula.
    /// Outside `[x[0], x[n-1]]` the power clamps to the endpoint values.
    ///
    /// The interpolation is fully unrolled into `select`s: every segment's
    /// slope/intercept is a compile-time constant, so each segment costs one
    /// `fmul`, one `fadd`, one `fcmp` and one `select`.
    unsafe fn build_noise_table_interp(
        &self,
        llbuilder: llvm_sys::prelude::LLVMBuilderRef,
        freq: llvm_sys::prelude::LLVMValueRef,
        vals: &[(stdx::Ieee64, stdx::Ieee64)],
        log: bool,
    ) -> &'ll llvm_sys::LLVMValue {
        let cx = self.cx;
        let n = vals.len();
        if n == 0 {
            return cx.const_real(0.0);
        }
        let x: Vec<f64> = vals.iter().map(|v| f64::from(v.0)).collect();
        let y: Vec<f64> = vals.iter().map(|v| f64::from(v.1)).collect();
        if n == 1 {
            // A single point: constant power (for the log form `y` holds
            // log10(power), so exponentiate back).
            return if log { cx.const_real(10f64.powf(y[0])) } else { cx.const_real(y[0]) };
        }

        // Lookup key: log10(freq) for the log-log form, the raw frequency for
        // the linear form.
        let lx = if log {
            let (log_ty, log_fn) = self
                .cx
                .intrinsic("llvm.log10.f64")
                .unwrap_or_else(|| unreachable!("intrinsic llvm.log10.f64 not found"));
            let mut log_args: [llvm_sys::prelude::LLVMValueRef; 1] = [freq];
            LLVMBuildCall2(
                llbuilder,
                NonNull::from(log_ty).as_ptr(),
                NonNull::from(log_fn).as_ptr(),
                log_args.as_mut_ptr(),
                1,
                UNNAMED,
            )
        } else {
            freq
        };

        // Enhancement-713 (robustness campaign F7 of 2026-09-23): the segment
        // search was a chain of n selects emitted straight into the function --
        // 2 000 pairs made 4 000 lines that LLVM's instruction combiner took 9 s
        // over, 5 000 pairs a minute. The table is three constant arrays now
        // (upper bound, slope and intercept per segment) and the search a loop
        // over them: the first segment whose upper bound exceeds `lx`, the last
        // point when none does -- exactly the chain's answer for any data,
        // sorted or not, NaN included -- in constant code.
        let ty_double = cx.ty_double();
        let ty_int = cx.ty_int();
        let mut hi_vals = Vec::with_capacity(n - 1);
        let mut slope_vals = Vec::with_capacity(n - 1);
        let mut icpt_vals = Vec::with_capacity(n - 1);
        for i in 0..n - 1 {
            let slope = (y[i + 1] - y[i]) / (x[i + 1] - x[i]);
            let intercept = y[i] - slope * x[i];
            hi_vals.push(cx.const_real(x[i + 1]));
            slope_vals.push(cx.const_real(slope));
            icpt_vals.push(cx.const_real(intercept));
        }
        let hi_arr = NonNull::from(cx.const_arr_ptr(ty_double, &hi_vals)).as_ptr();
        let slope_arr = NonNull::from(cx.const_arr_ptr(ty_double, &slope_vals)).as_ptr();
        let icpt_arr = NonNull::from(cx.const_arr_ptr(ty_double, &icpt_vals)).as_ptr();

        let llcx = NonNull::from(cx.llcx).as_ptr();
        let cur_bb = LLVMGetInsertBlock(llbuilder);
        let f = LLVMGetBasicBlockParent(cur_bb);
        let hdr = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
        let chk = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
        let next = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
        let found = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
        let merge = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
        let ty_int_p = NonNull::from(ty_int).as_ptr();
        let ty_double_p = NonNull::from(ty_double).as_ptr();
        let c0 = NonNull::from(cx.const_unsigned_int(0)).as_ptr();
        let c1 = NonNull::from(cx.const_unsigned_int(1)).as_ptr();
        let c_segs = NonNull::from(cx.const_unsigned_int((n - 1) as u32)).as_ptr();
        let y_last = NonNull::from(cx.const_real(y[n - 1])).as_ptr();

        LLVMBuildBr(llbuilder, hdr);

        // for (i = 0; i < n - 1; i++) if (lx < hi[i]) break;
        LLVMPositionBuilderAtEnd(llbuilder, hdr);
        let i = LLVMBuildPhi(llbuilder, ty_int_p, UNNAMED);
        let in_range = LLVMBuildICmp(llbuilder, LLVMIntULT, i, c_segs, UNNAMED);
        LLVMBuildCondBr(llbuilder, in_range, chk, merge);

        LLVMPositionBuilderAtEnd(llbuilder, chk);
        let mut idx = [i];
        let hi_ptr = LLVMBuildGEP2(llbuilder, ty_double_p, hi_arr, idx.as_mut_ptr(), 1, UNNAMED);
        let hi = LLVMBuildLoad2(llbuilder, ty_double_p, hi_ptr, UNNAMED);
        let below = LLVMBuildFCmp(llbuilder, LLVMRealPredicate::LLVMRealOLT, lx, hi, UNNAMED);
        LLVMBuildCondBr(llbuilder, below, found, next);

        LLVMPositionBuilderAtEnd(llbuilder, next);
        let i1 = LLVMBuildAdd(llbuilder, i, c1, UNNAMED);
        LLVMBuildBr(llbuilder, hdr);
        let mut i_vals = [c0, i1];
        let mut i_bbs = [cur_bb, next];
        LLVMAddIncoming(i, i_vals.as_mut_ptr(), i_bbs.as_mut_ptr(), 2);

        // seg = slope[i] * lx + intercept[i]
        LLVMPositionBuilderAtEnd(llbuilder, found);
        let slope_ptr =
            LLVMBuildGEP2(llbuilder, ty_double_p, slope_arr, idx.as_mut_ptr(), 1, UNNAMED);
        let slope = LLVMBuildLoad2(llbuilder, ty_double_p, slope_ptr, UNNAMED);
        let icpt_ptr = LLVMBuildGEP2(llbuilder, ty_double_p, icpt_arr, idx.as_mut_ptr(), 1, UNNAMED);
        let icpt = LLVMBuildLoad2(llbuilder, ty_double_p, icpt_ptr, UNNAMED);
        let seg = LLVMBuildFMul(llbuilder, slope, lx, UNNAMED);
        let seg = LLVMBuildFAdd(llbuilder, seg, icpt, UNNAMED);
        LLVMBuildBr(llbuilder, merge);

        // no segment: clamp to the last point
        LLVMPositionBuilderAtEnd(llbuilder, merge);
        let mut result = LLVMBuildPhi(llbuilder, ty_double_p, UNNAMED);
        let mut r_vals = [seg, y_last];
        let mut r_bbs = [found, hdr];
        LLVMAddIncoming(result, r_vals.as_mut_ptr(), r_bbs.as_mut_ptr(), 2);

        // Clamp below x[0] to the first point (otherwise segment 0 would
        // extrapolate below the table).
        let cond0 = LLVMBuildFCmp(
            llbuilder,
            LLVMRealPredicate::LLVMRealOLT,
            lx,
            NonNull::from(cx.const_real(x[0])).as_ptr(),
            UNNAMED,
        );
        result = LLVMBuildSelect(
            llbuilder,
            cond0,
            NonNull::from(cx.const_real(y[0])).as_ptr(),
            result,
            UNNAMED,
        );

        // Enhancement-109: the log-log form interpolated log10(power); map it
        // back to a power: 10^v = exp(v * ln 10).
        if log {
            let scaled = LLVMBuildFMul(
                llbuilder,
                result,
                NonNull::from(cx.const_real(core::f64::consts::LN_10)).as_ptr(),
                UNNAMED,
            );
            let (exp_ty, exp_fn) = self
                .cx
                .intrinsic("llvm.exp.f64")
                .unwrap_or_else(|| unreachable!("intrinsic llvm.exp.f64 not found"));
            let mut exp_args: [llvm_sys::prelude::LLVMValueRef; 1] = [scaled];
            result = LLVMBuildCall2(
                llbuilder,
                NonNull::from(exp_ty).as_ptr(),
                NonNull::from(exp_fn).as_ptr(),
                exp_args.as_mut_ptr(),
                1,
                UNNAMED,
            );
        }

        &*result
    }

    pub fn load_noise(&self) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = self;
        let void_ptr = cx.ty_ptr();
        let f64_ptr_ty = cx.ty_ptr();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, cx.ty_double(), f64_ptr_ty], cx.ty_void());
        let name = &format!("load_noise_{}", module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());
            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let inst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let freq = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);
            let dst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 3);

            // Enhancement-51: ac_stim sources share the eval-output slots but are
            // excluded from the noise descriptor arrays; `slot` tracks the position
            // in the FILTERED array so `dst` stays aligned with `noise_sources`.
            let mut slot = 0u32;
            for (src, eval_outputs) in
                zip(&module.dae_system.noise_sources, &self.inst_data.noise)
            {
                if matches!(src.kind, NoiseSourceKind::AcStim { .. }) {
                    continue;
                }
                let i = slot;
                slot += 1;
                let fac = self.load_eval_output(eval_outputs.factor, &*inst, &*model, &*llbuilder);
                let pwr = match src.kind {
                    NoiseSourceKind::WhiteNoise { .. } => {
                        self.load_eval_output(eval_outputs.args[0], &*inst, &*model, &*llbuilder)
                    }
                    NoiseSourceKind::FlickerNoise { .. } => {
                        let mut pwr = self.load_eval_output(
                            eval_outputs.args[0],
                            &*inst,
                            &*model,
                            &*llbuilder,
                        );
                        let exp = &*self.load_eval_output(
                            eval_outputs.args[1],
                            &*inst,
                            &*model,
                            &*llbuilder,
                        );
                        let (ty, fun) = self
                            .cx
                            .intrinsic("llvm.pow.f64")
                            .unwrap_or_else(|| unreachable!("intrinsic {} not found", name));

                        let freq_val = freq as *const llvm_sys::LLVMValue as *mut _;
                        let exp_val = &*exp as *const llvm_sys::LLVMValue as *mut _;
                        let mut call_args: [llvm_sys::prelude::LLVMValueRef; 2] =
                            [freq_val, exp_val];
                        let args_ptr = call_args.as_mut_ptr();

                        let freq_exp = LLVMBuildCall2(
                            llbuilder,
                            NonNull::from(ty).as_ptr(),
                            NonNull::from(fun).as_ptr(),
                            args_ptr,
                            2,
                            UNNAMED,
                        );
                        let fast_math_flags: c_uint = 0x01 | 0x02 | 0x10; // Reassoc | Reciprocal | Contract
                        llvm_sys::core::LLVMSetFastMathFlags(freq_exp, fast_math_flags);

                        pwr = &*LLVMBuildFDiv(
                            llbuilder,
                            NonNull::from(pwr).as_ptr(),
                            freq_exp,
                            UNNAMED,
                        );
                        let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                        llvm_sys::core::LLVMSetFastMathFlags(
                            NonNull::from(pwr).as_ptr(),
                            fast_math_flags,
                        );

                        pwr
                    }
                    NoiseSourceKind::NoiseTable { ref vals, log } => {
                        let freq_ptr = freq as *const llvm_sys::LLVMValue as *mut _;
                        self.build_noise_table_interp(llbuilder, freq_ptr, vals, log)
                    }
                    NoiseSourceKind::AcStim { .. } => unreachable!("filtered above"),
                };

                // Multiply with the squared factor because the factor is in terms of the
                // signal while we are computing the power, which scales by factor**2.
                //
                // Enhancement-42: fold it as `fac * |fac|` rather than `fac * fac`, so the
                // loaded power CARRIES THE FACTOR'S SIGN (its magnitude is identical).
                // ngspice's noise analysis takes `fabs()` of each source's power before
                // using it, so nothing changes for independent sources -- but the sign is
                // what lets same-named (perfectly correlated, LRM 4.6.4) sources sum
                // coherently as amplitudes in `osdinoise.c`, including cancellation
                // between anti-phase contributions (`... <+ -white_noise(S, "n")`).
                //
                // Enhancement-54: `dst` holds PAIRS per source: dst[2i] is the flat
                // signed power (fac * |fac| * pwr) and dst[2i+1] the j*omega
                // component's signed power (fac_react * |fac_react| * pwr) for a
                // noise wave routed through ddt(); the simulator combines them as
                // the complex amplitude (a + j*omega*b) * T per source.
                let (fabs_ty, fabs_fn) = self
                    .cx
                    .intrinsic("llvm.fabs.f64")
                    .unwrap_or_else(|| unreachable!("intrinsic llvm.fabs.f64 not found"));
                let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                let base_pwr = pwr;
                let store_folded = |fac: &'ll llvm_sys::LLVMValue, index: u32| {
                    let mut fabs_args: [llvm_sys::prelude::LLVMValueRef; 1] =
                        [fac as *const llvm_sys::LLVMValue as *mut _];
                    let fac_abs = LLVMBuildCall2(
                        llbuilder,
                        NonNull::from(fabs_ty).as_ptr(),
                        NonNull::from(fabs_fn).as_ptr(),
                        fabs_args.as_mut_ptr(),
                        1,
                        UNNAMED,
                    );
                    let mut pwr = LLVMBuildFMul(
                        llbuilder,
                        NonNull::from(base_pwr).as_ptr(),
                        NonNull::from(fac).as_ptr(),
                        UNNAMED,
                    );
                    llvm_sys::core::LLVMSetFastMathFlags(pwr, fast_math_flags);
                    pwr = LLVMBuildFMul(llbuilder, pwr, fac_abs, UNNAMED);
                    llvm_sys::core::LLVMSetFastMathFlags(pwr, fast_math_flags);
                    let index_val =
                        cx.const_unsigned_int(index) as *const llvm_sys::LLVMValue as *mut _;
                    let mut gep_indices: [llvm_sys::prelude::LLVMValueRef; 1] = [index_val];
                    let gep_ptr = gep_indices.as_mut_ptr();

                    let dst = LLVMBuildGEP2(
                        llbuilder,
                        NonNull::from(cx.ty_double()).as_ptr(),
                        dst,
                        gep_ptr,
                        1,
                        UNNAMED,
                    );
                    LLVMBuildStore(llbuilder, pwr, dst);
                };
                store_folded(fac, 2 * i);
                let fac_react = self.load_eval_output(
                    eval_outputs.factor_react,
                    &*inst,
                    &*model,
                    &*llbuilder,
                );
                store_folded(fac_react, 2 * i + 1);
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    /// Enhancement-51: `void load_ac_stim(void* inst, void* model, double* dst)`
    /// -- fills `dst` with `[re, im]` PAIRS, one per `ac_stim_sources` entry (in
    /// descriptor order): `factor * mag * cos(phase)` / `factor * mag * sin(phase)`.
    /// The simulator adds each pair into its complex AC RHS at the source's
    /// mapped nodes (+ at node_1, - at node_2) when the analysis name matches.
    pub fn load_ac_stim(&self) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = self;
        let void_ptr = cx.ty_ptr();
        let f64_ptr_ty = cx.ty_ptr();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, f64_ptr_ty], cx.ty_void());
        let name = &format!("load_ac_stim_{}", module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());
            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let inst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let dst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);

            let mut slot = 0u32;
            for (src, eval_outputs) in
                zip(&module.dae_system.noise_sources, &self.inst_data.noise)
            {
                if !matches!(src.kind, NoiseSourceKind::AcStim { .. }) {
                    continue;
                }
                let fac = self.load_eval_output(eval_outputs.factor, &*inst, &*model, &*llbuilder);
                let mag = self.load_eval_output(eval_outputs.args[0], &*inst, &*model, &*llbuilder);
                let phase =
                    self.load_eval_output(eval_outputs.args[1], &*inst, &*model, &*llbuilder);

                let amp = &*LLVMBuildFMul(
                    llbuilder,
                    NonNull::from(fac).as_ptr(),
                    NonNull::from(mag).as_ptr(),
                    UNNAMED,
                );

                let trig = |intrinsic: &'static str| {
                    let (ty, fun) = self
                        .cx
                        .intrinsic(intrinsic)
                        .unwrap_or_else(|| unreachable!("intrinsic {intrinsic} not found"));
                    let mut call_args: [llvm_sys::prelude::LLVMValueRef; 1] =
                        [phase as *const llvm_sys::LLVMValue as *mut _];
                    &*LLVMBuildCall2(
                        llbuilder,
                        NonNull::from(ty).as_ptr(),
                        NonNull::from(fun).as_ptr(),
                        call_args.as_mut_ptr(),
                        1,
                        UNNAMED,
                    )
                };
                let cos_p = trig("llvm.cos.f64");
                let sin_p = trig("llvm.sin.f64");

                let re = LLVMBuildFMul(
                    llbuilder,
                    NonNull::from(amp).as_ptr(),
                    NonNull::from(cos_p).as_ptr(),
                    UNNAMED,
                );
                let im = LLVMBuildFMul(
                    llbuilder,
                    NonNull::from(amp).as_ptr(),
                    NonNull::from(sin_p).as_ptr(),
                    UNNAMED,
                );

                let store = |val: llvm_sys::prelude::LLVMValueRef, idx: u32| {
                    let index_val =
                        cx.const_unsigned_int(idx) as *const llvm_sys::LLVMValue as *mut _;
                    let mut gep_indices: [llvm_sys::prelude::LLVMValueRef; 1] = [index_val];
                    let slot_ptr = LLVMBuildGEP2(
                        llbuilder,
                        NonNull::from(cx.ty_double()).as_ptr(),
                        dst,
                        gep_indices.as_mut_ptr(),
                        1,
                        UNNAMED,
                    );
                    LLVMBuildStore(llbuilder, val, slot_ptr);
                };
                store(re, 2 * slot);
                store(im, 2 * slot + 1);
                slot += 1;
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    
    
    
    pub fn load_noise_params(&self) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = self;
        let void_ptr = cx.ty_ptr();
        let f64_ptr_ty = cx.ty_ptr();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, f64_ptr_ty, f64_ptr_ty], cx.ty_void());
        let name = &format!("load_noise_params_{}", module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());
            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let inst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let dst_dens = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);
            let dst_exp = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 3);

            // Enhancement-51: skip ac_stim entries; `slot` = filtered index
            let mut slot = 0u32;
            for (src, eval_outputs) in
                zip(&module.dae_system.noise_sources, &self.inst_data.noise)
            {
                if matches!(src.kind, NoiseSourceKind::AcStim { .. }) {
                    continue;
                }
                let i = slot;
                slot += 1;
                // Factor and power
                let fac = self.load_eval_output(eval_outputs.factor, &*inst, &*model, &*llbuilder);
                let mut pwr = match src.kind {
                    NoiseSourceKind::WhiteNoise { .. } => {
                        self.load_eval_output(eval_outputs.args[0], &*inst, &*model, &*llbuilder)
                    }
                    NoiseSourceKind::FlickerNoise { .. } => {
                        self.load_eval_output(eval_outputs.args[0], &*inst, &*model, &*llbuilder)
                    }
                    // A frequency-dependent table has no single scalar power; the
                    // per-frequency `load_noise` entry point is the real evaluator
                    // (this ABI slot is unused by ngspice's OSDI noise path).
                    NoiseSourceKind::NoiseTable { .. } => cx.const_real(0.0),
                    NoiseSourceKind::AcStim { .. } => unreachable!("filtered above"),
                };

                // Multiply with squared factor because factor is in terms of signal, but
                // we are computing the power, which is scaled by factor**2.
                pwr = &*LLVMBuildFMul(
                    llbuilder,
                    NonNull::from(pwr).as_ptr(),
                    NonNull::from(fac).as_ptr(),
                    UNNAMED,
                );
                let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                llvm_sys::core::LLVMSetFastMathFlags(NonNull::from(pwr).as_ptr(), fast_math_flags);
                pwr = &*LLVMBuildFMul(
                    llbuilder,
                    NonNull::from(pwr).as_ptr(),
                    NonNull::from(fac).as_ptr(),
                    UNNAMED,
                );
                llvm_sys::core::LLVMSetFastMathFlags(NonNull::from(pwr).as_ptr(), fast_math_flags);

                // Exponent
                let exp = match src.kind {
                    NoiseSourceKind::WhiteNoise { .. } => cx.const_real(0.0),
                    NoiseSourceKind::FlickerNoise { .. } => {
                        self.load_eval_output(eval_outputs.args[1], &*inst, &*model, &*llbuilder)
                    }
                    NoiseSourceKind::NoiseTable { .. } => cx.const_real(0.0),
                    NoiseSourceKind::AcStim { .. } => unreachable!("filtered above"),
                };

                // Store power
                let index_val =
                    cx.const_unsigned_int(i) as *const llvm_sys::LLVMValue as *mut _;
                let mut gep_indices: [llvm_sys::prelude::LLVMValueRef; 1] = [index_val];
                let gep_ptr = gep_indices.as_mut_ptr();

                let dst_dens = LLVMBuildGEP2(
                    llbuilder,
                    NonNull::from(cx.ty_double()).as_ptr(),
                    dst_dens,
                    gep_ptr,
                    1,
                    UNNAMED,
                );
                LLVMBuildStore(llbuilder, NonNull::from(pwr).as_ptr(), dst_dens);

                // Store exponent
                let index_val =
                    cx.const_unsigned_int(i) as *const llvm_sys::LLVMValue as *mut _;
                let mut gep_indices: [llvm_sys::prelude::LLVMValueRef; 1] = [index_val];
                let gep_ptr = gep_indices.as_mut_ptr();

                let dst_exp = LLVMBuildGEP2(
                    llbuilder,
                    NonNull::from(cx.ty_double()).as_ptr(),
                    dst_exp,
                    gep_ptr,
                    1,
                    UNNAMED,
                );
                LLVMBuildStore(llbuilder, NonNull::from(exp).as_ptr(), dst_exp);
            }

            // TODO noise
            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    pub fn load_residual(&self, reactive: bool) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { inst_data, cx, module, .. } = self;
        let ptr_ty = cx.ty_ptr();
        let fun_ty = cx.ty_func(&[ptr_ty, ptr_ty, ptr_ty], cx.ty_void());
        let name =
            &format!("load_residual_{}_{}", if reactive { "react" } else { "resist" }, module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());

            LLVMPositionBuilderAtEnd(llbuilder, entry);

            // get params
            let inst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let dst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);

            for node in module.dae_system.unknowns.indices() {
                if let Some(contrib) = inst_data.read_residual(node, inst, &*llbuilder, reactive) {
                    inst_data.store_contrib(cx, node, inst, dst, contrib, &*llbuilder, false);
                }
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    pub fn load_lim_rhs(&self, reactive: bool) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { inst_data, cx, module, .. } = self;
        let void_ptr = cx.ty_ptr();
        let f64_ptr_ty = cx.ty_ptr();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, f64_ptr_ty], cx.ty_void());
        let name =
            &format!("load_lim_rhs_{}_{}", if reactive { "react" } else { "resist" }, module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());

            LLVMPositionBuilderAtEnd(llbuilder, entry);

            // get params
            let inst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let dst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);

            for node in module.dae_system.unknowns.indices() {
                if let Some(contrib) = inst_data.read_lim_rhs(node, inst, &*llbuilder, reactive) {
                    inst_data.store_contrib(cx, node, inst, dst, contrib, &*llbuilder, true);
                }
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    #[allow(clippy::too_many_arguments)]
    pub fn load_spice_rhs_(
        &self,
        tran: bool,
        llbuilder: &llvm_sys::LLVMBuilder,
        inst: &'ll llvm_sys::LLVMValue,
        model: &'ll llvm_sys::LLVMValue,
        dst: &'ll llvm_sys::LLVMValue,
        prev_solve: &'ll llvm_sys::LLVMValue,
        alpha: &'ll llvm_sys::LLVMValue,
    ) {
        let dae_system = &self.module.dae_system;
        let mut node_derivatives = TiVec::from(vec![Vec::new(); dae_system.unknowns.len()]);
        for (id, entry) in dae_system.jacobian.iter_enumerated() {
            node_derivatives[entry.row].push(id)
        }

        unsafe {
            for node in dae_system.unknowns.indices() {
                let mut res = None;
                for &entry in &node_derivatives[node] {
                    let node_deriv = dae_system.jacobian[entry].col;
                    let ddx = if let Some(ddx) =
                        self.load_jacobian_entry(entry, inst, model, llbuilder, tran)
                    {
                        ddx
                    } else {
                        continue;
                    };

                    let voltage = self
                        .inst_data
                        .read_node_voltage(self.cx, node_deriv, inst, prev_solve, llbuilder);
                    let val = LLVMBuildFMul(
                        NonNull::from(llbuilder).as_ptr(),
                        NonNull::from(ddx).as_ptr(),
                        NonNull::from(voltage).as_ptr(),
                        UNNAMED,
                    );
                    let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                    llvm_sys::core::LLVMSetFastMathFlags(val, fast_math_flags);

                    res = match res {
                        Some(old) => {
                            let val =
                                LLVMBuildFAdd(NonNull::from(llbuilder).as_ptr(), old, val, UNNAMED);
                            let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                            llvm_sys::core::LLVMSetFastMathFlags(val, fast_math_flags);

                            Some(val)
                        }
                        None => Some(val),
                    }
                }

                let OsdiCompilationUnit { inst_data, cx, .. } = self;
                if !tran {
                    if let Some(contrib) = inst_data.read_residual(node, inst, llbuilder, false) {
                        let val = LLVMBuildFSub(
                            NonNull::from(llbuilder).as_ptr(),
                            res.unwrap_or_else(|| NonNull::from(cx.const_real(0.0)).as_ptr()),
                            NonNull::from(contrib).as_ptr(),
                            UNNAMED,
                        );
                        let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                        llvm_sys::core::LLVMSetFastMathFlags(val, fast_math_flags);
                        res = Some(val);
                    }
                }
                if let Some(mut res) = res {
                    if let Some(lim_rhs) = inst_data.read_lim_rhs(node, inst, llbuilder, tran) {
                        res = LLVMBuildFAdd(
                            NonNull::from(llbuilder).as_ptr(),
                            res,
                            NonNull::from(lim_rhs).as_ptr(),
                            UNNAMED,
                        );
                    }
                    if tran {
                        res = LLVMBuildFMul(
                            NonNull::from(llbuilder).as_ptr(),
                            res,
                            NonNull::from(alpha).as_ptr(),
                            UNNAMED,
                        );
                        let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                        llvm_sys::core::LLVMSetFastMathFlags(res, fast_math_flags);
                    }
                    inst_data.store_contrib(cx, node, inst, dst, &*res, llbuilder, false);
                }
            }
        }
    }

    pub fn load_spice_rhs(&self, tran: bool) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = self;
        let f64_ty = cx.ty_double();
        let ptr_ty = cx.ty_ptr();
        let mut args = vec![ptr_ty, ptr_ty, ptr_ty, ptr_ty];
        if tran {
            args.push(f64_ty);
        }
        let fun_ty = cx.ty_func(&args, cx.ty_void());
        let name = &format!("load_spice_rhs_{}_{}", if tran { "tran" } else { "dc" }, &module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());
            LLVMPositionBuilderAtEnd(llbuilder, entry);

            // get params
            let inst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let dst = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);
            let prev_solve = &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 3);
            let alpha =
                if tran { &*LLVMGetParam(NonNull::from(llfunc).as_ptr(), 4) } else { prev_solve };

            self.load_spice_rhs_(false, &*llbuilder, inst, model, dst, prev_solve, alpha);
            if tran {
                self.load_spice_rhs_(true, &*llbuilder, inst, model, dst, prev_solve, alpha);
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    pub fn load_jacobian(
        &self,
        kind: JacobianLoadType,
        with_offset: bool,
    ) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = *self;
        let fun_ty = if !with_offset {
            if kind.read_reactive() {
                cx.ty_func(&[cx.ty_ptr(), cx.ty_ptr(), cx.ty_double()], cx.ty_void())
            } else {
                cx.ty_func(&[cx.ty_ptr(), cx.ty_ptr()], cx.ty_void())
            }
        } else {
            // with_offset assumes alpha=1 for the reactive Jacobian loader
            cx.ty_func(&[cx.ty_ptr(), cx.ty_ptr(), cx.ty_size()], cx.ty_void())
        };
        let name = if with_offset {
            format!("load_jacobian_with_offset_{}_{}", kind.name(), &module.sym,)
        } else {
            format!("load_jacobian_{}_{}", kind.name(), &module.sym,)
        };
        let llfunc = cx.declare_int_c_fn(&name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());

            LLVMPositionBuilderAtEnd(llbuilder, entry);
            // Get params
            let inst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let alpha = if !with_offset && kind.read_reactive() {
                // Reactive part
                LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2)
            } else {
                // Some dummy
                inst
            };
            let offset = if with_offset {
                LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2)
            } else {
                // Some dummy
                inst
            };

            for entry in module.dae_system.jacobian.keys() {
                let mut res = None;
                if kind.read_resistive() {
                    res = self.load_jacobian_entry(entry, &*inst, &*model, &*llbuilder, false);
                }

                if kind.read_reactive() {
                    if let Some(mut val) =
                        self.load_jacobian_entry(entry, &*inst, &*model, &*llbuilder, true)
                    {
                        // with_offset assumes alpha=1
                        if !with_offset {
                            val = &*LLVMBuildFMul(
                                llbuilder,
                                NonNull::from(val).as_ptr(),
                                alpha,
                                UNNAMED,
                            );
                            let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                            llvm_sys::core::LLVMSetFastMathFlags(
                                NonNull::from(val).as_ptr(),
                                fast_math_flags,
                            );
                        }
                        val = match res {
                            Some(resist) => {
                                let val = LLVMBuildFAdd(
                                    llbuilder,
                                    NonNull::from(resist).as_ptr(),
                                    NonNull::from(val).as_ptr(),
                                    UNNAMED,
                                );
                                let fast_math_flags: c_uint = 0x1F; // This represents all flags set
                                llvm_sys::core::LLVMSetFastMathFlags(val, fast_math_flags);

                                &*val
                            }
                            None => val,
                        };
                        res = Some(val)
                    }
                }

                if let Some(res) = res {
                    self.inst_data.store_jacobian_contrib(
                        self.cx,
                        entry,
                        &*inst,
                        &*llbuilder,
                        kind.dst_reactive(),
                        with_offset,
                        &*offset,
                        res,
                    );
                }
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    // write_jacobian_array_{resist|react|tran}(void* instance, void* model, double* destination [, alpha])
    // Writes Jacobian entries into a double array of size num_jacobian_entries
    // If a particular entry is not present, nothing is loaded.
    // Array of doubles need not be zeroed before calling this function.
    pub fn write_jacobian_array(&self, kind: JacobianLoadType) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { cx, module, .. } = *self;
        let args = [cx.ty_ptr(), cx.ty_ptr(), cx.ty_ptr()];
        let fun_ty = cx.ty_func(&args, cx.ty_void());
        let name = &format!("write_jacobian_array_{}_{}", kind.name(), &module.sym,);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);

        unsafe {
            let entry = LLVMAppendBasicBlockInContext(
                NonNull::from(cx.llcx).as_ptr(),
                NonNull::from(llfunc).as_ptr(),
                UNNAMED,
            );
            let llbuilder = LLVMCreateBuilderInContext(NonNull::from(cx.llcx).as_ptr());

            LLVMPositionBuilderAtEnd(llbuilder, entry);
            // get params
            let inst = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 0);
            let model = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 1);
            let dest_array = LLVMGetParam(NonNull::from(llfunc).as_ptr(), 2);

            // Destination array type
            let len = {
                if kind.read_resistive() {
                    module.dae_system.num_resistive
                } else {
                    module.dae_system.num_reactive
                }
            };
            let dest_ty = cx.ty_array(cx.ty_double(), len as u32);

            let mut pos: u32 = 0;
            for entry in module.dae_system.jacobian.keys() {
                let res = {
                    if kind.read_resistive() {
                        // Load resistive Jacobian value from instance structure
                        self.load_jacobian_entry(entry, &*inst, &*model, &*llbuilder, false)
                    } else {
                        // Load reactive Jacobian value from instance structure
                        self.load_jacobian_entry(entry, &*inst, &*model, &*llbuilder, true)
                    }
                };

                // Do we have any result in res
                if let Some(res) = res {
                    // Store it in array pointed to by ptr
                    self.inst_data.write_jacobian_contrib(
                        self.cx,
                        pos,
                        dest_ty,
                        NonNull::new_unchecked(dest_array).as_ref(),
                        NonNull::new_unchecked(llbuilder).as_ref(),
                        res,
                    );
                    pos = pos + 1;
                }
            }

            LLVMBuildRetVoid(llbuilder);
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }
}
