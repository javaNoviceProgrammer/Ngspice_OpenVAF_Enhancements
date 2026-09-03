use std::hash::BuildHasherDefault;
use std::iter::FilterMap;

use ahash::{AHashMap, AHashSet};
use bitset::HybridBitSet;
pub use callbacks::{
    CallBackKind, FileOp, NoiseTable, ParamInfoKind, PrintDst, RetFlag, RngFun, ScanKind,
};
use hir::{
    Branch, BranchWrite, CompilationDB, Module, Node, ParamSysFun, Parameter, Type, Variable,
};
use indexmap::IndexMap;
use lasso::Rodeo;
use mir::builder::InstBuilder;
use mir::{DataFlowGraph, FuncRef, Function, Inst, KnownDerivatives, Param, Unknown, Value};
use mir_build::{FunctionBuilder, FunctionBuilderContext, RetBuilder};
use rustc_hash::FxHasher;
use stdx::packed_option::PackedOption;
use stdx::{impl_debug_display, impl_idx_from};
use typed_index_collections::TiVec;
use typed_indexmap::{map, TiMap, TiSet};

use crate::body::BodyLoweringCtx;
use crate::ctx::LoweringCtx;

macro_rules! match_signature {
    ($signature:ident: $($case:ident $(| $extra_case:ident)* => $res:expr),*) => {
        match $signature {
            $($case $(|$extra_case)* => $res,)*
            signature => unreachable!("invalid signature {:?}",signature)
        }

    };
}

