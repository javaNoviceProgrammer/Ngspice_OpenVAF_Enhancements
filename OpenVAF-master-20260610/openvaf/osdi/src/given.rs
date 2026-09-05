//! Enhancement-555: the per-module `param_given_<sym>(inst, model, id, op)`
//! entry point, exported beside the descriptors as `OSDI_PARAM_GIVEN_FNS`.
//!
//! The descriptor's `access()` sets a parameter's given flag on every write,
//! which is right for a deck's `alter` and wrong for a machine write that must
//! leave givenness as it found it: an `.option osdimc` draw, or the restore
//! after a `.dc` / `sweep` of the parameter. A model that picks a default with
//! `$param_given` (BSIM4's `toxp`, derived from `toxe` when not given) ran a
//! different model from the second trial on, and after any sweep. This entry
//! point lets the simulator query the flag before such a write and put it back
//! after: `op` 0 reads it (0/1), 1 sets it, 2 clears it; an unknown id returns
//! 0xFFFFFFFF. For an instance parameter with `inst == NULL` the card-level
//! flag in the model is meant. The descriptor ABI is untouched -- an object
//! without the symbol simply has no such entry point.

use core::ptr::NonNull;

use llvm_sys::core::{
    LLVMAddCase, LLVMAppendBasicBlockInContext, LLVMBuildCondBr, LLVMBuildICmp, LLVMBuildRet,
    LLVMBuildSwitch, LLVMBuildZExt, LLVMCreateBuilderInContext, LLVMDisposeBuilder, LLVMGetParam,
    LLVMPositionBuilderAtEnd,
};
use llvm_sys::LLVMIntPredicate::LLVMIntEQ;
use mir_llvm::UNNAMED;

use crate::compilation_unit::OsdiCompilationUnit;

impl<'ll> OsdiCompilationUnit<'_, '_, 'll> {
    pub fn param_given_function_prototype(&self) -> &'ll llvm_sys::LLVMValue {
        let cx = &self.cx;
        let void_ptr = cx.ty_ptr();
        let uint32_t = cx.ty_int();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, uint32_t, uint32_t], uint32_t);
        let name = &format!("param_given_{}", &self.module.sym);
        cx.declare_ext_fn(name, fun_ty)
    }

    pub fn param_given_function(&self) -> &'ll llvm_sys::LLVMValue {
        let llfunc = self.param_given_function_prototype();
        let OsdiCompilationUnit { inst_data, model_data, cx, .. } = &self;

        unsafe {
            let llcx = NonNull::from(cx.llcx).as_ptr();
            let f = NonNull::from(llfunc).as_ptr();
            let entry = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let unknown = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let llbuilder = LLVMCreateBuilderInContext(llcx);

            LLVMPositionBuilderAtEnd(llbuilder, unknown);
            LLVMBuildRet(llbuilder, NonNull::from(cx.const_unsigned_int(u32::MAX)).as_ptr());

            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let inst = LLVMGetParam(f, 0);
            let model = LLVMGetParam(f, 1);
            let param_id = LLVMGetParam(f, 2);
            let op = LLVMGetParam(f, 3);
            let inst_is_null = LLVMBuildICmp(
                llbuilder,
                LLVMIntEQ,
                inst,
                NonNull::from(cx.const_null_ptr()).as_ptr(),
                UNNAMED,
            );

            let n_inst = inst_data.params.len();
            let n_model = model_data.params.len();
            let switch = LLVMBuildSwitch(llbuilder, param_id, unknown, (n_inst + n_model) as u32);

            // Where a flag lives: 0 = the instance's own bit, 1 = the model's
            // bit for an instance parameter, 2 = the model's bit for a model
            // parameter.
            let emit_ops = |pos: u32, where_: u32, bb: *mut llvm_sys::LLVMBasicBlock| {
                let get_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                let set_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                let clr_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                LLVMPositionBuilderAtEnd(llbuilder, bb);
                let sw = LLVMBuildSwitch(llbuilder, op, unknown, 3);
                LLVMAddCase(sw, NonNull::from(cx.const_unsigned_int(0)).as_ptr(), get_bb);
                LLVMAddCase(sw, NonNull::from(cx.const_unsigned_int(1)).as_ptr(), set_bb);
                LLVMAddCase(sw, NonNull::from(cx.const_unsigned_int(2)).as_ptr(), clr_bb);

                LLVMPositionBuilderAtEnd(llbuilder, get_bb);
                let bit = match where_ {
                    0 => inst_data.is_nth_param_given(cx, pos, &*inst, &*llbuilder),
                    1 => model_data.is_nth_inst_param_given(cx, pos, &*model, &*llbuilder),
                    _ => model_data.is_nth_param_given(cx, pos, &*model, &*llbuilder),
                };
                let val = LLVMBuildZExt(
                    llbuilder,
                    NonNull::from(bit).as_ptr(),
                    NonNull::from(cx.ty_int()).as_ptr(),
                    UNNAMED,
                );
                LLVMBuildRet(llbuilder, val);

                LLVMPositionBuilderAtEnd(llbuilder, set_bb);
                match where_ {
                    0 => inst_data.set_nth_param_given(cx, pos, &*inst, &*llbuilder),
                    1 => model_data.set_nth_inst_param_given(cx, pos, &*model, &*llbuilder),
                    _ => model_data.set_nth_param_given(cx, pos, &*model, &*llbuilder),
                }
                LLVMBuildRet(llbuilder, NonNull::from(cx.const_unsigned_int(1)).as_ptr());

                LLVMPositionBuilderAtEnd(llbuilder, clr_bb);
                match where_ {
                    0 => inst_data.clear_nth_param_given(cx, pos, &*inst, &*llbuilder),
                    1 => model_data.clear_nth_inst_param_given(cx, pos, &*model, &*llbuilder),
                    _ => model_data.clear_nth_param_given(cx, pos, &*model, &*llbuilder),
                }
                LLVMBuildRet(llbuilder, NonNull::from(cx.const_unsigned_int(0)).as_ptr());
            };

            for idx in 0..n_inst {
                let bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                LLVMAddCase(switch, NonNull::from(cx.const_unsigned_int(idx as u32)).as_ptr(), bb);
                let model_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                let inst_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                LLVMPositionBuilderAtEnd(llbuilder, bb);
                LLVMBuildCondBr(llbuilder, inst_is_null, model_side, inst_side);
                emit_ops(idx as u32, 0, inst_side);
                emit_ops(idx as u32, 1, model_side);
            }
            for idx in 0..n_model {
                let bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                LLVMAddCase(
                    switch,
                    NonNull::from(cx.const_unsigned_int((n_inst + idx) as u32)).as_ptr(),
                    bb,
                );
                emit_ops(idx as u32, 2, bb);
            }

            LLVMDisposeBuilder(llbuilder);
        }
        llfunc
    }
}
