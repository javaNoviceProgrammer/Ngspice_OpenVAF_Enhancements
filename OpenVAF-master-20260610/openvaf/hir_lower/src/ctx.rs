use ahash::AHashSet;
use hir::{BranchWrite, CompilationDB, Function, Name, Node, Type, Variable};
use mir::builder::{InsertBuilder, InstBuilder};
use mir::{
    Block, DataFlowGraph, FuncRef, Inst, Opcode, Param, SourceLoc, Value, FALSE, F_ZERO, INFINITY,
    TRUE,
};
use mir_build::{FuncInstBuilder, FunctionBuilder, Place};
use typed_indexmap::TiSet;

use crate::fmt::{DisplayKind, FmtArg};
use crate::{
    CallBackKind, HirInterner, ImplicitEquation, ImplicitEquationKind, LimitState, ParamKind,
    PlaceKind, PrintDst, RetFlag,
};

pub struct LoweringCtx<'a, 'c> {
    pub db: &'a CompilationDB,
    pub func: FunctionBuilder<'c>,
    pub no_equations: bool,
    pub intern: &'a mut HirInterner,
    pub places: TiSet<Place, PlaceKind>,
    tagged_vars: AHashSet<Variable>,
    /// Round-4 audit: the branches whose `IsVoltageSrc` classification is
    /// visible ON THE PATH BEING LOWERED. `places` answers "does this location
    /// exist at all", which is monotonic -- once any arm classifies a branch
    /// it looks classified everywhere, including in its own SIBLING arm. That
    /// is the wrong question for the noise-only rule in `contribute_value_`
    /// (see there): a noise-only contribution must not overwrite a
    /// classification that reaches it, but in an arm where none reaches it,
    /// its own kind is the only information there is. `make_cond` saves and
    /// restores this set per arm and unions the two afterwards, which is
    /// exactly "a definition in one arm reaches code after the merge, but not
    /// its sibling".
    classified_branches: AHashSet<BranchWrite>,
    pub inside_lim: bool,
    /// We create a dedicated callback for each noise source
    /// by giving each callback a unique index. Kind of ineffcient
    /// but necessary to avoid accidental correlation/opimization.
    /// For example white_noise(x) - white_noise(x) is not zero.
    pub num_noise_sources: u32,
    /// Stack of enclosing *named* blocks and the MIR block that each one's
    /// execution jumps to when it finishes. `disable <name>;` looks a name up
    /// here and branches to the matching exit (Verilog-AMS early-exit / loop
    /// `break`). Pushed when a named `begin : name ... end` is entered, popped
    /// when it is left.
    pub disable_scopes: Vec<(Name, Block)>,
    /// Stack of enclosing RUNTIME loops for the VAMS-2023 jump statements
    /// (LRM 5.11): `(continue_target, break_target)` -- `continue` jumps to
    /// the condition re-test (while/do-while), the increment (for), or the
    /// counter decrement (repeat); `break` jumps to the loop's exit block.
    pub loop_scopes: Vec<(Block, Block)>,
    /// Stack of inlined analog-function bodies for `return [expr];`: the
    /// function (whose `FunctionReturn` place the value is written to) and
    /// the exit block the jump targets. Innermost last, matching the
    /// recursive inlining in `lower_user_fun_impl`.
    pub return_scopes: Vec<(Function, Block)>,
    /// True while lowering the body of an event-controlled statement
    /// (`@(initial_step) ...`). Display statements lowered here are tagged
    /// LOG_FLAG_IMMEDIATE: they fire on the event's own Newton iteration, so
    /// the simulator prints them right away instead of deferring them to the
    /// accepted iteration (LRM 9.4.6 deferral, audit 2026-08-31).
    pub in_event_ctx: bool,
    /// True while lowering an `analog initial` block (LRM 5.2.1). Two rules
    /// hang off it, and both were open before the 2026-09-02 round-3 audit:
    ///
    /// * The block is gated on `IsInitialStep` inside the eval function, so
    ///   its statements run on the instance's FIRST Newton iteration of an
    ///   analysis -- which is not the accepted one. Untagged, every
    ///   `$strobe`/`$display`/`$write`/`$monitor` and every file write it
    ///   makes was deferred into that iteration's buffer and then dropped as
    ///   superseded: an `analog initial` block's entire output vanished, in
    ///   every analysis, with the file it opened left at zero bytes. This is
    ///   the same hazard `in_event_ctx` exists for, on the neighbouring
    ///   construct, so displays lowered here are tagged LOG_FLAG_IMMEDIATE
    ///   too.
    /// * LRM 9.7.3: "If `$error` is executed within an `analog initial`
    ///   block, then the message is issued and the initialization continues.
    ///   However, the simulation shall not proceed past initialization."
    ///   `$error` therefore raises [`RetFlag::InitErr`] here and nowhere else.
    pub in_analog_initial: bool,
}