mod body;
mod callbacks;
mod ctx;
mod expr;
pub mod fmt;
mod parameters;
mod state;
mod stmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ImplicitEquationKind {
    Ddt,
    NoiseSrc,
    Idt(IdtKind),
    /// Synthetic input node y_synth for absdelay slot `i`; enforces V(y_synth) = y_expr.
    AbsDelayInput(u32),
    /// Output node z for absdelay slot `i`; its equation row is stamped by the simulator.
    AbsDelayOutput(u32),
    /// Free unknown driven into the LHS branch of indirect branch assignment slot `i`
    /// (`<dst> : <lhs> == <rhs>;`); its equation row enforces `lhs == rhs`.
    IndirectBranch(u32),
    /// State variable `i` of a `laplace_*` transfer-function realization (controllable
    /// canonical form); its reactive/resistive residuals encode `dx_i/dt = ...`.
    LaplaceState(u32),
    /// Output state `i` of a `slew()` call; its reactive/resistive residuals encode a
    /// rate-limited tracking loop that follows the input while bounding `dy/dt`.
    Slew(u32),
    /// Output state `i` of a `transition()` call; same rate-limited tracking loop as
    /// `Slew`, applied to the (optionally delayed) input.
    Transition(u32),
    /// Synthetic input node y_synth for last_crossing slot `i`; enforces
    /// `V(y_synth) = watched_expr`.
    LastCrossingInput(u32),
    /// Output node z for last_crossing slot `i`; its equation row is stamped by the
    /// simulator with the time of the most recent qualifying zero-crossing of
    /// `V(y_synth)`'s history.
    LastCrossingOutput(u32),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum CurrentKind {
    Branch(Branch),
    Unnamed { hi: Node, lo: Option<Node> },
    Port(Node),
}

impl From<BranchWrite> for CurrentKind {
    fn from(kind: BranchWrite) -> Self {
        match kind {
            BranchWrite::Named(branch) => CurrentKind::Branch(branch),
            BranchWrite::Unnamed { hi, lo } => CurrentKind::Unnamed { hi, lo },
        }
    }
}

impl TryFrom<CurrentKind> for BranchWrite {
    type Error = ();
    fn try_from(kind: CurrentKind) -> Result<BranchWrite, ()> {
        match kind {
            CurrentKind::Branch(branch) => Ok(BranchWrite::Named(branch)),
            CurrentKind::Unnamed { hi, lo } => Ok(BranchWrite::Unnamed { hi, lo }),
            CurrentKind::Port(_) => Err(()),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ParamKind {
    Param(Parameter),
    Abstime,
    EnableIntegration,
    EnableLim,
    PrevState(LimitState),
    NewState(LimitState),
    Voltage { hi: Node, lo: Option<Node> },
    Current(CurrentKind),
    Temperature,
    ParamGiven { param: Parameter },
    PortConnected { port: Node },
    ParamSysFun(ParamSysFun),
    HiddenState(Variable),
    ImplicitUnknown(ImplicitEquation),
    /// True only on the very first `eval()` call of this instance's lifetime (gates
    /// `@(initial_step)`). A one-shot, monotonic approximation of the LRM's
    /// "fires once per analysis" semantics -- see `Stmt::EventControl` lowering.
    IsInitialStep,
    /// Enhancement-53: true only on the dedicated post-analysis `eval()` call the
    /// simulator issues once an analysis has completed (gates `@(final_step)`);
    /// that call's results are not loaded into the matrix/RHS. See
    /// `Stmt::EventControl` lowering, `EVAL_FLAG_IS_FINAL_STEP` in
    /// `openvaf/osdi/src/eval.rs`, and ngspice's `OSDIfinalStep`.
    IsFinalStep,
    /// Enhancement-8: persistent real storage slot `i`, read at the start of `eval()` --
    /// same read-at-start/store-at-end-of-eval() persistence as `HiddenState(Variable)`,
    /// but for compiler-synthesized per-call-site state (`cross`/`above`/`timer` edge
    /// detection) that has no source-level `Variable` to key off of. See
    /// `PlaceKind::EventState` (the write side) and `openvaf/osdi/src/inst_data.rs`'s
    /// `event_state`/`read_event_state`/`store_event_state`.
    EventState(u32),
}

impl ParamKind {
    /// Enhancement-327: ASKS whether this parameter is a plain node potential rather
    /// than asserting it. `ddx`'s unknown is user-supplied, so lowering must be able to
    /// inspect it -- a probe that is not one (a ground reference, a flow probe) simply
    /// is not an unknown of the DAE system and its derivative is zero.
    ///
    /// This replaced a panicking `unwrap_pot_node` (removed once E-327 left it with no
    /// callers): on a user-supplied probe, "not a node potential" is an ordinary answer,
    /// not an internal invariant violation.
    pub fn pot_node(&self) -> Option<Node> {
        match self {
            ParamKind::Voltage { hi, lo: None } => Some(*hi),
            _ => None,
        }
    }

    pub fn op_dependent(&self) -> bool {
        matches!(
            self,
            ParamKind::Voltage { .. }
                | ParamKind::Current(_)
                | ParamKind::ImplicitUnknown(_)
                | ParamKind::Abstime
                | ParamKind::EnableIntegration
                | ParamKind::HiddenState(_)
                | ParamKind::PrevState(_)
                | ParamKind::NewState(_)
                | ParamKind::EnableLim
                | ParamKind::IsInitialStep
                | ParamKind::IsFinalStep
                | ParamKind::EventState(_)
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum IdtKind {
    Basic,
    Ic,
    Assert,
    Modulus,
    ModulusOffset,
}

impl IdtKind {
    pub const fn num_params(self) -> u16 {
        match self {
            IdtKind::Basic => 1,
            IdtKind::Ic => 2,
            IdtKind::Assert | IdtKind::Modulus => 3,
            IdtKind::ModulusOffset => 4,
        }
    }
    pub const fn has_ic(self) -> bool {
        !matches!(self, IdtKind::Basic)
    }

    pub const fn has_assert(self) -> bool {
        matches!(self, IdtKind::Assert)
    }

    pub const fn has_modulus(self) -> bool {
        matches!(self, IdtKind::Modulus | IdtKind::ModulusOffset)
    }

    pub const fn has_offset(self) -> bool {
        matches!(self, IdtKind::ModulusOffset)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum PlaceKind {
    Var(Variable),
    FunctionReturn(hir::Function),
    FunctionArg(hir::FunctionArg),
    Contribute {
        dst: BranchWrite,
        reactive: bool,
        voltage_src: bool,
    },
    ImplicitResidual {
        equation: ImplicitEquation,
        reactive: bool,
    },
    CollapseImplicitEquation(ImplicitEquation),
    IsVoltageSrc(BranchWrite),
    /// A parameter during param initiliztion is mutable (write default in case its not given)
    Param(Parameter),
    ParamMin(Parameter),
    ParamMax(Parameter),
    BoundStep,
    /// Stores the current value of `td` for absdelay slot `i` into instance data.
    AbsDelayTime(u32),
    /// Stores the current value of `dir` for last_crossing slot `i` into instance data.
    LastCrossingDirection(u32),
    /// Enhancement-8: stores the new value of `cross`/`above`/`timer` edge-detection
    /// state slot `i` (the read side is `ParamKind::EventState(i)`) at the end of `eval()`.
    EventState(u32),
}

impl PlaceKind {
    pub fn ty(&self, db: &CompilationDB) -> Type {
        match *self {
            PlaceKind::Var(var) => var.ty(db),
            PlaceKind::FunctionReturn(fun) => fun.return_ty(db),
            PlaceKind::FunctionArg(arg) => arg.ty(db),

            PlaceKind::ImplicitResidual { .. }
            | PlaceKind::Contribute { .. }
            | PlaceKind::BoundStep
            | PlaceKind::AbsDelayTime(_)
            | PlaceKind::LastCrossingDirection(_)
            | PlaceKind::EventState(_) => Type::Real,
            PlaceKind::ParamMin(param) | PlaceKind::ParamMax(param) | PlaceKind::Param(param) => {
                param.ty(db)
            }
            PlaceKind::IsVoltageSrc(_) | PlaceKind::CollapseImplicitEquation(_) => Type::Bool,
        }
    }

    pub fn is_init_only(&self) -> bool {
        matches!(self, Self::CollapseImplicitEquation(_))
    }
}

impl From<hir::AssignmentLhs> for PlaceKind {
    fn from(hir: hir::AssignmentLhs) -> Self {
        match hir {
            hir::AssignmentLhs::Variable(var) => PlaceKind::Var(var),
            hir::AssignmentLhs::FunctionReturn(fun) => PlaceKind::FunctionReturn(fun),
            hir::AssignmentLhs::FunctionArg(arg) => PlaceKind::FunctionArg(arg),
        }
    }
}

#[derive(Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ImplicitEquation(u32);
impl_idx_from!(ImplicitEquation(u32));
impl_debug_display! {
    match ImplicitEquation {ImplicitEquation(i) => "inode{}", i;}
}

#[derive(Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct LimitState(u32);
impl_idx_from!(LimitState(u32));
impl_debug_display! {
    match LimitState {LimitState(i) => "lim_state{}", i;}
}

/// A mapping between abstractions used in the MIR and the corresponding
/// information from the HIR. This allows the MIR to remain independent of the frontend/HIR
#[derive(Debug, PartialEq, Clone)]
pub struct HirInterner {
    pub outputs: IndexMap<PlaceKind, PackedOption<Value>, BuildHasherDefault<FxHasher>>,
    pub params: TiMap<Param, ParamKind, Value>,
    pub callbacks: TiSet<FuncRef, CallBackKind>,
    pub callback_uses: TiVec<FuncRef, Vec<Inst>>,
    pub tagged_reads: IndexMap<Value, Variable, BuildHasherDefault<FxHasher>>,
    pub implicit_equations: TiVec<ImplicitEquation, ImplicitEquationKind>,
    pub lim_state: TiMap<LimitState, Value, Vec<(Value, bool)>>,
    /// Per absdelay slot: (eq_y = synthetic input node, eq_z = output node).
    /// One entry per `absdelay`: the synthetic-input and output implicit
    /// equations, plus the frozen-td flag (LRM 4.5.7: no maxdelay means the
    /// simulator latches td at its first transient evaluation).
    pub absdelay_equations: Vec<(ImplicitEquation, ImplicitEquation, bool)>,
    /// Per last_crossing slot: (eq_y = synthetic input node, eq_z = output node).
    pub last_crossing_equations: Vec<(ImplicitEquation, ImplicitEquation)>,
    /// Per indirect branch assignment slot: the free unknown's implicit equation.
    pub indirect_branch_equations: Vec<ImplicitEquation>,
    /// Enhancement-8: number of `ParamKind::EventState`/`PlaceKind::EventState` slots
    /// allocated so far -- one per `cross`/`above`/`timer` call site, handed out by
    /// `hir_lower::stmt::lower_event_control`. No per-slot metadata is needed (unlike
    /// `last_crossing_equations`): `openvaf/osdi/src/inst_data.rs` derives the live set of
    /// `EventState` slots directly by scanning `intern.params`, exactly like `hidden_state`.
    pub event_state_count: u32,
}

pub type LiveParams<'a> = FilterMap<
    map::Iter<'a, Param, ParamKind, Value>,
    fn((Param, (&'a ParamKind, &'a Value))) -> Option<(Param, &'a ParamKind, Value)>,
>;

impl Default for HirInterner {
    fn default() -> Self {
        Self {
            outputs: IndexMap::with_hasher(BuildHasherDefault::<FxHasher>::default()),
            params: TiMap::default(),
            callbacks: TiSet::default(),
            callback_uses: TiVec::default(),
            tagged_reads: IndexMap::with_hasher(BuildHasherDefault::<FxHasher>::default()),
            implicit_equations: TiVec::default(),
            lim_state: TiMap::default(),
            absdelay_equations: Vec::default(),
            last_crossing_equations: Vec::default(),
            indirect_branch_equations: Vec::default(),
            event_state_count: 0,
        }
    }
}

impl HirInterner {
    fn contains_ddx(
        ddx_calls: &mut AHashMap<FuncRef, (HybridBitSet<Unknown>, HybridBitSet<Unknown>)>,
        func: &Function,
        callbacks: &TiSet<FuncRef, CallBackKind>,
        ddx: &CallBackKind,
        val: Unknown,
        neg: bool,
    ) -> bool {
        if let Some(ddx) = callbacks.index(ddx) {
            let (pos_dst, neg_dst) = ddx_calls.entry(ddx).or_default();
            if neg {
                neg_dst.insert(val, func.dfg.num_values());
            } else {
                pos_dst.insert(val, func.dfg.num_values());
            }
            true
        } else {
            false
        }
    }

    pub fn unknowns(&self, func: impl AsRef<Function>, sim_derivatives: bool) -> KnownDerivatives {
        let func = func.as_ref();
        let mut unknowns = TiSet::default();
        let mut ddx_calls = AHashMap::new();
        // let mut nodes: AHashMap<NodeId, HybridBitSet<Value>> = AHashMap::new();
        // let mut required_nodes: IndexSet<NodeId, RandomState> = IndexSet::default();
        for (param, (kind, &val)) in self.params.iter_enumerated() {
            if func.dfg.value_dead(val) {
                continue;
            }

            let param_required = Self::contains_ddx(
                &mut ddx_calls,
                func,
                &self.callbacks,
                &CallBackKind::Derivative(param),
                unknowns.len().into(),
                false,
            );

            let mut node_required = |node, neg| {
                Self::contains_ddx(
                    &mut ddx_calls,
                    func,
                    &self.callbacks,
                    &CallBackKind::NodeDerivative(node),
                    unknowns.len().into(),
                    neg,
                )
            };

            let required = match *kind {
                ParamKind::Voltage { hi, lo: Some(lo) } => {
                    sim_derivatives | node_required(hi, false) | node_required(lo, true)
                }
                ParamKind::Voltage { hi, lo: None } => sim_derivatives | node_required(hi, false),
                ParamKind::Current(_) | ParamKind::ImplicitUnknown(_) => sim_derivatives,
                _ => param_required,
            };

            if required {
                unknowns.insert(val);
            }
        }

        for (param, vals) in self.lim_state.iter() {
            for &(val, neg) in vals {
                let param = func.dfg.value_def(*param).unwrap_param();

                let mut required = Self::contains_ddx(
                    &mut ddx_calls,
                    func,
                    &self.callbacks,
                    &CallBackKind::Derivative(param),
                    unknowns.len().into(),
                    neg,
                );

                let mut node_required = |node, neg| {
                    Self::contains_ddx(
                        &mut ddx_calls,
                        func,
                        &self.callbacks,
                        &CallBackKind::NodeDerivative(node),
                        unknowns.len().into(),
                        neg,
                    )
                };

                match *self.params.get_index(param).unwrap().0 {
                    ParamKind::Voltage { hi, lo: None } => required |= node_required(hi, neg),
                    ParamKind::Voltage { hi, lo: Some(lo) } => {
                        required |= node_required(hi, false) | node_required(lo, !neg);
                    }
                    _ => (),
                };

                if required | sim_derivatives {
                    unknowns.insert(val);
                }
            }
        }

        KnownDerivatives { unknowns, ddx_calls }
    }

    pub fn is_param_live(&self, func: impl AsRef<Function>, kind: &ParamKind) -> bool {
        let func = func.as_ref();
        if let Some(val) = self.params.raw.get(kind) {
            !func.dfg.value_dead(*val)
        } else {
            false
        }
    }

    pub fn is_param_live_(
        params: &TiMap<Param, ParamKind, Value>,
        func: &Function,
        kind: &ParamKind,
    ) -> bool {
        if let Some(val) = params.raw.get(kind) {
            !func.dfg.value_dead(*val)
        } else {
            false
        }
    }

    pub fn ensure_param(&mut self, func: impl AsMut<Function>, kind: ParamKind) -> Value {
        Self::ensure_param_(&mut self.params, func, kind)
    }

    pub fn ensure_param_(
        params: &mut TiMap<Param, ParamKind, Value>,
        mut func: impl AsMut<Function>,
        kind: ParamKind,
    ) -> Value {
        let len = params.len();
        let entry = params.raw.entry(kind);
        *entry.or_insert_with(|| func.as_mut().dfg.make_param(len.into()))
    }

    pub fn live_params<'a>(
        &'a self,
        dfg: &'a DataFlowGraph,
    ) -> FilterMap<
        map::Iter<'a, Param, ParamKind, Value>,
        impl FnMut((Param, (&'a ParamKind, &'a Value))) -> Option<(Param, &'a ParamKind, Value)> + Clone,
    > {
        self.params.iter_enumerated().filter_map(|(param, (kind, val))| {
            if dfg.value_dead(*val) {
                None
            } else {
                Some((param, kind, *val))
            }
        })
    }
}

pub struct MirBuilder<'a> {
    db: &'a CompilationDB,
    module: Module,
    is_output: &'a dyn Fn(PlaceKind) -> bool,
    required_vars: &'a mut dyn Iterator<Item = Variable>,
    tagged_reads: AHashSet<Variable>,
    tag_writes: bool,
    ctx: Option<&'a mut FunctionBuilderContext>,
    lower_equations: bool,
}

impl<'a> MirBuilder<'a> {
    pub fn new(
        db: &'a CompilationDB,
        module: Module,
        is_output: &'a dyn Fn(PlaceKind) -> bool,
        required_vars: &'a mut dyn Iterator<Item = Variable>,
    ) -> MirBuilder<'a> {
        MirBuilder {
            db,
            module,
            tagged_reads: AHashSet::new(),
            is_output,
            required_vars,
            ctx: None,
            lower_equations: false,
            tag_writes: false,
        }
    }

    pub fn tag_reads(&mut self, var: Variable) -> bool {
        self.tagged_reads.insert(var)
    }

    pub fn with_tagged_reads(mut self, tagged_vars: AHashSet<Variable>) -> Self {
        self.tagged_reads = tagged_vars;
        self
    }

    pub fn tag_writes(&mut self) {
        self.tag_writes = true;
    }

    pub fn with_tagged_writes(mut self) -> Self {
        self.tag_writes = true;
        self
    }

    pub fn lower_equations(&mut self) {
        self.lower_equations = true;
    }

    pub fn with_equations(mut self) -> Self {
        self.lower_equations = true;
        self
    }

    pub fn with_ctx(mut self, ctx: &'a mut FunctionBuilderContext) -> Self {
        self.ctx = Some(ctx);
        self
    }

    pub fn with_builder_ctx(mut self, ctx: &'a mut FunctionBuilderContext) -> Self {
        self.ctx = Some(ctx);
        self
    }

    pub fn build(self, literals: &mut Rodeo) -> (Function, HirInterner) {
        let mut func = Function::default();
        let mut interner = HirInterner::default();

        let mut ctx_;
        let ctx = if let Some(ctx) = self.ctx {
            ctx
        } else {
            ctx_ = FunctionBuilderContext::new();
            &mut ctx_
        };

        let builder: FunctionBuilder<'_> =
            FunctionBuilder::new(&mut func, literals, ctx, self.tag_writes);
        let path = self.module.name(self.db);
        let analog_initial_body = self.module.analog_initial_block(self.db);
        let analog_body = self.module.analog_block(self.db);

        let mut ctx = LoweringCtx::new(self.db, builder, !self.lower_equations, &mut interner)
            .with_tagged_vars(self.tagged_reads);
        let mut body_ctx =
            BodyLoweringCtx { ctx: &mut ctx, body: analog_initial_body.borrow(), path: &path };

        // Enhancement-456: `analog initial` runs ONCE, not on every evaluation.
        //
        // LRM 5.2: "The analog initial block is executed once for each analysis".
        // Its statements used to be lowered straight into the front of the eval
        // function -- concatenated with the main analog block -- so they re-ran on
        // every evaluation and overwrote whatever the model had accumulated. That
        // silently destroyed the one thing the construct exists for: a variable
        // initialised there could no longer hold state.
        //
        //     real peak;
        //     analog initial begin peak = 0.0; end          // <- breaks it
        //     analog begin
        //       if (V(in) > peak) peak = V(in);             // never holds a peak;
        //       V(out) <+ peak;                             //   follows the input
        //     end                                           //   back down instead
        //
        // The identical model with the initialisation removed, or written as
        // `@(initial_step) peak = 0.0;` inside the main block, worked correctly --
        // which is exactly the gate used here. `ParamKind::IsInitialStep` is true
        // on an instance's first evaluation of an analysis (once per analysis per
        // instance: once for a whole dc sweep, twice for `op` then `dc`), which is
        // the LRM's baseline rule.
        //
        // Statements still lower in source order and still run BEFORE the main
        // block, so multiple `analog initial` blocks compose exactly as before --
        // they are simply no longer re-applied afterwards.
        // Emitted ONLY when there is something to gate. A module with no `analog
        // initial` block must lower exactly as before -- otherwise every model in
        // the corpus picks up an `IsInitialStep` parameter and an empty
        // conditional it never asked for, which showed up immediately as a
        // 32-byte change in a MEXTRAM model that has no initial block at all.
        //
        // ROUND-3 AUDIT (2026-09-02): the gate below is what makes the block's
        // statements run on the instance's FIRST Newton iteration of an
        // analysis -- which is exactly the iteration the LRM 9.4.6/9.5.9
        // deferral treats as superseded. Every display and every file write in
        // an `analog initial` block was therefore buffered and then dropped:
        // one module with $strobe/$display/$write/$monitor and an
        // open-write-close sequence in its initial block produced ZERO output
        // across op+tran+dc, and left the file it created at zero bytes, while
        // $debug and $info (which take the immediate path) printed once per
        // analysis -- proving the block ran and only its output was lost.
        // LRM 5.2.1 forbids access functions, analog operators, contributions
        // and event controls in the block, so reporting is one of only two
        // things it can do at all. `in_analog_initial` tags those statements
        // immediate, exactly as `in_event_ctx` does for `@(initial_step)`.
        if !body_ctx.body.entry().is_empty() {
            let is_initial = body_ctx.ctx.use_param(ParamKind::IsInitialStep);
            body_ctx.ctx.make_cond(is_initial, |ctx, branch| {
                if branch {
                    let outer = ctx.in_analog_initial;
                    ctx.in_analog_initial = true;
                    BodyLoweringCtx { ctx, body: analog_initial_body.borrow(), path: &path }
                        .lower_entry_stmts();
                    ctx.in_analog_initial = outer;
                }
            });
        }

        // ... and normal analog blocks afterwards
        body_ctx.body = analog_body.borrow();
        body_ctx.lower_entry_stmts();

        for var in self.required_vars {
            ctx.dec_place(PlaceKind::Var(var));
        }
        let is_output = self.is_output;
        ctx.intern.outputs = ctx
            .places
            .iter_enumerated()
            .map(|(place, kind)| {
                if is_output(*kind) {
                    let mut val = ctx.func.use_var(place);
                    val = ctx.func.ins().ensure_optbarrier(val);
                    (*kind, val.into())
                } else {
                    (*kind, None.into())
                }
            })
            .collect();
        ctx.func.ins().ret();
        ctx.func.finalize();
        (func, interner)
    }
}
