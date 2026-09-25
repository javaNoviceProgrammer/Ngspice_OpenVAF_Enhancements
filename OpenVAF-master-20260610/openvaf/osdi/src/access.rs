use core::ptr::NonNull;

use llvm_sys::core::{
    LLVMAddIncoming, LLVMBuildPhi, LLVMBuildZExt,
    LLVMAddCase, LLVMAppendBasicBlockInContext, LLVMBuildAdd, LLVMBuildAnd, LLVMBuildBr,
    LLVMBuildCondBr, LLVMBuildGEP2, LLVMBuildICmp, LLVMBuildLShr, LLVMBuildLoad2, LLVMBuildOr,
    LLVMBuildRet, LLVMBuildSelect, LLVMBuildShl, LLVMBuildStore, LLVMBuildStructGEP2,
    LLVMBuildSub, LLVMBuildSwitch, LLVMCreateBuilderInContext, LLVMDisposeBuilder, LLVMGetParam,
    LLVMPositionBuilderAtEnd,
};
use llvm_sys::target::{LLVMOffsetOfElement, LLVMTargetDataRef};
use llvm_sys::LLVMIntPredicate::{LLVMIntNE, LLVMIntULT};
use mir_llvm::UNNAMED;

use crate::compilation_unit::OsdiCompilationUnit;
use crate::inst_data::{NUM_CONST_FIELDS as INST_NUM_CONST_FIELDS, PARAM_GIVEN as INST_PARAM_GIVEN};
use crate::metadata::osdi_0_4::{ACCESS_FLAG_INSTANCE, ACCESS_FLAG_SET};
use crate::model_data::{NUM_CONST_FIELDS as MODEL_NUM_CONST_FIELDS, PARAM_GIVEN as MODEL_PARAM_GIVEN};