impl<'a, 'c> LoweringCtx<'a, 'c> {
    pub fn new(
        db: &'a CompilationDB,
        func: FunctionBuilder<'c>,
        no_equations: bool,
        intern: &'a mut HirInterner,
    ) -> Self {
        Self {
            db,
            func,
            no_equations,
            places: TiSet::default(),
            tagged_vars: AHashSet::default(),
            classified_branches: AHashSet::default(),
            inside_lim: false,
            intern,
            num_noise_sources: 0,
            disable_scopes: Vec::new(),
            loop_scopes: Vec::new(),
            return_scopes: Vec::new(),
            in_event_ctx: false,
            in_analog_initial: false,
        }
    }

    pub fn with_tagged_vars(mut self, vars: AHashSet<Variable>) -> Self {
        self.tagged_vars = vars;
        self
    }

    /// This function should be used for reading variables to correctly
    /// handle value tagging
    pub fn read_variable(&mut self, var: Variable) -> Value {
        let place = self.dec_place(PlaceKind::Var(var));
        let mut val = self.func.use_var(place);
        if self.tagged_vars.contains(&var) {
            val = self.func.ins().optbarrier(val);
            self.intern.tagged_reads.insert(val, var);
        }
        val
    }

    /// Defclares a mutable memory locations (places) which will
    /// be translated to SSA (phi stmts where necessary) automatically.
    /// If the requested memory location already exists then that place
    /// will be returned. Otherwise a new memory slot is created an
    /// the place is initialized in the function entry (if necessary)
    pub fn dec_place(&mut self, kind: PlaceKind) -> Place {
        let (place, inserted) = self.places.ensure(kind);
        if inserted {
            let init = match kind {
                // always initialized
                PlaceKind::FunctionReturn { .. }
                | PlaceKind::FunctionArg { .. }
                | PlaceKind::Param(_)
                | PlaceKind::ParamMin(_)
                | PlaceKind::ParamMax(_) => return place,

                PlaceKind::Var(var) => self.use_param(ParamKind::HiddenState(var)),
                PlaceKind::ImplicitResidual { .. } | PlaceKind::Contribute { .. } => F_ZERO,
                PlaceKind::CollapseImplicitEquation(_) => TRUE,
                PlaceKind::IsVoltageSrc(_) => FALSE,
                PlaceKind::BoundStep => INFINITY,
                PlaceKind::AbsDelayTime(_) | PlaceKind::LastCrossingDirection(_) => F_ZERO,
                PlaceKind::EventState(i) => self.use_param(ParamKind::EventState(i)),
            };
            let entry = self.func.func.layout.entry_block().unwrap();
            self.func.def_var_at(place, init, entry);
        }
        place
    }

    pub fn def_place(&mut self, kind: PlaceKind, val: Value) {
        let place = self.dec_place(kind);
        self.func.def_var(place, val)
    }

    pub fn use_place(&mut self, kind: PlaceKind) -> Value {
        let place = self.dec_place(kind);
        self.func.use_var(place)
    }

    /// Determines if a mutable memory location (places) exists.
    /// If that location exists the corresponding place is returned
    /// otherwise returns `None`
    pub fn get_place(&self, kind: PlaceKind) -> Option<Place> {
        self.places.index(&kind)
    }

    /// Whether a branch-kind classification reaches the point being lowered
    /// (round-4 audit -- see `classified_branches`).
    pub fn classification_reaches(&self, write: BranchWrite) -> bool {
        self.classified_branches.contains(&write)
    }

    /// Records that this branch's kind is now classified on the current path.
    pub fn record_classification(&mut self, write: BranchWrite) {
        self.classified_branches.insert(write);
    }

