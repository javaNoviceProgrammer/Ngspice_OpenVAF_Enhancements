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
    LLVMAddCase, LLVMAddIncoming, LLVMAppendBasicBlockInContext, LLVMBuildAdd, LLVMBuildAnd,
    LLVMBuildBr, LLVMBuildCondBr, LLVMBuildGEP2, LLVMBuildICmp, LLVMBuildLShr, LLVMBuildLoad2,
    LLVMBuildNot, LLVMBuildOr, LLVMBuildPhi, LLVMBuildRet, LLVMBuildShl, LLVMBuildStore,
    LLVMBuildStructGEP2, LLVMBuildSub, LLVMBuildSwitch, LLVMBuildZExt, LLVMCreateBuilderInContext,
    LLVMDisposeBuilder, LLVMGetParam, LLVMPositionBuilderAtEnd,
};
use llvm_sys::LLVMIntPredicate::{LLVMIntEQ, LLVMIntNE, LLVMIntULT};
use mir_llvm::UNNAMED;

use crate::compilation_unit::OsdiCompilationUnit;
use crate::inst_data::PARAM_GIVEN as INST_PARAM_GIVEN;
use crate::model_data::PARAM_GIVEN as MODEL_PARAM_GIVEN;

impl<'ll> OsdiCompilationUnit<'_, '_, 'll> {
    pub fn param_given_function_prototype(&self) -> &'ll llvm_sys::LLVMValue {
        let cx = &self.cx;
        let void_ptr = cx.ty_ptr();
        let uint32_t = cx.ty_int();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, uint32_t, uint32_t], uint32_t);
        let name = &format!("param_given_{}", &self.module.sym);
        cx.declare_ext_fn(name, fun_ty)
    }

    /// Enhancement-579: table-free given-flag query.
    ///
    /// This was a `switch` with one case per parameter, each case a second
    /// `switch` over the operation with three leaf blocks -- four blocks and
    /// eighteen IR lines per parameter, 66,000 lines for a 2,000-entry array
    /// parameter. The given bits are a flat bitfield indexed by parameter
    /// position (word `pos/32`, mask `1 << pos%32`, the layout `bitfield`
    /// uses), so the word can be addressed from the id arithmetically; only
    /// WHICH bitfield (instance struct, or the model struct's copies of the
    /// instance parameters, or its own parameters) depends on the id range and
    /// on whether an instance pointer was passed. The function is now ten
    /// blocks for any number of parameters.
    pub fn param_given_function(&self) -> &'ll llvm_sys::LLVMValue {
        let llfunc = self.param_given_function_prototype();
        let OsdiCompilationUnit { inst_data, model_data, cx, .. } = &self;
        let n_inst = inst_data.params.len() as u32;
        let n_model = model_data.params.len() as u32;

        unsafe {
            let llcx = NonNull::from(cx.llcx).as_ptr();
            let f = NonNull::from(llfunc).as_ptr();
            let entry = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let unknown = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let inst_id = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let inst_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_chk = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_param = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let common = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let get_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let set_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let clr_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let llbuilder = LLVMCreateBuilderInContext(llcx);

            let ty_int = NonNull::from(cx.ty_int()).as_ptr();
            let ty_ptr = NonNull::from(cx.ty_ptr()).as_ptr();
            let zero = NonNull::from(cx.const_unsigned_int(0)).as_ptr();
            let one = NonNull::from(cx.const_unsigned_int(1)).as_ptr();
            let five = NonNull::from(cx.const_unsigned_int(5)).as_ptr();
            let thirty_one = NonNull::from(cx.const_unsigned_int(31)).as_ptr();
            let c_n_inst = NonNull::from(cx.const_unsigned_int(n_inst)).as_ptr();
            let c_n_model = NonNull::from(cx.const_unsigned_int(n_model)).as_ptr();

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
            let is_inst_id = LLVMBuildICmp(llbuilder, LLVMIntULT, param_id, c_n_inst, UNNAMED);
            LLVMBuildCondBr(llbuilder, is_inst_id, inst_id, model_chk);

            // an instance parameter: its bit lives in the instance struct when one
            // was passed, else in the model struct after the model parameters
            LLVMPositionBuilderAtEnd(llbuilder, inst_id);
            LLVMBuildCondBr(llbuilder, inst_is_null, model_side, inst_side);

            LLVMPositionBuilderAtEnd(llbuilder, inst_side);
            let arr_i = LLVMBuildStructGEP2(
                llbuilder,
                NonNull::from(inst_data.ty).as_ptr(),
                inst,
                INST_PARAM_GIVEN,
                UNNAMED,
            );
            LLVMBuildBr(llbuilder, common);

            LLVMPositionBuilderAtEnd(llbuilder, model_side);
            let arr_m1 = LLVMBuildStructGEP2(
                llbuilder,
                NonNull::from(model_data.ty).as_ptr(),
                model,
                MODEL_PARAM_GIVEN,
                UNNAMED,
            );
            let pos_m1 = LLVMBuildAdd(llbuilder, param_id, c_n_model, UNNAMED);
            LLVMBuildBr(llbuilder, common);

            // a model parameter: ids n_inst..n_inst+n_model
            LLVMPositionBuilderAtEnd(llbuilder, model_chk);
            let idx = LLVMBuildSub(llbuilder, param_id, c_n_inst, UNNAMED);
            let in_range = LLVMBuildICmp(llbuilder, LLVMIntULT, idx, c_n_model, UNNAMED);
            LLVMBuildCondBr(llbuilder, in_range, model_param, unknown);

            LLVMPositionBuilderAtEnd(llbuilder, model_param);
            let arr_m2 = LLVMBuildStructGEP2(
                llbuilder,
                NonNull::from(model_data.ty).as_ptr(),
                model,
                MODEL_PARAM_GIVEN,
                UNNAMED,
            );
            LLVMBuildBr(llbuilder, common);

            LLVMPositionBuilderAtEnd(llbuilder, common);
            let arr = LLVMBuildPhi(llbuilder, ty_ptr, UNNAMED);
            let mut arr_vals = [arr_i, arr_m1, arr_m2];
            let mut arr_bbs = [inst_side, model_side, model_param];
            LLVMAddIncoming(arr, arr_vals.as_mut_ptr(), arr_bbs.as_mut_ptr(), 3);
            let pos = LLVMBuildPhi(llbuilder, ty_int, UNNAMED);
            let mut pos_vals = [param_id, pos_m1, idx];
            let mut pos_bbs = [inst_side, model_side, model_param];
            LLVMAddIncoming(pos, pos_vals.as_mut_ptr(), pos_bbs.as_mut_ptr(), 3);

            let word_idx = LLVMBuildLShr(llbuilder, pos, five, UNNAMED);
            let bit = LLVMBuildAnd(llbuilder, pos, thirty_one, UNNAMED);
            let mask = LLVMBuildShl(llbuilder, one, bit, UNNAMED);
            let mut w = [word_idx];
            let word_ptr = LLVMBuildGEP2(llbuilder, ty_int, arr, w.as_mut_ptr(), 1, UNNAMED);
            let word = LLVMBuildLoad2(llbuilder, ty_int, word_ptr, UNNAMED);
            let sw = LLVMBuildSwitch(llbuilder, op, unknown, 3);
            LLVMAddCase(sw, zero, get_bb);
            LLVMAddCase(sw, one, set_bb);
            LLVMAddCase(sw, NonNull::from(cx.const_unsigned_int(2)).as_ptr(), clr_bb);

            LLVMPositionBuilderAtEnd(llbuilder, get_bb);
            let is_set = LLVMBuildAnd(llbuilder, word, mask, UNNAMED);
            let bit_set = LLVMBuildICmp(llbuilder, LLVMIntNE, is_set, zero, UNNAMED);
            let val = LLVMBuildZExt(llbuilder, bit_set, ty_int, UNNAMED);
            LLVMBuildRet(llbuilder, val);

            LLVMPositionBuilderAtEnd(llbuilder, set_bb);
            let with_bit = LLVMBuildOr(llbuilder, word, mask, UNNAMED);
            LLVMBuildStore(llbuilder, with_bit, word_ptr);
            LLVMBuildRet(llbuilder, one);

            LLVMPositionBuilderAtEnd(llbuilder, clr_bb);
            let not_mask = LLVMBuildNot(llbuilder, mask, UNNAMED);
            let without_bit = LLVMBuildAnd(llbuilder, word, not_mask, UNNAMED);
            LLVMBuildStore(llbuilder, without_bit, word_ptr);
            LLVMBuildRet(llbuilder, zero);

            LLVMDisposeBuilder(llbuilder);
        }
        llfunc
    }
}