impl<'ll> OsdiCompilationUnit<'_, '_, 'll> {
    pub fn access_function_prototype(&self) -> &'ll llvm_sys::LLVMValue {
        let cx = &self.cx;
        let void_ptr = cx.ty_ptr();
        let uint32_t = cx.ty_int();
        let fun_ty = cx.ty_func(&[void_ptr, void_ptr, uint32_t, uint32_t], void_ptr);
        let name = &format!("access_{}", &self.module.sym);
        cx.declare_ext_fn(name, fun_ty)
    }

    /// Enhancement-579: table-driven parameter access.
    ///
    /// The parameter half of this function used to be a `switch` with one case
    /// per parameter, and every case carried its own `if (write) set given bit`
    /// diamond: three basic blocks and two branches per parameter. An array
    /// parameter is one OSDI parameter PER ELEMENT, so a 10,000-entry table
    /// made a 30,000-block function on which LLVM's dominator, scheduling and
    /// register-allocation work went quadratic -- 70 s of a 72 s compile, and
    /// 375 s for an instance array. The parameter storage is a struct field
    /// per parameter at a fixed byte offset, so the lookup is now
    /// `base + OFFSETS[id]` with the offsets in a constant table, and the
    /// given bit (word `id/32`, mask `1 << id%32` -- the layout `bitfield`
    /// uses) is set with a branchless masked OR. The function is the same size
    /// for one parameter or a million; only the tables grow. The opvar half
    /// keeps its switch: opvars are few and heterogeneous (calculated slots,
    /// constants, parameters on either struct, the temperature).
    pub fn access_function(&self, target_data: LLVMTargetDataRef) -> &'ll llvm_sys::LLVMValue {
        let llfunc = self.access_function_prototype();
        let OsdiCompilationUnit { inst_data, model_data, cx, .. } = &self;
        let n_inst = inst_data.params.len() as u32;
        let n_model = model_data.params.len() as u32;

        unsafe {
            let llcx = NonNull::from(cx.llcx).as_ptr();
            let f = NonNull::from(llfunc).as_ptr();
            let entry = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let err_exit = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let inst_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let opvar_bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let llbuilder = LLVMCreateBuilderInContext(llcx);

            LLVMPositionBuilderAtEnd(llbuilder, entry);

            // get params
            let inst = LLVMGetParam(f, 0);
            let model = LLVMGetParam(f, 1);
            let param_id = LLVMGetParam(f, 2);
            let flags = LLVMGetParam(f, 3);

            // constants
            let access_flag_instance =
                NonNull::from(cx.const_unsigned_int(ACCESS_FLAG_INSTANCE)).as_ptr();
            let access_flag_set = NonNull::from(cx.const_unsigned_int(ACCESS_FLAG_SET)).as_ptr();
            let zero = NonNull::from(cx.const_unsigned_int(0)).as_ptr();
            let one = NonNull::from(cx.const_unsigned_int(1)).as_ptr();
            let five = NonNull::from(cx.const_unsigned_int(5)).as_ptr();
            let thirty_one = NonNull::from(cx.const_unsigned_int(31)).as_ptr();
            let c_n_inst = NonNull::from(cx.const_unsigned_int(n_inst)).as_ptr();
            let c_n_model = NonNull::from(cx.const_unsigned_int(n_model)).as_ptr();
            let ty_int = NonNull::from(cx.ty_int()).as_ptr();
            let ty_char = NonNull::from(cx.ty_char()).as_ptr();

            // compute boolean indicating if instance flag is set
            let flags_and_instance = LLVMBuildAnd(llbuilder, flags, access_flag_instance, UNNAMED);
            let instance_flag_set =
                LLVMBuildICmp(llbuilder, LLVMIntNE, flags_and_instance, zero, UNNAMED);

            // compute boolean indicating if write flag is set
            let flags_and_set = LLVMBuildAnd(llbuilder, flags, access_flag_set, UNNAMED);
            let write_flag_set = LLVMBuildICmp(llbuilder, LLVMIntNE, flags_and_set, zero, UNNAMED);

            LLVMBuildCondBr(llbuilder, instance_flag_set, inst_bb, model_bb);

            // the byte offset of struct fields `first..first+n` of `ty`, as a constant table
            let offsets = |ty: &'ll llvm_sys::LLVMType, first: u32, n: u32| {
                if n == 0 {
                    return None;
                }
                let vals: Vec<_> = (0..n)
                    .map(|i| {
                        let off =
                            LLVMOffsetOfElement(target_data, NonNull::from(ty).as_ptr(), first + i);
                        cx.const_unsigned_int(off as u32)
                    })
                    .collect();
                Some(cx.const_arr_ptr(cx.ty_int(), &vals))
            };
            let inst_tbl = offsets(inst_data.ty, INST_NUM_CONST_FIELDS, n_inst);
            let model_inst_tbl = offsets(model_data.ty, MODEL_NUM_CONST_FIELDS + n_model, n_inst);
            let model_tbl = offsets(model_data.ty, MODEL_NUM_CONST_FIELDS, n_model);

            // `ptr = base + tbl[idx]`; set given bit `pos` of `base`'s bitfield (struct
            // field `given_field`) when the write flag is set; return ptr
            let lookup = |bb: *mut llvm_sys::LLVMBasicBlock,
                          tbl: &'ll llvm_sys::LLVMValue,
                          base: *mut llvm_sys::LLVMValue,
                          base_ty: &'ll llvm_sys::LLVMType,
                          idx: *mut llvm_sys::LLVMValue,
                          given_field: u32,
                          pos: *mut llvm_sys::LLVMValue| {
                LLVMPositionBuilderAtEnd(llbuilder, bb);
                let mut i = [idx];
                let off_ptr = LLVMBuildGEP2(
                    llbuilder,
                    ty_int,
                    NonNull::from(tbl).as_ptr(),
                    i.as_mut_ptr(),
                    1,
                    UNNAMED,
                );
                let off = LLVMBuildLoad2(llbuilder, ty_int, off_ptr, UNNAMED);
                let mut o = [off];
                let ptr = LLVMBuildGEP2(llbuilder, ty_char, base, o.as_mut_ptr(), 1, UNNAMED);

                let arr = LLVMBuildStructGEP2(
                    llbuilder,
                    NonNull::from(base_ty).as_ptr(),
                    base,
                    given_field,
                    UNNAMED,
                );
                let word_idx = LLVMBuildLShr(llbuilder, pos, five, UNNAMED);
                let bit = LLVMBuildAnd(llbuilder, pos, thirty_one, UNNAMED);
                let mask = LLVMBuildShl(llbuilder, one, bit, UNNAMED);
                let mut w = [word_idx];
                let word_ptr = LLVMBuildGEP2(llbuilder, ty_int, arr, w.as_mut_ptr(), 1, UNNAMED);
                let word = LLVMBuildLoad2(llbuilder, ty_int, word_ptr, UNNAMED);
                let mask_if_write = LLVMBuildSelect(llbuilder, write_flag_set, mask, zero, UNNAMED);
                let new_word = LLVMBuildOr(llbuilder, word, mask_if_write, UNNAMED);
                LLVMBuildStore(llbuilder, new_word, word_ptr);
                LLVMBuildRet(llbuilder, ptr);
            };

            //
            // instance params: ids 0..n_inst, storage in the instance struct
            LLVMPositionBuilderAtEnd(llbuilder, inst_bb);
            match inst_tbl {
                Some(tbl) => {
                    let in_range = LLVMBuildICmp(llbuilder, LLVMIntULT, param_id, c_n_inst, UNNAMED);
                    let hit = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                    LLVMBuildCondBr(llbuilder, in_range, hit, opvar_bb);
                    lookup(hit, tbl, inst, inst_data.ty, param_id, INST_PARAM_GIVEN, param_id);
                }
                None => {
                    LLVMBuildBr(llbuilder, opvar_bb);
                }
            }

            //
            // model side: the model-struct copies of the instance params (ids
            // 0..n_inst, given bits after the model params) and then the model
            // params (ids n_inst..n_inst+n_model)
            LLVMPositionBuilderAtEnd(llbuilder, model_bb);
            let model_params_bb = match model_inst_tbl {
                Some(tbl) => {
                    let is_inst = LLVMBuildICmp(llbuilder, LLVMIntULT, param_id, c_n_inst, UNNAMED);
                    let hit = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                    let next = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                    LLVMBuildCondBr(llbuilder, is_inst, hit, next);
                    LLVMPositionBuilderAtEnd(llbuilder, hit);
                    let pos = LLVMBuildAdd(llbuilder, param_id, c_n_model, UNNAMED);
                    lookup(hit, tbl, model, model_data.ty, param_id, MODEL_PARAM_GIVEN, pos);
                    next
                }
                None => model_bb,
            };
            LLVMPositionBuilderAtEnd(llbuilder, model_params_bb);
            match model_tbl {
                Some(tbl) => {
                    let idx = LLVMBuildSub(llbuilder, param_id, c_n_inst, UNNAMED);
                    let in_range = LLVMBuildICmp(llbuilder, LLVMIntULT, idx, c_n_model, UNNAMED);
                    let hit = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                    LLVMBuildCondBr(llbuilder, in_range, hit, opvar_bb);
                    lookup(hit, tbl, model, model_data.ty, idx, MODEL_PARAM_GIVEN, idx);
                }
                None => {
                    LLVMBuildBr(llbuilder, opvar_bb);
                }
            }

            let null_ptr = cx.const_null_ptr();

            LLVMPositionBuilderAtEnd(llbuilder, opvar_bb);
            let switch_opvar =
                LLVMBuildSwitch(llbuilder, param_id, err_exit, inst_data.opvars.len() as u32);

            for opvar_idx in 0..inst_data.opvars.len() {
                let OsdiCompilationUnit { inst_data, model_data, cx, .. } = &self;
                let bb = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
                LLVMPositionBuilderAtEnd(llbuilder, bb);
                let case = cx.const_unsigned_int(
                    (model_data.params.len() + inst_data.params.len() + opvar_idx) as u32,
                );

                LLVMAddCase(switch_opvar, NonNull::from(case).as_ptr(), bb);

                let (ptr, _) = self.nth_opvar_ptr(opvar_idx as u32, &*inst, &*model, &*llbuilder);
                LLVMBuildRet(llbuilder, NonNull::from(ptr).as_ptr());
            }

            LLVMPositionBuilderAtEnd(llbuilder, err_exit);
            LLVMBuildRet(llbuilder, NonNull::from(null_ptr).as_ptr());

            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    /// Enhancement-713 (robustness campaign F7 of 2026-09-23): `given_flag_instance`
    /// and `given_flag_model` were a `switch` with one case per parameter, each
    /// case reading its own bit -- 20 000 cases for a 20 000-element array
    /// parameter, and LLVM's switch lowering took 5.9 s of the descriptor module.
    /// The given bits are a flat bitfield indexed by parameter position (E-555
    /// made `param_given` read it arithmetically), so both are one bounds check,
    /// one shift and one load now, whatever the parameter count.
    pub fn given_flag_instance(&self) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { inst_data, cx, .. } = &self;
        let fun_ty = cx.ty_func(&[cx.ty_ptr(), cx.ty_int()], cx.ty_int());
        let name = &format!("given_flag_instance_{}", &self.module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);
        let n_inst = inst_data.params.len() as u32;

        unsafe {
            let llcx = NonNull::from(cx.llcx).as_ptr();
            let f = NonNull::from(llfunc).as_ptr();
            let entry = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let found = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let not_found = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let llbuilder = LLVMCreateBuilderInContext(llcx);

            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let ptr = LLVMGetParam(f, 0);
            let param_id = LLVMGetParam(f, 1);
            let in_range = LLVMBuildICmp(
                llbuilder,
                LLVMIntULT,
                param_id,
                NonNull::from(cx.const_unsigned_int(n_inst)).as_ptr(),
                UNNAMED,
            );
            LLVMBuildCondBr(llbuilder, in_range, found, not_found);

            LLVMPositionBuilderAtEnd(llbuilder, found);
            let arr = LLVMBuildStructGEP2(
                llbuilder,
                NonNull::from(inst_data.ty).as_ptr(),
                ptr,
                INST_PARAM_GIVEN,
                UNNAMED,
            );
            let bit = given_bit(cx, llbuilder, arr, param_id);
            LLVMBuildRet(llbuilder, bit);

            LLVMPositionBuilderAtEnd(llbuilder, not_found);
            LLVMBuildRet(llbuilder, NonNull::from(cx.const_int(0)).as_ptr());
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }

    /// See `given_flag_instance`. The model struct's bitfield holds the model
    /// parameters at their own positions and the instance parameters' copies
    /// after them, as `is_nth_inst_param_given` reads them.
    pub fn given_flag_model(&self) -> &'ll llvm_sys::LLVMValue {
        let OsdiCompilationUnit { inst_data, model_data, cx, .. } = &self;
        let fun_ty = cx.ty_func(&[cx.ty_ptr(), cx.ty_int()], cx.ty_int());
        let name = &format!("given_flag_model_{}", self.module.sym);
        let llfunc = cx.declare_int_c_fn(name, fun_ty);
        let n_inst = inst_data.params.len() as u32;
        let n_model = model_data.params.len() as u32;

        unsafe {
            let llcx = NonNull::from(cx.llcx).as_ptr();
            let f = NonNull::from(llfunc).as_ptr();
            let entry = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let inst_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_chk = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let model_side = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let common = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let not_found = LLVMAppendBasicBlockInContext(llcx, f, UNNAMED);
            let llbuilder = LLVMCreateBuilderInContext(llcx);
            let ty_int = NonNull::from(cx.ty_int()).as_ptr();
            let c_n_inst = NonNull::from(cx.const_unsigned_int(n_inst)).as_ptr();
            let c_n_model = NonNull::from(cx.const_unsigned_int(n_model)).as_ptr();

            LLVMPositionBuilderAtEnd(llbuilder, entry);
            let ptr = LLVMGetParam(f, 0);
            let param_id = LLVMGetParam(f, 1);
            let is_inst = LLVMBuildICmp(llbuilder, LLVMIntULT, param_id, c_n_inst, UNNAMED);
            LLVMBuildCondBr(llbuilder, is_inst, inst_side, model_chk);

            // an instance parameter's copy sits after the model parameters
            LLVMPositionBuilderAtEnd(llbuilder, inst_side);
            let pos_inst = LLVMBuildAdd(llbuilder, param_id, c_n_model, UNNAMED);
            LLVMBuildBr(llbuilder, common);

            LLVMPositionBuilderAtEnd(llbuilder, model_chk);
            let pos_model = LLVMBuildSub(llbuilder, param_id, c_n_inst, UNNAMED);
            let in_range = LLVMBuildICmp(llbuilder, LLVMIntULT, pos_model, c_n_model, UNNAMED);
            LLVMBuildCondBr(llbuilder, in_range, model_side, not_found);

            LLVMPositionBuilderAtEnd(llbuilder, model_side);
            LLVMBuildBr(llbuilder, common);

            LLVMPositionBuilderAtEnd(llbuilder, common);
            let pos = LLVMBuildPhi(llbuilder, ty_int, UNNAMED);
            let mut pos_vals = [pos_inst, pos_model];
            let mut pos_bbs = [inst_side, model_side];
            LLVMAddIncoming(pos, pos_vals.as_mut_ptr(), pos_bbs.as_mut_ptr(), 2);
            let arr = LLVMBuildStructGEP2(
                llbuilder,
                NonNull::from(model_data.ty).as_ptr(),
                ptr,
                MODEL_PARAM_GIVEN,
                UNNAMED,
            );
            let bit = given_bit(cx, llbuilder, arr, pos);
            LLVMBuildRet(llbuilder, bit);

            LLVMPositionBuilderAtEnd(llbuilder, not_found);
            LLVMBuildRet(llbuilder, NonNull::from(cx.const_int(0)).as_ptr());
            LLVMDisposeBuilder(llbuilder);
        }

        llfunc
    }
}