    /// Defines a new parameter (if not already present) and returns its value
    pub fn use_param(&mut self, kind: ParamKind) -> Value {
        let len = self.intern.params.len();
        let entry = self.intern.params.raw.entry(kind);
        *entry.or_insert_with(|| self.func.func.dfg.make_param(len.into()))
    }

    pub fn def_param(&mut self, kind: ParamKind, val: Value) {
        self.intern.params.insert(kind, val);
    }

    pub fn def_output(&mut self, kind: PlaceKind, val: Value) {
        self.intern.outputs.insert(kind, val.into());
    }

    pub fn get_param(&mut self, kind: ParamKind) -> Option<Value> {
        self.intern.params.get(&kind).copied()
    }

    /// Enhancement-327: the [`ParamKind`] a [`Param`] was interned for. Lets `ddx`
    /// lowering INSPECT a user-supplied unknown (is it a plain node potential?)
    /// rather than assert its shape and panic.
    pub fn param_kind(&self, param: Param) -> &ParamKind {
        self.intern.params.get_index(param).unwrap().0
    }

    pub fn call1(&mut self, kind: CallBackKind, args: &[Value]) -> Value {
        let inst = self.call(kind, args);
        self.dfg().first_result(inst)
    }

    pub fn call(&mut self, kind: CallBackKind, args: &[Value]) -> Inst {
        let tracked = !self.no_equations && kind.tracked();
        let func = self.dec_callback(kind);
        let res = self.func.ins().call(func, args);
        if tracked {
            self.intern.callback_uses[func].push(res)
        }
        res
    }

    /// Enhancement-506: emits a `$fatal`-equivalent from lowering itself, for a
    /// RUN-TIME value that the compile-time guards cannot see.
    ///
    /// Every value guard in `hir_ty` judges a CONSTANT: it sees a literal or a
    /// localparam and nothing else. The ordinary case is a model whose
    /// `parameter real T = 1n` is overridden from the deck, which the compiler
    /// deliberately does not refuse (a default is the author's business) and which
    /// nothing checked afterwards -- so a value the compiler calls an outright
    /// error was accepted in silence when it arrived by the ordinary route.
    ///
    /// Enhancement-504 closed that gap wherever the domain has a natural
    /// projection (a negative rise time becomes zero, an unusable noise power
    /// becomes zero). Where it has none -- a sampling period that must be
    /// positive, a denominator whose leading coefficient must be non-zero, an
    /// event direction that must be one of three values -- there is nothing
    /// honest to substitute, so the run time says exactly what the compiler would
    /// have said and aborts, instead of continuing into a wrong answer.
    ///
    /// Shape follows `$fatal` (Enhancement-324): print, then RAISE A FLAG and
    /// CONTINUE. The OSDI eval function has a mandatory epilogue that the ABI
    /// requires to run, and every ret-flag is only a flag the simulator inspects
    /// after eval returns -- none of them can longjmp out of the middle of an
    /// evaluation, so terminating the MIR function early here would strand the
    /// epilogue in a block with no incoming edges.
    /// `val`, when given, is appended to the message as `%g` -- the run time can
    /// name the offending NUMBER, which is the half the compile-time diagnostic
    /// gets for free and the half a user actually needs to find the deck line.
    pub fn runtime_fatal(&mut self, msg: &str, val: Option<Value>) {
        let (fmt_lit, arg_tys): (String, Vec<FmtArg>) = match val {
            Some(_) => (format!("{msg} %g\n"), vec![Type::Real.into()]),
            None => (format!("{msg}\n"), Vec::new()),
        };
        let fmt = self.sconst(&fmt_lit);
        let mut call_args = vec![fmt];
        call_args.extend(val);
        let cb = CallBackKind::Print {
            kind: DisplayKind::Fatal,
            arg_tys: arg_tys.into_boxed_slice(),
            dst: PrintDst::Console,
            immediate: true,
            in_initial: self.in_analog_initial,
        };
        self.call(cb, &call_args);
        self.call(CallBackKind::SetRetFlag(RetFlag::Abort), &[]);
    }

    pub fn dec_callback(&mut self, kind: CallBackKind) -> FuncRef {
        let data = kind.signature();
        let (func_ref, changed) = self.intern.callbacks.ensure(kind);
        if changed {
            self.intern.callback_uses.push(Vec::new());
            let sig = self.func.func.import_function(data);
            debug_assert_eq!(func_ref, sig);
        }
        func_ref
    }