/// Enhancement-713: bit `pos` of the given bitfield at `arr` (word `pos / 32`,
/// bit `pos % 32`, the layout `bitfield` writes), as a 0/1 `i32`.
unsafe fn given_bit(
    cx: &mir_llvm::CodegenCx<'_, '_>,
    llbuilder: llvm_sys::prelude::LLVMBuilderRef,
    arr: llvm_sys::prelude::LLVMValueRef,
    pos: llvm_sys::prelude::LLVMValueRef,
) -> llvm_sys::prelude::LLVMValueRef {
    let ty_int = NonNull::from(cx.ty_int()).as_ptr();
    let word_idx =
        LLVMBuildLShr(llbuilder, pos, NonNull::from(cx.const_unsigned_int(5)).as_ptr(), UNNAMED);
    let bit = LLVMBuildAnd(llbuilder, pos, NonNull::from(cx.const_unsigned_int(31)).as_ptr(), UNNAMED);
    let mask = LLVMBuildShl(llbuilder, NonNull::from(cx.const_unsigned_int(1)).as_ptr(), bit, UNNAMED);
    let mut w = [word_idx];
    let word_ptr = LLVMBuildGEP2(llbuilder, ty_int, arr, w.as_mut_ptr(), 1, UNNAMED);
    let word = LLVMBuildLoad2(llbuilder, ty_int, word_ptr, UNNAMED);
    let is_set = LLVMBuildAnd(llbuilder, word, mask, UNNAMED);
    let bit_set = LLVMBuildICmp(
        llbuilder,
        LLVMIntNE,
        is_set,
        NonNull::from(cx.const_unsigned_int(0)).as_ptr(),
        UNNAMED,
    );
    LLVMBuildZExt(llbuilder, bit_set, ty_int, UNNAMED)

}