    pub fn node(&self, node: Node) -> Option<Node> {
        if node.is_gnd(self.db) {
            None
        } else {
            Some(node)
        }
    }

    pub fn nodes(
        &mut self,
        hi: Node,
        lo: Option<Node>,
        kind: impl Fn(Node, Option<Node>) -> ParamKind,
    ) -> Value {
        let hi = self.node(hi);
        let lo = lo.and_then(|lo| self.node(lo));
        match (hi, lo) {
            (Some(hi), None) => self.use_param(kind(hi, None)),
            (None, Some(lo)) => {
                let lo = self.use_param(kind(lo, None));
                self.func.ins().fneg(lo)
            }
            // TODO refactor to nice if let binding when stable
            (Some(hi), Some(lo)) => {
                if let Some(inverted) = self.get_param(kind(lo, Some(hi))) {
                    self.func.ins().fneg(inverted)
                } else {
                    self.use_param(kind(hi, Some(lo)))
                }
            }
            (None, None) => F_ZERO,
        }
    }

    /// Start lowering a `$limit` function by allocating a state slot
    /// for the limit call. `probe` is the first argument (voltage or current probe)
    /// to `$limit`.
    ///
    /// The returned limit state *must* be passed to `finish_limit` to ensure corectness
    pub fn start_limit(&mut self, probe: Value) -> LimitState {
        let mut unknown = probe;
        if let Some(inst) = self.func.func.dfg.value_def(unknown).inst() {
            debug_assert_eq!(self.func.func.dfg.insts[inst].opcode(), Opcode::Fneg);
            unknown = self.func.func.dfg.instr_args(inst)[0];
        }
        let dst = self.intern.lim_state.raw.entry(unknown);
        let state = LimitState::from(dst.index());
        // value is a placeholder that will be populated by insert_limit
        dst.or_default().push((F_ZERO, probe != unknown));
        debug_assert!(!self.inside_lim);
        self.inside_lim = true;
        state
    }

    pub fn finish_limit(&mut self, state: LimitState, mut val: Value) -> Value {
        val = self.call1(CallBackKind::StoreLimit(state), &[val]);
        self.intern.lim_state[state].last_mut().unwrap().0 = val;
        debug_assert!(self.inside_lim);
        self.inside_lim = false;
        val
    }

    pub fn implicit_equation(&mut self, kind: ImplicitEquationKind) -> (ImplicitEquation, Value) {
        let equation = self.intern.implicit_equations.push_and_get_key(kind);
        let place = self.dec_place(PlaceKind::CollapseImplicitEquation(equation));
        self.func.def_var(place, FALSE);
        let val = self.use_param(ParamKind::ImplicitUnknown(equation));
        (equation, val)
    }

    pub fn def_resist_residual(&mut self, residual_val: Value, equation: ImplicitEquation) {
        let place = PlaceKind::ImplicitResidual { equation, reactive: false };
        let place = self.dec_place(place);
        self.func.def_var(place, residual_val);
    }

    pub fn def_react_residual(&mut self, residual_val: Value, equation: ImplicitEquation) {
        let place = PlaceKind::ImplicitResidual { equation, reactive: true };
        let place = self.dec_place(place);
        self.func.def_var(place, residual_val);
    }

    pub fn insert_cast(&mut self, val: Value, src: &Type, dst: &Type) -> Value {
        let op = match (dst, src) {
            (Type::Real, Type::Integer) => Opcode::IFcast,
            (Type::Integer, Type::Real) => Opcode::FIcast,
            (Type::Bool, Type::Real) => Opcode::FBcast,
            (Type::Real, Type::Bool) => Opcode::BFcast,
            (Type::Integer, Type::Bool) => Opcode::BIcast,
            (Type::Bool, Type::Integer) => Opcode::IBcast,
            (Type::Array { .. }, Type::EmptyArray) | (Type::EmptyArray, Type::Array { .. }) => {
                return val
            }
            _ => unreachable!("unknown cast found  {:?} -> {:?}", src, dst),
        };
        let inst = self.func.ins().unary(op, val).0;
        self.func.func.dfg.first_result(inst)
    }

    pub fn make_select(
        &mut self,
        cond: Value,
        lower_branch: impl FnMut(&mut Self, bool) -> Value,
    ) -> Value {
        let (then_src, else_src) = self.make_cond(cond, lower_branch);

        self.func.ins().phi(&[then_src, else_src])
    }

    pub fn make_cond<T>(
        &mut self,
        cond: Value,
        mut lower_branch: impl FnMut(&mut Self, bool) -> T,
    ) -> ((Block, T), (Block, T)) {
        let then_dst = self.func.create_block();
        let else_dst = self.func.create_block();
        let next_bb = self.func.create_block();

        self.func.ins().br(cond, then_dst, else_dst);
        self.func.seal_block(then_dst);
        self.func.seal_block(else_dst);

        // Round-4 audit: branch classifications are path-scoped across the two
        // arms (see `classified_branches`). The else arm starts from the set
        // that reached the `if`, not from whatever the then arm added, and the
        // union is what reaches the code after the merge.
        let entry_classified = self.classified_branches.clone();

        self.func.switch_to_block(then_dst);
        self.func.ensure_inserted_block();
        let then_val = lower_branch(self, true);
        self.func.ins().jump(next_bb);
        let then_tail = self.func.current_block();

        let then_classified = std::mem::replace(&mut self.classified_branches, entry_classified);

        self.func.switch_to_block(else_dst);
        self.func.ensure_inserted_block();
        let else_val = lower_branch(self, false);
        self.func.ins().jump(next_bb);
        let else_tail = self.func.current_block();

        self.classified_branches.extend(then_classified);

        self.func.switch_to_block(next_bb);
        self.func.ensure_inserted_block();
        self.func.seal_block(next_bb);

        ((then_tail, then_val), (else_tail, else_val))
    }

    pub(crate) fn get_srcloc(&self) -> SourceLoc {
        self.func.get_srcloc()
    }

    pub(crate) fn set_srcloc(&mut self, loc: SourceLoc) {
        self.func.set_srcloc(loc)
    }

    pub(crate) fn ins(&mut self) -> InsertBuilder<'_, FuncInstBuilder<'_, 'c>> {
        self.func.ins()
    }

    pub fn fconst(&mut self, val: f64) -> Value {
        self.func.fconst(val)
    }

    /// LRM 9.18 Table 9-29 (round-3 audit): `$angle` resolves to
    /// "$angle_specified + $angle_hier, **modulo 360 degrees**", with the
    /// allowed range "0 <= $angle < 360". The sum was implemented and the
    /// modulo was not, so two levels of 200 degrees read back as 400.
    ///
    /// `x - 360*floor(x/360)` rather than a `%`: the value is a real, and this
    /// form is the mathematically correct non-negative remainder for negative
    /// angles too (-90 -> 270), which C's `fmod` and Verilog's `%` are not.
    ///
    /// Applied wherever a `$angle` value is materialised, so every route into
    /// it -- the netlist `_angle=`, a paramset override, an instance
    /// `#(.$angle(...))`, and any composition of them -- lands in range.
    pub fn normalize_angle(&mut self, val: Value) -> Value {
        let full = self.fconst(360.0);
        let turns = self.ins().fdiv(val, full);
        let whole = self.ins().floor(turns);
        let wrapped = self.ins().fmul(full, whole);
        self.ins().fsub(val, wrapped)
    }

    pub fn iconst(&mut self, val: i32) -> Value {
        self.func.iconst(val)
    }

    pub fn sconst(&mut self, val: &str) -> Value {
        self.func.sconst(val)
    }

    pub(crate) fn create_block(&mut self) -> Block {
        self.func.create_block()
    }

    pub(crate) fn switch_to_block(&mut self, bb: Block) {
        self.func.switch_to_block(bb)
    }

    pub(crate) fn seal_block(&mut self, bb: Block) {
        self.func.seal_block(bb)
    }

    pub(crate) fn dfg(&self) -> &DataFlowGraph {
        &self.func.func.dfg
    }

    pub(crate) fn dfg_mut(&mut self) -> &mut DataFlowGraph {
        &mut self.func.func.dfg
    }

    pub(crate) fn ensured_sealed(&mut self) {
        self.func.ensured_sealed()
    }

    pub(crate) fn current_block(&self) -> Block {
        self.func.current_block()
    }
}
