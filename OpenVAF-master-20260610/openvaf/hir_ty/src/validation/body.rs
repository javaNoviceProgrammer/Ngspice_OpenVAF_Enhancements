use std::mem::replace;

use ahash::{HashMap, HashSet};
use hir_def::body::Body;
use hir_def::{
    BranchId, BuiltIn, CaseKind, DefWithBodyId, DisciplineId, Expr, ExprId, FunctionArgLoc,
    FunctionId, Literal, Lookup, NatureId, NodeId, ParamId, Path, Stmt, StmtId, Type, VarId,
};
use hir_def::expr::{CaseCond, Event};
use stdx::impl_display;
use syntax::ast::{AssignOp, BinaryOp, UnaryOp};
use syntax::name::{AsIdent, Name};

use crate::builtin::{
    ABSDELAY_MAX, DDT_TOL, IDT_IC_ASSERT_TOL, NATURE_ACCESS_BRANCH, NATURE_ACCESS_NODES,
    NATURE_ACCESS_NODE_GND, NATURE_ACCESS_PORT_FLOW, NOISE_TABLE_FILE, NOISE_TABLE_FILE_NAME,
    NOISE_TABLE_INLINE, NOISE_TABLE_INLINE_NAME, SIMPARAM_NO_DEFAULT,
    TRANSITION_DELAY_RISET_FALLT_TOL,
};
use crate::db::HirTyDB;
use crate::inference::{BranchWrite, InferenceResult, ResolvedFun};
use crate::lower::BranchKind;
use crate::types::{BuiltinInfo, Signature, Ty};

/// Enhancement-421: the simulator parameters ngspice actually serves, taken
/// from `src/osdi/osdiload.c` (`sim_params` and `sim_params_str`).
///
/// Deliberately NOT the LRM's list. The LRM names `minr`, `imelt`, `shrink`,
/// `imax` and `rthresh`, and ngspice serves none of them -- a model using one
/// dies. For `$simparam$str` the two sets do not intersect at all: the LRM
/// names `cwd`, `module`, `instance` and `path`; ngspice serves
/// `analysis_name` and `simulator`. Listing the LRM's names here would warn
/// on the names that work and stay silent on the ones that abort.
///
/// Enhancement-476: `temp` was missing, and these lists are now module-level
/// so that the diagnostic in `validation.rs` can be BUILT from them instead of
/// repeating them.
///
/// Enhancement-434 added `temp` to ngspice's `sim_params[]` -- it is how a
/// model ported from Spectre asks for the simulation temperature -- and did
/// not add it here. The compiler therefore warned on the exact call that
/// enhancement exists to serve, and the note beside the warning told the
/// author the name is fatal at run time when in fact it returns the ambient.
/// The diagnostic's own copy of the list had drifted the same way, which is
/// why both now come from here.
pub(crate) const SIMPARAM_NAMES: [&'static str; 15] = [
    "abstime",
    "abstol",
    "epsmin",
    "gdev",
    "gmin",
    "iniLim",
    "iteration",
    "reltol",
    "scale",
    "simulatorSubversion",
    "simulatorVersion",
    "sourceScaleFactor",
    "temp",
    "tnom",
    "vntol",
];

/// The `$simparam$str` channel; see [`SIMPARAM_NAMES`].
pub(crate) const SIMPARAM_STR_NAMES: [&'static str; 2] = ["analysis_name", "simulator"];

#[derive(PartialEq, Eq, Clone, Debug)]
pub enum IllegalCtxAccessKind {
    NatureAccess,
    AnalogOperator { name: Name, is_standard: bool, non_const_dominator: Box<[ExprId]> },
    /// Enhancement-424: a noise or `ac_stim` source inside a run-time loop.
    ///
    /// Its own kind rather than `AnalogOperator` because the restriction is
    /// narrower: these are legal in a conditional (and work correctly there),
    /// only a loop is the problem. And because the message should say what they
    /// are -- "analog operator 'white_noise'" would be wrong twice over.
    SmallSignalSourceInLoop { name: Name },
    AnalysisFun { name: Name },
    Var(VarId),
}

#[derive(PartialEq, Eq, Clone, Debug)]
pub struct IllegalCtxAccess {
    pub kind: IllegalCtxAccessKind,
    pub ctx: BodyCtx,
    pub expr: ExprId,
}

#[derive(PartialEq, Eq, Clone, Debug)]
pub enum BodyValidationDiagnostic {
    /// Enhancement-392: a runtime `$table_model` with more knots than the emitted
    /// code normalises.
    ///
    /// The compile-time forms sort and de-duplicate at ANY size; the runtime form
    /// emits a sorting network, which has to be bounded. Above that bound the two
    /// silently disagreed again on unsorted data. Saying so is the point -- the
    /// table is still usable, it just has to arrive already ascending.
    TableTooLargeToSort { expr: ExprId, len: usize, max: usize },

    /// Enhancement-390: a `$table_model` data file that could not be used.
    ///
    /// The file is read during LOWERING, which has no diagnostic channel, so any
    /// problem -- a mistyped name, an unreadable file, an empty or malformed one --
    /// produced an EMPTY table and the device silently contributed zero. Nothing
    /// was reported at compile time and nothing was odd at run time; the model just
    /// did nothing. Whether the file is usable is decided when the report is built,
    /// where the root file and the VFS are both in hand.
    /// Enhancement-425: `ndim` is the DIMENSIONALITY OF THE CALL -- the number of
    /// input arguments before the data argument, exactly as `lower_table_model`
    /// computes it. The validator cannot infer it from the file: a perfectly good
    /// 1-D file such as `2 3 / 4 5 / 6 7` begins with numbers that read as a
    /// 2-dimensional header, so guessing from the content false-positives. The two
    /// forms have genuinely different grammars, so the check needs to know which
    /// one it is looking at.
    TableFileUnusable { expr: ExprId, path: Box<str>, ndim: usize },

    /// Enhancement-414: a `noise_table`/`noise_table_log` DATA FILE that could not be
    /// used. Exactly the `$table_model` story above, in the one place it was not
    /// checked: a missing, empty or unparseable file yielded an EMPTY table, and an
    /// empty noise table contributes nothing, so the noise source vanished. The output
    /// spectrum was then bit-for-bit identical to a model with no noise source at all,
    /// which is why a mistyped filename could not be noticed. The INLINE form has been
    /// validated since Enhancement-396; the file form reached the runtime unexamined.
    NoiseTableFileUnusable { expr: ExprId, path: Box<str>, log: bool },

    /// Enhancement-395: a `$table_model` control-string code that is not
    /// implemented, or not a control code at all.
    ///
    /// The string was decoded by scanning for `'3'` and `'L'` anywhere in it.
    /// Every other LRM code -- `2` (quadratic spline), `D` (closest-point
    /// lookup), `I` (ignore this column), `E` (error on an extrapolation
    /// request) -- and every typo silently fell through to linear interpolation
    /// with clamped ends. A model asking for a quadratic spline got a LINEAR
    /// one; a model asking for `E`, whose whole purpose is to be told when the
    /// table is left, got silent clamping instead. Saying so is the point.
    TableControlUnsupported { expr: ExprId, code: Box<str>, why: Box<str> },

    /// Enhancement-390: `disable <name>` naming no enclosing named block.
    ///
    /// Lowering resolves the name against the enclosing named blocks and, on a
    /// miss, degraded to a no-op on purpose. That is invisible and wrong for the
    /// case that actually happens: a typo'd label, or a block that was never
    /// labelled at all. The statement silently did nothing, so a loop meant to
    /// exit early ran to completion instead -- a changed answer from a spelling
    /// mistake, with no diagnostic anywhere.
    UnresolvedDisable { stmt: StmtId, name: Name },

    ExpectedPort {
        expr: ExprId,
        node: NodeId,
    },
    TrivialBranchAccess {
        branch: BranchWrite,
        expr: ExprId,
        stmt: StmtId,
    },
    /// Enhancement-395: an `$random`/`$dist_*` call inside a runtime loop draws
    /// the SAME number on every iteration.
    RngInLoop {
        name: Box<str>,
        expr: ExprId,
        stmt: StmtId,
    },
    /// Enhancement-396: `$limit` names a limiting function the target simulator
    /// is not known to provide.
    UnknownLimitFunction {
        name: Box<str>,
        nargs: usize,
        expr: ExprId,
        stmt: StmtId,
    },
    /// Enhancement-399: an analysis-name string that no analysis can ever match.
    /// `analysis("tarn")` is false in every analysis and
    /// `@(initial_step("tarn"))` never fires -- silently, so a typo turns a whole
    /// branch or initialisation block into dead code.
    UnknownAnalysisName {
        name: Box<str>,
        builtin: Box<str>,
        /// `None` for an `@(initial_step("..."))` phase filter: the phase list is
        /// lowered to bare strings with no span of their own, so the report is
        /// anchored on the event statement instead.
        expr: Option<ExprId>,
        stmt: StmtId,
    },
    /// Enhancement-421: a `$simparam`/`$simparam$str` name the simulator cannot
    /// resolve. Unlike its siblings this one is FATAL at run time -- the model
    /// aborts the analysis -- and nothing was said at compile time.
    UnknownSimparam {
        name: Box<str>,
        builtin: Box<str>,
        /// true for `$simparam`, which has a non-fatal two-argument form to
        /// suggest; `$simparam$str` has no such form.
        has_default_form: bool,
        expr: ExprId,
        stmt: StmtId,
    },
    /// Enhancement-396: a builtin was handed a compile-time-constant argument
    /// that its own definition forbids (a non-positive period, a direction that
    /// is not -1/0/+1, a malformed `noise_table` array, ...).
    InvalidBuiltinArg {
        builtin: Box<str>,
        what: Box<str>,
        why: Box<str>,
        expr: ExprId,
    },
    PotentialOfPortFlow {
        expr: ExprId,
        branch: Option<BranchId>,
    },
    ContributeToPortFlow {
        expr: ExprId,
        branch: BranchId,
    },
    // Enhancement-97: a contribution whose branch is entirely the `ground`
    // reference (`V(gnd) <+ ...`, `V(gnd, gnd) <+ ...`) -- both endpoints
    // collapse to node 0, so there is no unknown to contribute to. Used to
    // panic (`unreachable!()`) in `lower_contribute_unnamed_branch`.
    ContributeToGround {
        expr: ExprId,
    },
    IllegalContribute {
        stmt: StmtId,
        ctx: BodyCtx,
    },

    WriteToInputArg {
        expr: ExprId,
        arg: FunctionArgLoc,
    },

    IllegalParamAccess {
        def: ParamId,
        expr: ExprId,
        param: ParamId,
    },

    /// Enhancement-414: a parameter (or localparam) whose own default expression reads
    /// itself -- `parameter real p = p;`, `localparam real ls = ls + 1;`.
    ///
    /// The forward-reference check beside this one compares declaration order with `<`,
    /// so a self-reference (the same declaration) fell through it. The value that came
    /// out was not merely undefined but an artefact: the initializer was folded TWICE, so
    /// `ls = ls + 1` yielded 2 and `l2 = l2*3 + 7` yielded 28 -- silently, with the
    /// declaration that contains the mistake saying nothing.
    SelfReferentialParam {
        def: ParamId,
        expr: ExprId,
    },

    IllegalCtxAccess(IllegalCtxAccess),

    ConstSimparam {
        known: bool,
        expr: ExprId,
        stmt: StmtId,
    },

    UnsupportedFunction {
        expr: ExprId,
        func: BuiltIn,
    },

    IncompatibleNatureAccess {
        candidates: [Option<(Name, Name)>; 2],
        access_nature: Option<NatureId>,
        access_expr: ExprId,
        branch: String,
    },

    IllegalNatureAccess {
        is_pot: bool,
        access_expr: ExprId,
    },

    IncompatibleImplicitBranch {
        access: ExprId,
        node1: NodeId,
        node2: NodeId,
    },

    /// Enhancement-59: a cycle in the analog-function call graph
    /// (`f1` calls `f2` calls `f1`). The LRM forbids recursion; without this
    /// check the recursive inlining in lowering overflows the compiler stack.
    /// `cycle` holds the function names along the cycle, starting and ending
    /// with the offending function. Direct self-recursion never gets here --
    /// inside `f`, `f` resolves to the return variable and is diagnosed at
    /// inference (`InferenceDiagnostic::RecursiveFunctionCall`).
    RecursiveFunctionCall {
        expr: ExprId,
        cycle: Vec<Name>,
    },

    /// Enhancement-460: an event control statement where the LRM forbids one.
    ///
    /// LRM 5.2.1 lists three things an `analog initial` block "shall not contain":
    /// statements with access functions or analog operators, contribution statements,
    /// and EVENT CONTROL STATEMENTS. LRM 4.7.1 forbids the same three in an analog
    /// function. The first two were enforced in both; the third was accepted in both,
    /// and the guarded statement was then silently DROPPED -- an initialisation that
    /// looks careful and does nothing.
    IllegalEventControl {
        stmt: StmtId,
        ctx: BodyCtx,
    },

    /// Enhancement-85: a part-select (`v[msb:lsb]`) anywhere other than an
    /// instance port connection (which elaboration consumes textually).
    StrayPartSelect {
        expr: ExprId,
    },
    /// Enhancement-78: an integer literal spelled with don't-care digits
    /// (`'b1x?`) anywhere other than directly as a `casex`/`casez` item.
    StrayDontCareLiteral {
        expr: ExprId,
    },
    /// Enhancement-78: an `x` digit in a `casez` item -- only `z`/`?` are
    /// don't-cares under `casez` (use `casex` for `x` as well).
    XDigitInCaseZ {
        expr: ExprId,
    },
    /// Enhancement-78: `casex`/`casez` masks are bitwise, so the
    /// discriminant must be an integer.
    NonIntegerCaseXZ {
        kind: CaseKind,
        discr: ExprId,
    },
    /// Enhancement-375: a loop whose controlling condition provably cannot change
    /// between iterations. `always` distinguishes a condition that is a non-zero
    /// literal (certainly infinite) from one that is merely loop-invariant (either
    /// never entered or never left -- not decidable here, and both are defects).
    ///
    /// This is an ERROR rather than a lint because there is no correct object code
    /// for a model that cannot finish one evaluation. Emitting the loop hangs the
    /// simulator with no diagnostic at all; substituting a value invents a device.
    NonTerminatingLoop {
        cond: ExprId,
        always: bool,
    },
}

impl BodyValidationDiagnostic {
    pub fn collect(db: &dyn HirTyDB, def: DefWithBodyId) -> Vec<BodyValidationDiagnostic> {
        let body = db.body(def);
        let infere = db.inference_result(def);

        let ctx = match def {
            DefWithBodyId::ModuleId { initial: false, .. } => BodyCtx::AnalogBlock,
            DefWithBodyId::ModuleId { initial: true, .. } => BodyCtx::AnalogInitialBlock,
            DefWithBodyId::FunctionId(_) => BodyCtx::Function,
            _ => BodyCtx::Const,
        };

        let mut validator = BodyValidator {
            db,
            owner: def,
            body: &body,
            infer: &infere,
            diagnostics: Vec::new(),
            ctx,
            loop_depth: 0,
            disable_scopes: Vec::new(),
            non_const_dominator: Box::default(),
            non_trivial_branches: HashSet::default(),
            trivial_probes: HashMap::default(),
        };

        for stmt in &*body.entry_stmts {
            validator.validate_stmt(*stmt)
        }

        // Enhancement-78: every don't-care literal that survived collection
        // (i.e. was not consumed as a casex/casez item) is an error
        for &expr in &body.stray_dontcare_literals {
            validator.diagnostics.push(BodyValidationDiagnostic::StrayDontCareLiteral { expr });
        }

        // Enhancement-85: part-selects (`v[msb:lsb]`) are only legal in
        // instance port connections, which elaboration consumes textually --
        // one that reached body lowering is behavioral-code misuse.
        //
        // Enhancement-458: except as a filter coefficient vector, which is the
        // second `analog_filter_function_arg` form in LRM Syntax 4-3. Inference
        // resolves that one into its element slice, so a part select recorded in
        // either whole-array map was consumed legitimately and is not stray.
        for &expr in &body.stray_part_selects {
            if infere.array_var_refs.contains_key(&expr)
                || infere.array_param_refs.contains_key(&expr)
            {
                continue;
            }
            validator.diagnostics.push(BodyValidationDiagnostic::StrayPartSelect { expr });
        }

        // Enhancement-59: reject call-graph cycles among analog functions
        // (mutual recursion) before lowering inlines them forever.
        if let DefWithBodyId::FunctionId(func) = def {
            check_call_cycles(db, func, &infere, &mut validator.diagnostics);
        }

        for (branch, exprs) in validator.trivial_probes {
            for (stmt, expr) in exprs {
                validator.diagnostics.push(BodyValidationDiagnostic::TrivialBranchAccess {
                    branch,
                    expr,
                    stmt,
                })
            }
        }

        validator.diagnostics
    }
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum BodyCtx {
    AnalogBlock,
    AnalogInitialBlock,
    Conditional,
    /// Enhancement-70: the body of a runtime loop (for/while/do-while/
    /// repeat). Same restrictions as `Conditional`, but diagnosed as
    /// "loops" -- an analog operator inside a loop body used to be
    /// reported as "not allowed in conditions", which pointed users at
    /// the wrong construct (LRM 4.5.1 forbids analog operators in
    /// looping statements).
    Loop,
    EventControl,
    Function,
    ConstOrAnalysis,
    Const,
}

impl BodyCtx {
    fn allow_nature_access(self) -> bool {
        matches!(self, Self::AnalogBlock | Self::Conditional | Self::Loop | Self::EventControl)
    }

    fn allow_contribute(self) -> bool {
        matches!(self, Self::AnalogBlock | Self::Conditional | Self::Loop)
    }

    fn allow_analog_operator(self) -> bool {
        matches!(self, Self::AnalogBlock)
    }

    fn allow_analysis_fun(self) -> bool {
        !matches!(self, Self::Const)
    }

    fn allow_var_ref(self) -> bool {
        !matches!(self, Self::Const | Self::ConstOrAnalysis)
    }
}

impl_display! {
    match BodyCtx{
       BodyCtx::AnalogBlock => "analog block";
       BodyCtx::AnalogInitialBlock => "analog initial block";
       BodyCtx::Conditional => "conditions";
       BodyCtx::Loop => "loops";
       BodyCtx::EventControl => "events";
       BodyCtx::Function => "analog functions";
       BodyCtx::ConstOrAnalysis => "constant or analysis";
       BodyCtx::Const => "constants";
    }
}

/// Enhancement-375: does a literal condition select the loop body?
fn literal_is_truthy(lit: &Literal) -> bool {
    match *lit {
        Literal::Int(val) => val != 0,
        Literal::Float(val) => !val.is_zero(),
        // `while ("")` is not meaningful Verilog-A and `$inf` is non-zero; neither
        // is a zero-trip loop, so neither should suppress the diagnostic.
        Literal::String(_) | Literal::Inf => true,
    }
}

/// Enhancement-375: builtins that return a different value on each call, so a
/// condition containing one is not loop-invariant no matter what the body does.
fn builtin_is_impure(builtin: BuiltIn) -> bool {
    matches!(
        builtin,
        BuiltIn::random
            | BuiltIn::arandom
            | BuiltIn::dist_chi_square
            | BuiltIn::dist_exponential
            | BuiltIn::dist_poisson
            | BuiltIn::dist_uniform
            | BuiltIn::dist_erlang
            | BuiltIn::dist_normal
            | BuiltIn::dist_t
            | BuiltIn::rdist_chi_square
            | BuiltIn::rdist_exponential
            | BuiltIn::rdist_poisson
            | BuiltIn::rdist_uniform
            | BuiltIn::rdist_erlang
            | BuiltIn::rdist_normal
            | BuiltIn::rdist_t
    )
}

struct BodyValidator<'a> {
    db: &'a dyn HirTyDB,
    owner: DefWithBodyId,
    body: &'a Body,
    infer: &'a InferenceResult,
    diagnostics: Vec<BodyValidationDiagnostic>,
    ctx: BodyCtx,
    /// Enhancement-330: number of enclosing RUNTIME loops. `ctx` cannot express
    /// this: `validate_condition_in` REPLACES it rather than stacking, so an `if`
    /// nested inside a `for` resets it to `BodyCtx::Conditional`. It also only
    /// becomes `BodyCtx::Loop` when the controlling expression is non-constant,
    /// so `repeat(3)` would be missed.
    loop_depth: u32,
    /// Enhancement-390: names of the enclosing `begin : label` blocks, mirroring
    /// `hir_lower`'s `disable_scopes`, so a `disable` can be resolved here where
    /// diagnostics exist.
    disable_scopes: Vec<Name>,
    non_const_dominator: Box<[ExprId]>,
    non_trivial_branches: HashSet<BranchWrite>,
    trivial_probes: HashMap<BranchWrite, Vec<(StmtId, ExprId)>>,
}

impl BodyValidator<'_> {
    /// Enhancement-396: check the constant arguments of an event expression.
    ///
    /// `@(timer(start, period))` with a period of zero, a negative period, or a
    /// denormal one did not error and did not disable the timer -- it fired on
    /// EVERY solver evaluation. Over a 10 us transient a 1 us timer produced 10
    /// events and a zero period produced 120, one per timestep, so a period
    /// computed as `1/freq` with `freq = 0` silently turned a sampler into a
    /// per-iteration event. `@(cross(expr, dir))` likewise accepted any integer
    /// as the direction, where only -1, 0 and +1 mean anything.
    /// Enhancement-399: an event form was handed more arguments than it takes.
    /// They used to be dropped by an unconsumed iterator, so `@(cross(e,0,t,x,1,2))`
    /// behaved exactly like `@(cross(e,0))` and nothing said so.
    fn check_event_surplus(&mut self, form: &str, takes: usize, surplus: &[ExprId], stmt: StmtId) {
        if let Some(&first) = surplus.first() {
            let mut v =
                ExprValidator { parent: self, cond_diagnostic_sink: None, write: false, stmt };
            v.bad_arg(
                form,
                "the argument list",
                format!(
                    "has {} argument(s) more than the {takes} this event form \
                     takes; the surplus is ignored entirely",
                    surplus.len()
                ),
                first,
            );
        }
    }

    /// Enhancement-399: the event's required first argument is absent
    /// (`@(cross())`). This used to make `event_from_condition` bail, which
    /// degrades the WHOLE event control to an unconditional body -- so the
    /// guarded statement ran on every evaluation instead of on the event. It is
    /// recorded as `Expr::Missing` now, and must be rejected HERE: lowering
    /// panics on a missing expression (hir/src/body.rs), so leaving it to reach
    /// codegen would trade a wrong answer for a compiler crash.
    fn check_event_arg_present(&mut self, form: &str, expr: ExprId, stmt: StmtId) -> bool {
        if matches!(self.body.exprs[expr], Expr::Missing) {
            let mut v =
                ExprValidator { parent: self, cond_diagnostic_sink: None, write: false, stmt };
            v.bad_arg(form, "the argument list", "is empty; this event form \
                 requires at least the expression it watches".to_owned(), expr);
            return false;
        }
        true
    }

    fn validate_event(&mut self, event: &Event, stmt: StmtId) {
        match *event {
            // Enhancement-399: `@(initial_step("tarn"))` never fires -- the phase
            // filter is matched by the same fixed name set as `analysis()`, so a
            // typo turns the whole initialisation block into dead code, silently.
            Event::Global { kind, ref phases } => {
                let form = match kind {
                    hir_def::expr::GlobalEvent::InitialStep => "@(initial_step)",
                    hir_def::expr::GlobalEvent::FinalStep => "@(final_step)",
                };
                for ph in phases.iter() {
                    if !ExprValidator::ANALYSIS_NAMES.contains(&&**ph) {
                        self.diagnostics.push(
                            BodyValidationDiagnostic::UnknownAnalysisName {
                                name: ph.clone().into_boxed_str(),
                                builtin: form.to_owned().into_boxed_str(),
                                expr: None,
                                stmt,
                            },
                        );
                    }
                }
            }
            Event::Timer { t0, period, tol, enable, ref surplus } => {
                if !self.check_event_arg_present("@(timer)", t0, stmt) {
                    return;
                }
                let mut v = ExprValidator {
                    parent: self,
                    cond_diagnostic_sink: None,
                    write: false,
                    stmt,
                };
                v.require_non_negative("@(timer)", "the start time", t0);
                // A NON-POSITIVE PERIOD IS LEGAL. LRM 5.10.3.3: "If the period
                // expression evaluates to a value less than or equal to 0.0, the
                // timer shall trigger only once at the specified start_time." It
                // used to be refused ("the period must be greater than zero"),
                // which rejected the way a one-shot is written when the period is
                // computed rather than omitted -- while `@(timer(t0))`, the same
                // request spelled differently, was accepted and did exactly that.
                // The lowering now routes a non-positive period to the same
                // fire-once path, so nothing here needs to constrain it.
                let _ = period;
                // Enhancement-399: the tolerance was previously discarded, so a
                // negative one reached nothing and was reported by no one.
                if let Some(tol) = tol {
                    v.require_non_negative("@(timer)", "the time tolerance", tol);
                }
                // Nothing to constrain: LRM 5.10.3.3's `enable` argument enables
                // the event for ANY non-zero value, so no range applies. Inference
                // types it as a condition and the lowering gates the event on it;
                // it is named here only so the arity below counts it.
                let _ = enable;
                self.check_event_surplus("@(timer)", 4, surplus, stmt);
            }
            Event::Above { expr, time_tol, expr_tol, enable, ref surplus } => {
                if !self.check_event_arg_present("@(above)", expr, stmt) {
                    return;
                }
                let mut v =
                    ExprValidator { parent: self, cond_diagnostic_sink: None, write: false, stmt };
                if let Some(t) = time_tol {
                    v.require_non_negative("@(above)", "the time tolerance", t);
                }
                if let Some(t) = expr_tol {
                    v.require_non_negative("@(above)", "the expression tolerance", t);
                }
                // Nothing to constrain: LRM 5.10.3.2's `enable` argument enables
                // the event for ANY non-zero value, so no range applies. Inference
                // types it as a condition and the lowering gates the event on it;
                // it is named here only so the arity below counts it.
                let _ = enable;
                self.check_event_surplus("@(above)", 4, surplus, stmt);
            }
            Event::Cross { expr, dir: _, time_tol, expr_tol, enable, ref surplus } => {
                if !self.check_event_arg_present("@(cross)", expr, stmt) {
                    return;
                }
                let mut v = ExprValidator {
                    parent: self,
                    cond_diagnostic_sink: None,
                    write: false,
                    stmt,
                };
                if let Some(t) = time_tol {
                    v.require_non_negative("@(cross)", "the time tolerance", t);
                }
                if let Some(t) = expr_tol {
                    v.require_non_negative("@(cross)", "the expression tolerance", t);
                }
                // Nothing to constrain: LRM 5.10.3.1's `enable` argument enables
                // the event for ANY non-zero value, so no range applies. Inference
                // types it as a condition and the lowering gates the event on it;
                // it is named here only so the arity below counts it.
                let _ = enable;
                self.check_event_surplus("@(cross)", 5, surplus, stmt);
                self.validate_event_cross_dir(event, stmt);
            }
            Event::Or(ref events) => {
                for ev in events.iter() {
                    self.validate_event(ev, stmt);
                }
            }
            _ => {}
        }
    }

    fn validate_event_cross_dir(&mut self, event: &Event, stmt: StmtId) {
        match *event {
            Event::Cross { dir: Some(dir), .. } => {
                let v = ExprValidator {
                    parent: self,
                    cond_diagnostic_sink: None,
                    write: false,
                    stmt,
                };
                let val = v.const_num(dir);
                if let Some(val) = val {
                    if val != -1.0 && val != 0.0 && val != 1.0 {
                        let mut v = ExprValidator {
                            parent: self,
                            cond_diagnostic_sink: None,
                            write: false,
                            stmt,
                        };
                        v.bad_arg(
                            "@(cross)",
                            "the direction",
                            format!("must be -1 (falling), 0 (either) or +1 (rising), but is {val}"),
                            dir,
                        );
                    }
                }
            }
            // only ever called with a Cross event, from validate_event
            _ => {}
        }
    }

    fn validate_stmt(&mut self, stmt: StmtId) {
        let cond = match self.body.stmts[stmt] {
            Stmt::Assignment { dst, val, assignment_kind } => {
                self.validate_expr(val, stmt);

                if assignment_kind == AssignOp::Contribute && !self.ctx.allow_contribute() {
                    self.diagnostics
                        .push(BodyValidationDiagnostic::IllegalContribute { stmt, ctx: self.ctx })
                }
                // avoid duplicate errors
                else if self.infer.assignment_destination.contains_key(&stmt) {
                    self.validate_assignment_dst(dst, stmt);
                }

                return;
            }
            Stmt::EventControl { ref event, body } => {
                // LRM 5.2.1 / 4.7.1: neither an analog initial block nor an analog
                // function may contain an event control statement. Checked on the
                // STATEMENT rather than on what it guards, because the guarded body is
                // exactly what used to disappear without a word.
                if matches!(self.ctx, BodyCtx::AnalogInitialBlock | BodyCtx::Function) {
                    let ctx = self.ctx;
                    self.diagnostics
                        .push(BodyValidationDiagnostic::IllegalEventControl { stmt, ctx });
                }
                self.validate_event(event, stmt);
                event.walk_child_exprs(|e| self.validate_expr(e, stmt));
                let old = replace(&mut self.ctx, BodyCtx::EventControl);
                self.validate_stmt(body);
                self.ctx = old;
                return;
            }
            Stmt::Block { ref name, ref body } => {
                if let Some(name) = name {
                    self.disable_scopes.push(name.clone());
                }
                let named = name.is_some();
                body.iter().for_each(|stmt| self.validate_stmt(*stmt));
                if named {
                    self.disable_scopes.pop();
                }
                return;
            }

            Stmt::Disable { ref name } => {
                // Enhancement-390: resolve against the enclosing named blocks.
                if !self.disable_scopes.iter().any(|n| n == name) {
                    self.diagnostics.push(BodyValidationDiagnostic::UnresolvedDisable {
                        stmt,
                        name: name.clone(),
                    });
                }
                return;
            }

            Stmt::Missing | Stmt::Empty => return,

            Stmt::Expr(e) => {
                self.validate_expr(e, stmt);
                return;
            }

            Stmt::If { cond, .. } => cond,

            Stmt::Case { kind, discr, ref case_arms } => {
                // Enhancement-78: casex/casez restrictions
                if kind != CaseKind::Case {
                    if self.infer.expr_types[discr].to_value() != Some(Type::Integer) {
                        self.diagnostics
                            .push(BodyValidationDiagnostic::NonIntegerCaseXZ { kind, discr });
                    }
                    if kind == CaseKind::CaseZ {
                        for arm in case_arms {
                            if let CaseCond::Vals(vals) = &arm.cond {
                                for (val, mask) in vals.iter().zip(&arm.masks) {
                                    if mask.had_x {
                                        self.diagnostics.push(
                                            BodyValidationDiagnostic::XDigitInCaseZ {
                                                expr: *val,
                                            },
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
                discr
            }

            Stmt::ForLoop { cond, .. }
            | Stmt::WhileLoop { cond, .. }
            | Stmt::DoWhile { cond, .. }
            | Stmt::Repeat { count: cond, .. } => {
                // Enhancement-375: reject a loop that provably cannot finish before
                // it can be emitted into a model that hangs the simulator.
                self.check_loop_termination(stmt, cond);

                // Enhancement-70: loop bodies get their own ctx so the
                // analog-operator restriction is reported against "loops"
                // (LRM 4.5.1), not "conditions".
                self.loop_depth += 1;
                self.validate_condition_in(BodyCtx::Loop, cond, stmt, |s| {
                    s.body.stmts[stmt].walk_child_stmts(|stmt| s.validate_stmt(stmt))
                });
                self.loop_depth -= 1;
                return;
            }
        };

        self.validate_condition(cond, stmt, |s| {
            s.body.stmts[stmt].walk_child_stmts(|stmt| s.validate_stmt(stmt))
        });
    }

    /// Enhancement-375: flag a loop whose controlling condition cannot change.
    ///
    /// A Verilog-A module body must finish one evaluation; a loop that cannot exit
    /// makes that impossible. The compiler used to panic on these (an `unwrap()` on
    /// a loop-exit block that was never created); after the CFG repair in
    /// Enhancement-363 it instead emitted a well-formed `.osdi` containing the
    /// infinite loop, and ngspice hung on the first device evaluation with no
    /// diagnostic. That is strictly worse than the crash, hence this check.
    ///
    /// The analysis is deliberately SOUND IN THE REJECT DIRECTION -- every bail-out
    /// below means "say nothing", so it can miss a hang but must not reject a model
    /// that terminates:
    ///
    ///   * `repeat (n)` is counted and always terminates -- exempt.
    ///   * a literal-zero condition is a zero-trip loop, not an infinite one.
    ///   * `$finish`, `$stop` and `$fatal` leave the loop (and compile today).
    ///     `disable` is handled separately -- see `collect_loop_writes`.
    ///   * a user function call may write through an OUTPUT ARGUMENT, so every name
    ///     passed to one counts as written. A user call in the CONDITION could do
    ///     the same, so that abandons the check outright.
    ///   * `$random`/`$dist_*`/`$rdist_*` return a fresh value per call, so a
    ///     condition containing one is not invariant.
    ///
    /// Names are matched SYNTACTICALLY rather than resolved to `VarId`s, which errs
    /// the safe way: a shadowing declaration in a nested block makes an unrelated
    /// name look written, which suppresses the diagnostic rather than inventing one.
    ///
    /// NOT DETECTED, and undecidable in general: a loop whose condition variables
    /// are written but never toward the exit -- notably nested loops sharing an
    /// index, where termination depends on the two bounds
    /// (`for(i=0;i<10;i=i+1) for(i=0;i<3;i=i+1)` runs forever, but the same shape
    /// with the bounds swapped terminates). Those still reach the simulator.
    fn check_loop_termination(&mut self, stmt: StmtId, cond: ExprId) {
        let (body, incr) = match self.body.stmts[stmt] {
            Stmt::WhileLoop { body, .. } | Stmt::DoWhile { body, .. } => (body, None),
            Stmt::ForLoop { body, incr, .. } => (body, Some(incr)),
            // `repeat (n)` is a counted loop: it terminates by construction.
            _ => return,
        };

        // `while (0)` never runs. It is dead code, not a hang -- not this check's
        // business, and reporting it as non-terminating would be plainly wrong.
        if let Expr::Literal(ref lit) = self.body.exprs[cond] {
            if !literal_is_truthy(lit) {
                return;
            }
        }

        let mut reads = HashSet::default();
        if !self.collect_cond_reads(cond, &mut reads) {
            return;
        }

        let mut writes = HashSet::default();
        let mut escapes = false;
        self.collect_loop_writes(body, &mut writes, &mut escapes);
        // The `for` INCREMENT counts, but the INIT must not: `for (i=0; i<10; j=j+1)`
        // never changes `i`, and folding init into the write set would hide exactly
        // the bug this check exists to find.
        if let Some(incr) = incr {
            self.collect_loop_writes(incr, &mut writes, &mut escapes);
        }
        if escapes || reads.iter().any(|name| writes.contains(name)) {
            return;
        }

        let always =
            matches!(self.body.exprs[cond], Expr::Literal(ref lit) if literal_is_truthy(lit));
        self.diagnostics.push(BodyValidationDiagnostic::NonTerminatingLoop { cond, always });
    }

    /// Names read by a loop condition. Returns `false` when the condition cannot be
    /// treated as invariant at all, in which case the caller says nothing.
    fn collect_cond_reads(&self, expr: ExprId, out: &mut HashSet<Name>) -> bool {
        match self.body.exprs[expr] {
            Expr::Path { ref path, .. } => {
                if let Some(name) = path.segments.last() {
                    out.insert(name.clone());
                }
            }
            Expr::BitSelect { ref base, .. } => {
                if let Some(name) = base.segments.last() {
                    out.insert(name.clone());
                }
            }
            Expr::Call { .. } => match self.infer.resolved_calls.get(&expr) {
                // an output argument could rewrite what the condition reads
                Some(ResolvedFun::User { .. }) => return false,
                Some(ResolvedFun::BuiltIn(builtin)) if builtin_is_impure(*builtin) => return false,
                _ => {}
            },
            _ => {}
        }

        let mut invariant = true;
        self.body.exprs[expr].walk_child_exprs(|child| {
            if !self.collect_cond_reads(child, out) {
                invariant = false;
            }
        });
        invariant
    }

    /// Names a loop body can write, plus whether it can leave the loop early.
    fn collect_loop_writes(&self, stmt: StmtId, out: &mut HashSet<Name>, escapes: &mut bool) {
        match self.body.stmts[stmt] {
            Stmt::Assignment { dst, val, .. } => {
                // Enhancement-389: a write that provably cannot change the value is
                // not progress toward the exit, so it must not count as one.
                if let Some(name) = self.root_name(dst) {
                    if !self.assignment_is_noop(dst, val) {
                        out.insert(name);
                    }
                }
            }
            // `disable <block>` (LRM 5.4) is Verilog-AMS's loop break, and it is
            // deliberately NOT treated as an escape here. It works, and keeps
            // working, for a loop that can also finish normally -- such a loop's
            // condition changes, so this check never looks at it.
            //
            // As the SOLE exit from a loop whose condition cannot change it does
            // not work today: the code after the loop is then reachable only
            // through the `disable` edge, and OSDI codegen aborts on it with
            // `unreachable!("attempted to read undefined value")`
            // (mir_llvm/src/builder.rs). Verified on the shipped binary for a
            // literal `while (1)`, a constant-folding `while (1 > 0)` and a
            // non-constant `while (i < 10)` whose `i` is never written -- 3/3
            // crash, with and without the loop result being used.
            //
            // So reporting it here cannot regress a working program: there is no
            // such program. It replaces a compiler crash with an actionable error.
            _ => {}
        }
        self.body.stmts[stmt].walk_child_exprs(|e| self.scan_call_effects(e, out, escapes));
        self.body.stmts[stmt].walk_child_stmts(|s| self.collect_loop_writes(s, out, escapes));
    }

    fn scan_call_effects(&self, expr: ExprId, out: &mut HashSet<Name>, escapes: &mut bool) {
        if let Expr::Call { ref args, .. } = self.body.exprs[expr] {
            match self.infer.resolved_calls.get(&expr) {
                Some(ResolvedFun::BuiltIn(
                    BuiltIn::finish | BuiltIn::stop | BuiltIn::fatal,
                )) => *escapes = true,
                Some(ResolvedFun::User { .. }) => {
                    // Any argument may be an output argument. Assuming they all are
                    // is the safe direction: it can only suppress the diagnostic.
                    for &arg in args {
                        if let Some(name) = self.root_name(arg) {
                            out.insert(name);
                        }
                    }
                }
                _ => {}
            }
        }
        self.body.exprs[expr].walk_child_exprs(|e| self.scan_call_effects(e, out, escapes));
    }

    /// Enhancement-389: does this assignment provably leave its destination at the
    /// value it already had?
    ///
    /// `collect_loop_writes` treats any assignment to a condition variable as
    /// progress and then says nothing. That is right for `k = k + 1` and wrong for
    /// `k = k` and `k = k + 0`, which WRITE `k` without CHANGING it: the loop runs
    /// forever, the check stays silent, and the model compiles into an `.osdi` that
    /// hangs ngspice at the operating point with no diagnostic -- the exact outcome
    /// Enhancement-375 exists to prevent, reached by a different shape.
    ///
    /// Only value-preserving forms count, and the arithmetic ones only on INTEGERS.
    /// On reals `k = k + 0.0` is not quite the identity -- it turns `-0.0` into
    /// `+0.0`, and a condition can observe that (`1.0/k < 0` flips from `-inf` to
    /// `+inf`), so a loop really can terminate because of it. Contrived, but this
    /// analysis is sound in the REJECT direction, so reals get only the exact copy
    /// `k = k`, which is a bit-for-bit move for every value including NaN.
    fn assignment_is_noop(&self, dst: ExprId, val: ExprId) -> bool {
        // `a[i] = a[i]` would additionally require proving the two indices equal.
        let name = match self.body.exprs[dst] {
            Expr::Path { ref path, .. } => match path.segments.last() {
                Some(name) => name.clone(),
                None => return false,
            },
            _ => return false,
        };
        self.expr_reproduces(val, &name)
    }

    /// Does `expr` evaluate to exactly the current value of `name`?
    fn expr_reproduces(&self, expr: ExprId, name: &Name) -> bool {
        match self.body.exprs[expr] {
            Expr::Path { .. } => self.is_var(expr, name),
            Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
                if self.infer.expr_types[expr].to_value() != Some(Type::Integer) {
                    return false;
                }
                let l = self.is_var(lhs, name);
                let r = self.is_var(rhs, name);
                match op {
                    // `k + 0`, `0 + k`
                    BinaryOp::Addition => {
                        (l && self.is_int_lit(rhs, 0)) || (r && self.is_int_lit(lhs, 0))
                    }
                    // `k - 0` only; `0 - k` negates.
                    BinaryOp::Subtraction => l && self.is_int_lit(rhs, 0),
                    // `k * 1`, `1 * k`
                    BinaryOp::Multiplication => {
                        (l && self.is_int_lit(rhs, 1)) || (r && self.is_int_lit(lhs, 1))
                    }
                    // `k / 1` only; `1 / k` does not reproduce `k`.
                    BinaryOp::Division => l && self.is_int_lit(rhs, 1),
                    _ => false,
                }
            }
            _ => false,
        }
    }

    fn is_var(&self, expr: ExprId, name: &Name) -> bool {
        matches!(self.body.exprs[expr], Expr::Path { ref path, .. }
            if path.segments.last() == Some(name))
    }

    fn is_int_lit(&self, expr: ExprId, want: i32) -> bool {
        matches!(self.body.exprs[expr], Expr::Literal(Literal::Int(val)) if val == want)
    }

    /// The variable a write lands on: `x` for `x = ...`, `a` for `a[i] = ...`.
    fn root_name(&self, expr: ExprId) -> Option<Name> {
        match self.body.exprs[expr] {
            Expr::Path { ref path, .. } => path.segments.last().cloned(),
            Expr::BitSelect { ref base, .. } => base.segments.last().cloned(),
            _ => None,
        }
    }

    fn validate_condition(
        &mut self,
        cond: ExprId,
        stmt: StmtId,
        f: impl FnOnce(&mut Self),
    ) -> Option<Box<[ExprId]>> {
        self.validate_condition_in(BodyCtx::Conditional, cond, stmt, f)
    }

    /// Like `validate_condition`, entering `enter_ctx` for the guarded body
    /// when the condition is non-constant (Enhancement-70: loops enter
    /// `BodyCtx::Loop`, ifs/cases `BodyCtx::Conditional`).
    fn validate_condition_in(
        &mut self,
        enter_ctx: BodyCtx,
        cond: ExprId,
        stmt: StmtId,
        f: impl FnOnce(&mut Self),
    ) -> Option<Box<[ExprId]>> {
        if matches!(self.ctx, BodyCtx::AnalogBlock | BodyCtx::Conditional | BodyCtx::Loop) {
            let mut non_const_access = Vec::new();
            ExprValidator {
                parent: self,
                cond_diagnostic_sink: Some(&mut non_const_access),
                write: false,
                stmt,
            }
            .validate_expr(cond);

            if !non_const_access.is_empty() {
                let non_const_dominator =
                    replace(&mut self.non_const_dominator, non_const_access.into_boxed_slice());
                let ctx = replace(&mut self.ctx, enter_ctx);
                f(self);
                self.ctx = ctx;
                return Some(replace(&mut self.non_const_dominator, non_const_dominator));
            }
        } else {
            self.validate_expr(cond, stmt);
        }

        f(self);
        None
    }

    fn validate_expr(&mut self, expr: ExprId, stmt: StmtId) {
        ExprValidator { parent: self, cond_diagnostic_sink: None, write: false, stmt }
            .validate_expr(expr)
    }

    fn validate_assignment_dst(&mut self, expr: ExprId, stmt: StmtId) {
        ExprValidator { parent: self, cond_diagnostic_sink: None, write: true, stmt }
            .validate_expr(expr)
    }
}

struct ExprValidator<'a, 'b> {
    parent: &'a mut BodyValidator<'b>,
    cond_diagnostic_sink: Option<&'a mut Vec<ExprId>>,
    write: bool,
    stmt: StmtId,
}

impl ExprValidator<'_, '_> {
    fn report_illegal_access(&mut self, kind: IllegalCtxAccessKind, expr: ExprId) {
        // `ctx` only reaches `BodyCtx::Loop` when the loop's controlling
        // expression is non-constant, so a `repeat (3)` reported via `loop_depth`
        // would otherwise be described as being in an "analog block" -- naming the
        // wrong construct and omitting the loop rule the user needs. Report the
        // context the check actually used.
        let ctx = if self.parent.loop_depth != 0 && self.parent.ctx.allow_analog_operator() {
            BodyCtx::Loop
        } else {
            self.parent.ctx
        };
        let err = IllegalCtxAccess { kind, ctx, expr };
        self.report(BodyValidationDiagnostic::IllegalCtxAccess(err));
    }

    fn check_access(
        &mut self,
        kind: impl FnOnce(&Self) -> IllegalCtxAccessKind,
        expr: ExprId,
        allowed: bool,
    ) {
        if let Some(sink) = &mut self.cond_diagnostic_sink {
            sink.push(expr)
        }

        if !allowed {
            self.report_illegal_access(kind(self), expr)
        }
    }

    fn report(&mut self, diagnostic: BodyValidationDiagnostic) {
        self.parent.diagnostics.push(diagnostic)
    }

    fn report_illegal_nature_access(
        &mut self,
        branch: String,
        discipline: DisciplineId,
        access_nature: Option<NatureId>,
        access_expr: ExprId,
    ) {
        let db = self.parent.db;
        let discipline = db.discipline_info(discipline);

        let nature_info = |nature: NatureId| {
            let nature = nature.lookup(db.upcast());
            let nature = &nature.item_tree(db.upcast())[nature.id];
            Some((nature.name.clone(), nature.access.clone()?.0))
        };
        let pot = discipline.potential.and_then(nature_info);
        let flow = discipline.flow.and_then(nature_info);
        self.parent.diagnostics.push(BodyValidationDiagnostic::IncompatibleNatureAccess {
            candidates: [pot, flow],
            access_nature,
            access_expr,
            branch,
        })
    }

    fn validate_implicit_branch(
        &mut self,
        expr: ExprId,
        node1: NodeId,
        node2: NodeId,
    ) -> Option<DisciplineId> {
        if let Some(discipline1) = self.parent.db.node_discipline(node1) {
            if let Some(discipline2) = self.parent.db.node_discipline(node2) {
                let discipline2 = self.parent.db.discipline_info(discipline2);
                if !discipline2.compatible(discipline1, self.parent.db) {
                    self.report(BodyValidationDiagnostic::IncompatibleImplicitBranch {
                        access: expr,
                        node1,
                        node2,
                    });
                } else {
                    return Some(discipline1);
                }
            }
        }

        None
    }

    fn lint_trivial_branch(&mut self, branch: BranchWrite, call: BuiltIn, expr: ExprId) {
        let is_flow = call == BuiltIn::flow;
        if self.write {
            self.parent.non_trivial_branches.insert(branch);
            self.parent.trivial_probes.remove(&branch);
        } else if is_flow && !self.parent.non_trivial_branches.contains(&branch) {
            self.parent.trivial_probes.entry(branch).or_default().push((self.stmt, expr))
        }
    }

    fn validate_flow_or_pot(&mut self, expr: ExprId, call: BuiltIn, discipline: DisciplineId) {
        let is_pot = call == BuiltIn::potential;
        let discipline_ = self.parent.db.discipline_info(discipline);
        if discipline_.potential.is_none() && is_pot || discipline_.flow.is_none() && !is_pot {
            self.report(BodyValidationDiagnostic::IllegalNatureAccess { is_pot, access_expr: expr })
        }
    }

    fn validate_nature_access(
        &mut self,
        access_nature: NatureId,
        access_expr: ExprId,
        args: &[ExprId],
    ) {
        match self.parent.infer.resolved_signatures.get(&access_expr).copied() {
            Some(NATURE_ACCESS_BRANCH) => {
                let branch = match self.parent.infer.expr_types[args[0]] { Ty::Branch(id) => id, _ => return };
                if let Some(branch_info) = self.parent.db.branch_info(branch) {
                    self.report_illegal_nature_access(
                        self.parent.db.branch_data(branch).name.to_string(),
                        branch_info.discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }

            Some(NATURE_ACCESS_NODE_GND) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    let node = self.parent.db.node_data(node);
                    self.report_illegal_nature_access(
                        format!("({})", node.name),
                        discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }

            Some(NATURE_ACCESS_NODES) => {
                let node1 = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let node2 = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                if let Some(discipline1) = self.parent.db.node_discipline(node1) {
                    if let Some(discipline2) = self.parent.db.node_discipline(node2) {
                        let discipline2 = self.parent.db.discipline_info(discipline2);
                        if discipline2.compatible(discipline1, self.parent.db) {
                            let node1 = self.parent.db.node_data(node1);
                            let node2 = self.parent.db.node_data(node2);
                            self.report_illegal_nature_access(
                                format!("({}, {})", node1.name, node2.name),
                                discipline1,
                                Some(access_nature),
                                access_expr,
                            )
                        } else {
                            self.report(BodyValidationDiagnostic::IncompatibleImplicitBranch {
                                access: access_expr,
                                node1,
                                node2,
                            })
                        }
                    }
                }
            }

            Some(NATURE_ACCESS_PORT_FLOW) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::PortFlow(id) => id, _ => return };
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    let node = self.parent.db.node_data(node);
                    self.report_illegal_nature_access(
                        format!("(<{}>)", node.name),
                        discipline,
                        Some(access_nature),
                        access_expr,
                    )
                }
            }
            Some(_) => unreachable!(),
            None => (),
        };
    }

    fn validate_expr(&mut self, expr: ExprId) {
        match self.parent.body.exprs[expr] {
            Expr::Call { ref fun, ref args, .. } => {
                match self.parent.infer.resolved_calls.get(&expr) {
                    Some(ResolvedFun::BuiltIn(builtin)) => {
                        // Enhancement-390: flag every `$table_model` data FILE. Whether
                        // it is usable is decided when the report is built, where the
                        // root file and the VFS are available; a usable one reports
                        // nothing.
                        // Enhancement-392: a runtime table larger than the emitted
                        // sorting network can handle is reported, not silently left
                        // unsorted.
                        if *builtin == BuiltIn::table_model && args.len() >= 3 {
                            if let Some(elems) =
                                self.parent.infer.array_var_refs.get(&args[1])
                            {
                                let max = hir_lower_max_runtime_table();
                                if elems.len() > max {
                                    self.parent.diagnostics.push(
                                        BodyValidationDiagnostic::TableTooLargeToSort {
                                            expr: args[1],
                                            len: elems.len(),
                                            max,
                                        },
                                    );
                                }
                            }
                        }
                        if *builtin == BuiltIn::table_model && args.len() >= 2 {
                            // Enhancement-399: a concatenation is neither an array
                            // literal nor an array-variable reference, so it fell
                            // through `inline` below to the file branch, found no
                            // string literal to complain about, and returned 0.0
                            // from an empty table.
                            self.require_array_arg("$table_model", "the table data", args[1]);
                            // Mirror `lower_table_model`'s own rule for WHICH argument
                            // is the data file. Inline data -- an array literal or a
                            // bare array-variable reference (Enhancement-389) -- means
                            // there is no file at all, and the only string literal is
                            // then the CONTROL STRING. Treating that as a filename
                            // would reject every inline table for failing to open a
                            // file named "1L".
                            let inline = matches!(
                                self.parent.body.exprs[args[1]],
                                Expr::Array(_)
                            ) || self.parent.infer.array_var_refs.contains_key(&args[1]);
                            if !inline {
                                for (i, &arg) in args[1..].iter().enumerate() {
                                    if let Expr::Literal(Literal::String(ref path)) =
                                        self.parent.body.exprs[arg]
                                    {
                                        // Enhancement-425: the data file is preceded by
                                        // `1 + i` input arguments, which IS the call's
                                        // dimensionality -- the same quantity
                                        // `lower_table_model` derives from the index of
                                        // the first string literal. Carry it so the file
                                        // check can apply the right grammar.
                                        self.parent.diagnostics.push(
                                            BodyValidationDiagnostic::TableFileUnusable {
                                                expr: arg,
                                                path: path.clone(),
                                                ndim: i + 1,
                                            },
                                        );
                                        break;
                                    }
                                }
                            }
                            // Enhancement-395: validate the control string. It is
                            // the LAST string literal argument for inline data, and
                            // the one AFTER the file otherwise -- the same rule
                            // lowering uses to pick it.
                            let ctrl_arg = if inline {
                                args[2..].iter().rev().copied().find(|&a| {
                                    matches!(
                                        self.parent.body.exprs[a],
                                        Expr::Literal(Literal::String(_))
                                    )
                                })
                            } else {
                                let mut it = args[1..].iter().copied().filter(|&a| {
                                    matches!(
                                        self.parent.body.exprs[a],
                                        Expr::Literal(Literal::String(_))
                                    )
                                });
                                it.next();
                                it.next()
                            };
                            if let Some(carg) = ctrl_arg {
                                if let Expr::Literal(Literal::String(ref ctrl)) =
                                    self.parent.body.exprs[carg]
                                {
                                    if let Some(why) = table_ctrl_problem(ctrl) {
                                        self.parent.diagnostics.push(
                                            BodyValidationDiagnostic::TableControlUnsupported {
                                                expr: carg,
                                                code: ctrl.clone(),
                                                why: why.into(),
                                            },
                                        );
                                    }
                                }
                            }
                        }
                        let signature = self.parent.infer.resolved_signatures.get(&expr);
                        self.validate_builtin(fun, expr, args, *builtin, signature.cloned());
                        return;
                    }
                    Some(ResolvedFun::InvalidNatureAccess(nature)) => {
                        self.validate_nature_access(*nature, expr, args);
                        return;
                    }
                    _ => (),
                }
            }

            Expr::Select { cond, then_val, else_val } => {
                if let Some(non_const_dominators) =
                    self.parent.validate_condition(cond, self.stmt, |s| {
                        let mut validator = ExprValidator {
                            parent: s,
                            cond_diagnostic_sink: self.cond_diagnostic_sink.as_deref_mut(),
                            write: false,
                            stmt: self.stmt,
                        };
                        validator.validate_expr(then_val);
                        validator.validate_expr(else_val);
                    })
                {
                    if let Some(sink) = &mut self.cond_diagnostic_sink {
                        sink.extend(non_const_dominators.to_vec())
                    }
                }
                // Robustness fix: the arm above already validates cond, then_val and
                // else_val (via validate_condition). Falling through to the generic
                // walk_child_exprs below would validate then_val/else_val a SECOND
                // time, so a chain of N nested ternaries was validated 2^N times --
                // an exponential-time hang. Return like the Call / Path arms do.
                return;
            }

            // Enhancement-489: `x ** y` is `pow(x, y)` written as an operator, and it
            // reaches code generation by a different path -- `BinaryOp::Power`, not
            // `BuiltIn::pow` -- so the guard added to the call form above does not see
            // it. Judging only one spelling of the same operation is how the two
            // drift apart, so both are judged here on the same rule.
            Expr::BinaryOp { lhs, rhs, op: Some(BinaryOp::Power) } => {
                // ...but ONLY for the REAL operation. Enhancement-420 implements an
                // INTEGER `**` per IEEE 1364-2005 Table 5-6, where a negative exponent
                // is fully defined -- `2 ** -1` is 0, `-1 ** -3` is -1 -- and a base of
                // 0 is `'x`, which is 0 in an integer context. Those are correct
                // answers, not NaNs, and vafdegen_examples asserts every one of them.
                // Judging them by the real domain rule rejected valid models; the first
                // version of this arm did exactly that and E-420's suite caught it.
                if self.parent.infer.expr_types[expr].to_value() == Some(Type::Integer) {
                    return;
                }
                if let (Some(base), Some(exp)) = (self.const_num(lhs), self.const_num(rhs)) {
                    if base < 0.0 && exp.fract() != 0.0 {
                        self.bad_arg(
                            "**",
                            "the base",
                            format!(
                                "is {base} with the fractional exponent {exp}, which is \
                                 outside the domain of ** (a negative base needs an \
                                 integer exponent); the result would be NaN"
                            ),
                            lhs,
                        )
                    } else if base == 0.0 && exp < 0.0 {
                        self.bad_arg(
                            "**",
                            "the base",
                            format!(
                                "is 0 with the negative exponent {exp}, which is outside \
                                 the domain of **; the result would be infinite"
                            ),
                            lhs,
                        )
                    }
                }
            }

            Expr::Path { port: false, .. } => {
                match self.parent.infer.expr_types[expr] {
                    Ty::FunctionVar { arg: Some(arg), fun, .. } => {
                        let is_output = self.parent.db.function_data(fun).args[arg].is_output;
                        if self.write && !is_output {
                            self.report(BodyValidationDiagnostic::WriteToInputArg {
                                expr,
                                arg: FunctionArgLoc { fun, id: arg },
                            })
                        }
                    }

                    Ty::Var(_, var) => {
                        self.check_access(
                            |__| IllegalCtxAccessKind::Var(var),
                            expr,
                            self.parent.ctx.allow_var_ref(),
                        );
                    }
                    Ty::Param(_, param) => {
                        if let DefWithBodyId::ParamId(def) = self.parent.owner {
                            // Enhancement-414: the same declaration -- a self-reference.
                            if def == param {
                                self.report(BodyValidationDiagnostic::SelfReferentialParam {
                                    def,
                                    expr,
                                })
                            } else if def.lookup(self.parent.db.upcast()).id
                                < param.lookup(self.parent.db.upcast()).id
                            {
                                self.report(BodyValidationDiagnostic::IllegalParamAccess {
                                    def,
                                    expr,
                                    param,
                                })
                            }
                        }
                    }
                    _ => (),
                };
                return;
            }

            _ => (),
        }

        self.parent.body.exprs[expr].walk_child_exprs(|child| self.validate_expr(child))
    }

    fn validate_builtin(
        &mut self,
        name: &Option<Path>,
        expr: ExprId,
        mut args: &[ExprId],
        call: BuiltIn,
        signature: Option<Signature>,
    ) {
        // Enhancement-220: the arms below index args[0..2] on the assumption that
        // the call has as many arguments as the builtin requires. A call with too
        // few arguments (e.g. `$simparam()`, `$port_connected()`) would index out
        // of bounds and crash the compiler. Inference already reports the
        // ArgCntMismatch for such a call (resolve_function_args), so skip the
        // builtin-specific validation rather than panic.
        if args.len() < BuiltinInfo::from(call).min_args {
            return;
        }
        match call {
            _ if call.is_unsupported() => self
                .parent
                .diagnostics
                .push(BodyValidationDiagnostic::UnsupportedFunction { expr, func: call }),
            BuiltIn::potential | BuiltIn::flow => self.check_access(
                |_| IllegalCtxAccessKind::NatureAccess,
                expr,
                self.parent.ctx.allow_nature_access(),
            ),

            // Enhancement-330: `ddx` is exempt from the general analog-operator
            // context restriction below -- it is symbolic and stateless, and the
            // industry CMC corpus uses it inside `if` in 192 places, so that
            // exemption must stay. It is NOT valid inside a runtime loop: a back
            // edge lets the differentiated expression depend on the ddx result
            // itself, so `live_derivative_fixpoint` requests a new derivative one
            // order higher every round -- it grows the very lattice it iterates
            // over, so it has no fixed point and the compiler HANGS forever
            // (confirmed: 99.8% of samples in raise_order_with, RSS climbing, no
            // termination at 15 min). Every other analog operator is already
            // rejected here; `ddx` was the lone hole.
            //
            // The same `loop_depth` test now covers EVERY analog operator, not just
            // `ddx`. The generic arm below asks `ctx.allow_analog_operator()`, and
            // `ctx` only becomes `BodyCtx::Loop` when the loop's controlling
            // expression is NON-CONSTANT -- so `repeat (3)` (or any loop with a
            // constant bound) slipped past it. `ddt` inside such a loop compiled
            // silently and produced the WRONG CHARGE, where the identical `for`
            // and `while` spellings were correctly rejected. `loop_depth` counts
            // every loop form, so the diagnostic no longer depends on whether the
            // trip count happens to be a literal.
            // Enhancement-395: the RNG builtins are PURE functions of
            // (seed, salt) with no persistent state -- Enhancement-10 made them
            // so deliberately, because a seed that advances in place, as the LRM
            // nominally prescribes, changes on every model evaluation and breaks
            // DC/transient convergence (measured: a carried seed with a
            // meaningful spread fails gmin stepping, source stepping and the
            // transient op outright). `salt` is the call's ExprId, so it is
            // constant per CALL SITE -- which means a loop executing one call
            // site N times draws the SAME number N times, and a Monte-Carlo
            // model written the obvious way has exactly one sample of variation
            // in it. That cannot be fixed by advancing the seed without
            // reintroducing the convergence failure, so it is reported instead
            // of being silent. A lint, not a hard error: the code is well
            // formed and a model that does not care can allow it.
            _ if call.is_rng() && self.parent.loop_depth != 0 => {
                if let Some(name) = name.as_ref().and_then(|p| p.as_ident()) {
                    self.parent.diagnostics.push(BodyValidationDiagnostic::RngInLoop {
                        name: name.to_string().into_boxed_str(),
                        expr,
                        stmt: self.stmt,
                    });
                }
            }

            // Enhancement-424: a noise source contributed inside a run-time loop
            // registered NO SOURCE AT ALL and contributed exactly nothing --
            // `onoise_total` came back bit-identical to a model with no noise in
            // it, and nothing was said, not even under `-E all`. `ac_stim` rides
            // the same pipeline (Enhancement-51) and vanished the same way: 500
            // to 0.
            //
            // Every OTHER member of this family was already rejected here --
            // `ddt`, `idt`, `absdelay`, `transition`, `laplace_*` all report
            // "analog operator 'X' is not allowed in loops". The noise builtins
            // are not in `is_analog_operator()`, so they fell past this arm and
            // were dropped further down instead. Rejecting them is what the
            // evidence supports: the sibling behaviour is already an error, and
            // the LRM restriction (4.5.1) is the same one.
            //
            // A genvar loop is unrolled before this runs and keeps working --
            // it creates one source per iteration, which is what a model that
            // wants per-finger noise should write.
            _ if call.is_small_signal_source() && self.parent.loop_depth != 0 => {
                if let Some(name) = name.as_ref().and_then(|p| p.as_ident()) {
                    self.report_illegal_access(
                        IllegalCtxAccessKind::SmallSignalSourceInLoop { name },
                        expr,
                    )
                }
            }

            _ if (call.is_analog_operator() || call.is_analog_operator_sysfun())
                && self.parent.loop_depth != 0 =>
            {
                self.report_illegal_access(
                    IllegalCtxAccessKind::AnalogOperator {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                        is_standard: call.is_analog_operator(),
                        non_const_dominator: self.parent.non_const_dominator.clone(),
                    },
                    expr,
                )
            }

            _ if call.is_analog_operator() && call != BuiltIn::ddx
                || call.is_analog_operator_sysfun() =>
            {
                // let non_const_dominator = if self.cond_diagnostic_sink.is_none() {
                // self.parent.non_const_dominator.clone()
                // } else {
                // vec![].into_boxed_slice()
                // };

                self.check_access(
                    |sel| IllegalCtxAccessKind::AnalogOperator {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                        is_standard: call.is_analog_operator(),
                        non_const_dominator: sel.parent.non_const_dominator.clone(),
                    },
                    expr,
                    self.parent.ctx.allow_analog_operator(),
                )
            }

            _ if call.is_analysis_var() && !self.parent.ctx.allow_analysis_fun() => self
                .report_illegal_access(
                    IllegalCtxAccessKind::AnalysisFun {
                        name: name.as_ref().and_then(|p| p.as_ident()).unwrap(),
                    },
                    expr,
                ),
            _ => (),
        }

        match (call, signature) {
            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_NODES)) => {
                let hi = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let lo = match self.parent.infer.expr_types[args[1]] { Ty::Node(id) => id, _ => return };
                // Enhancement-97: contributing to a branch whose endpoints are
                // both `ground` (e.g. `V(gnd, gnd) <+ ...`) has no unknown to
                // stamp and used to panic during lowering.
                if self.write
                    && self.parent.db.node_data(hi).is_gnd
                    && self.parent.db.node_data(lo).is_gnd
                {
                    self.report(BodyValidationDiagnostic::ContributeToGround { expr });
                    return;
                }
                let branch = if hi >= lo {
                    BranchWrite::Unnamed { hi, lo: Some(lo) }
                } else {
                    BranchWrite::Unnamed { hi: lo, lo: Some(hi) }
                };
                self.lint_trivial_branch(branch, call, expr);
                if let Some(discipline) = self.validate_implicit_branch(expr, hi, lo) {
                    self.validate_flow_or_pot(expr, call, discipline)
                }
            }

            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_NODE_GND)) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                // Enhancement-97: `V(gnd) <+ ...` -- the single node is the
                // ground reference, so the implicit node-to-ground branch is
                // ground-to-ground (no unknown; used to panic during lowering).
                if self.write && self.parent.db.node_data(node).is_gnd {
                    self.report(BodyValidationDiagnostic::ContributeToGround { expr });
                    return;
                }
                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    self.lint_trivial_branch(
                        BranchWrite::Unnamed { hi: node, lo: None },
                        call,
                        expr,
                    );
                    self.validate_flow_or_pot(expr, call, discipline)
                }
            }

            (BuiltIn::flow, Some(NATURE_ACCESS_PORT_FLOW)) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::PortFlow(id) => id, _ => return };
                let node_data = self.parent.db.node_data(node);
                if !(node_data.is_input | node_data.is_output) {
                    self.report(BodyValidationDiagnostic::ExpectedPort { node, expr })
                }

                if let Some(discipline) = self.parent.db.node_discipline(node) {
                    self.validate_flow_or_pot(expr, BuiltIn::flow, discipline)
                }
            }

            (BuiltIn::potential, Some(NATURE_ACCESS_PORT_FLOW)) => {
                self.report(BodyValidationDiagnostic::PotentialOfPortFlow { expr, branch: None })
            }

            (BuiltIn::potential | BuiltIn::flow, Some(NATURE_ACCESS_BRANCH)) => {
                let branch = match self.parent.infer.expr_types[args[0]] { Ty::Branch(id) => id, _ => return };

                if let Some(branch_info) = self.parent.db.branch_info(branch) {
                    match branch_info.kind {
                        BranchKind::PortFlow(_) => {
                            if call == BuiltIn::potential {
                                self.report(BodyValidationDiagnostic::PotentialOfPortFlow {
                                    expr,
                                    branch: Some(branch),
                                })
                            } else if self.write {
                                // Port branches are probe-only (LRM 5.4.3.1): the port
                                // flow is defined by the connected network, so
                                // contributing to it is illegal (and used to panic in
                                // BranchWrite::nodes during lowering).
                                self.report(BodyValidationDiagnostic::ContributeToPortFlow {
                                    expr,
                                    branch,
                                })
                            } else {
                                self.validate_flow_or_pot(
                                    expr,
                                    BuiltIn::flow,
                                    branch_info.discipline,
                                )
                            }
                        }
                        BranchKind::NodeGnd(node) => {
                            self.lint_trivial_branch(
                                BranchWrite::Unnamed { hi: node, lo: None },
                                call,
                                expr,
                            );
                            self.validate_flow_or_pot(expr, call, branch_info.discipline)
                        }
                        BranchKind::Nodes(hi, lo) => {
                            let branch = if hi >= lo {
                                BranchWrite::Unnamed { hi, lo: Some(lo) }
                            } else {
                                BranchWrite::Unnamed { hi: lo, lo: Some(hi) }
                            };
                            self.lint_trivial_branch(branch, call, expr);
                            self.validate_flow_or_pot(expr, call, branch_info.discipline)
                        }
                    }
                }
            }

            (BuiltIn::port_connected, _) => {
                let node = match self.parent.infer.expr_types[args[0]] { Ty::Node(id) => id, _ => return };
                let node_data = self.parent.db.node_data(node);
                if !(node_data.is_input | node_data.is_output) {
                    self.report(BodyValidationDiagnostic::ExpectedPort { node, expr })
                }
            }

            // Enhancement-414: the FILE form of the same builtin -- see
            // `NoiseTableFileUnusable`. Whether the file is usable is decided when the
            // report is built, which is the first point holding the root file and VFS.
            (
                BuiltIn::noise_table | BuiltIn::noise_table_log,
                Some(NOISE_TABLE_FILE | NOISE_TABLE_FILE_NAME),
            ) => {
                if let Expr::Literal(Literal::String(ref path)) = self.parent.body.exprs[args[0]] {
                    let path = path.clone();
                    // Enhancement-506: `log` selects the VALUE rule applied to the
                    // file's entries -- see `noise_table_file_bad_value`. The file
                    // form was checked for STRUCTURE only.
                    self.report(BodyValidationDiagnostic::NoiseTableFileUnusable {
                        expr: args[0],
                        path,
                        log: call == BuiltIn::noise_table_log,
                    });
                }
            }

            // Enhancement-414: a negative noise POWER is not a noise power. It reached
            // the runtime and produced exactly the spectrum of its positive twin, so the
            // sign was discarded in silence. `noise_table`'s inline entries have been
            // checked since Enhancement-396; these two were not checked at all.
            // Enhancement-455: a CONSTANT argument outside the function's domain.
            //
            // `sqrt(-1.0)`, `ln(-1.0)`, `asin(2.0)` and friends folded to NaN with
            // no diagnostic at all, and the model then failed at simulation with
            // "Transient op failed, timestep too small" -- a convergence message
            // for a NaN written literally in the source. Integer `1/0` and `5 % 0`
            // have always been compile errors; the same mistake in a real-valued
            // call said nothing.
            //
            // Only CONSTANT arguments are judged, exactly as for the guards above:
            // a run-time value going out of domain is the model's own business,
            // and a parameter may be overridden.
            (
                BuiltIn::sqrt
                | BuiltIn::ln
                | BuiltIn::log
                | BuiltIn::asin
                | BuiltIn::acos
                | BuiltIn::acosh
                | BuiltIn::atanh,
                _,
            ) if !args.is_empty() => {
                if let Some(v) = self.const_num(args[0]) {
                    let (name, ok, domain) = match call {
                        BuiltIn::sqrt => ("sqrt", v >= 0.0, "values >= 0"),
                        BuiltIn::ln => ("ln", v > 0.0, "values > 0"),
                        BuiltIn::log => ("log", v > 0.0, "values > 0"),
                        BuiltIn::asin => ("asin", (-1.0..=1.0).contains(&v), "values in [-1, 1]"),
                        BuiltIn::acos => ("acos", (-1.0..=1.0).contains(&v), "values in [-1, 1]"),
                        BuiltIn::acosh => ("acosh", v >= 1.0, "values >= 1"),
                        _ => ("atanh", (-1.0..1.0).contains(&v.abs()), "values in (-1, 1)"),
                    };
                    if !ok {
                        self.bad_arg(
                            name,
                            "the argument",
                            format!(
                                "is {v}, which is outside the domain of {name} ({domain}); \
                                 the result would be NaN"
                            ),
                            args[0],
                        )
                    }
                }
            }

            // Enhancement-489: `pow(x,y)` and its `**` spelling are the one member of
            // the family above that the guard left out, and they are the SAME mistake:
            // pow(-2.0, 0.5) IS sqrt(-2.0). Measured before the fix, it compiled clean
            // and the model then failed at simulation with
            //     "Error: Transient op failed, timestep too small"
            // which is exactly the outcome Enhancement-455's comment above cites as the
            // reason that guard exists -- a convergence message for a NaN written
            // literally in the source.
            //
            // Two constant shapes have no value. A negative base with a fractional
            // exponent is NaN (there is no real root). A zero base with a negative
            // exponent is a division by zero and is infinite. Both are judged only when
            // BOTH arguments are constant, exactly as the unary domains are judged: a
            // run-time value is the model's own business and a parameter may be
            // overridden.
            (BuiltIn::pow, _) if args.len() >= 2 => {
                if let (Some(base), Some(exp)) =
                    (self.const_num(args[0]), self.const_num(args[1]))
                {
                    if base < 0.0 && exp.fract() != 0.0 {
                        self.bad_arg(
                            "pow",
                            "the base",
                            format!(
                                "is {base} with the fractional exponent {exp}, which is \
                                 outside the domain of pow (a negative base needs an \
                                 integer exponent); the result would be NaN"
                            ),
                            args[0],
                        )
                    } else if base == 0.0 && exp < 0.0 {
                        self.bad_arg(
                            "pow",
                            "the base",
                            format!(
                                "is 0 with the negative exponent {exp}, which is outside \
                                 the domain of pow; the result would be infinite"
                            ),
                            args[0],
                        )
                    }
                }
            }

            // Enhancement-455: LRM 9.13.2 -- "In $rdist_uniform, the start and end
            // arguments are real inputs which bound the values returned. The start
            // value shall be smaller than the end value." Reversed bounds were
            // accepted and returned exactly what the correct ordering returns, so
            // the mistake produced plausible numbers and said nothing.
            (BuiltIn::rdist_uniform | BuiltIn::dist_uniform, _) if args.len() >= 3 => {
                if let (Some(start), Some(end)) =
                    (self.const_num(args[1]), self.const_num(args[2]))
                {
                    if start >= end {
                        self.bad_arg(
                            rng_builtin_name(call),
                            "the bounds",
                            format!(
                                "must have the start below the end, but the start is \
                                 {start} and the end is {end}"
                            ),
                            args[1],
                        )
                    }
                }
            }

            // Enhancement-506: these arms serve BOTH families -- one arm matches
            // `rdist_normal | dist_normal` -- and the name was hardcoded to the
            // `$rdist_*` spelling, so a `$dist_normal(s, 0, -1)` call was reported
            // as "$rdist_normal: the standard deviation must not be negative".
            // The author greps their source for the function the compiler named
            // and does not find it. Exactly the defect Enhancement-396 fixed for
            // `noise_table_log` in the `noise_table` arm below.
            //
            // LRM 9.13.2 gives every distribution in this family a shape
            // argument that "shall be positive". Only `$rdist_uniform` above was
            // ever checked, so the other six accepted a degenerate shape and
            // returned a plausible finite number from a distribution that cannot
            // exist -- `$rdist_exponential(s, -1.0)` handed back -1.735, a
            // NEGATIVE sample from a distribution whose support is [0, inf).
            // Nothing was reported at compile time or at run time.
            (BuiltIn::rdist_normal | BuiltIn::dist_normal, _) if args.len() >= 3 => {
                // The mean is unconstrained; only the spread has to be real.
                self.require_non_negative(rng_builtin_name(call), "the standard deviation", args[2]);
            }
            (BuiltIn::rdist_exponential | BuiltIn::dist_exponential, _) if args.len() >= 2 => {
                self.require_positive(rng_builtin_name(call), "the mean", args[1]);
            }
            (BuiltIn::rdist_poisson | BuiltIn::dist_poisson, _) if args.len() >= 2 => {
                self.require_positive(rng_builtin_name(call), "the mean", args[1]);
            }
            (BuiltIn::rdist_chi_square | BuiltIn::dist_chi_square, _) if args.len() >= 2 => {
                self.require_positive(rng_builtin_name(call), "the degrees of freedom", args[1]);
            }
            (BuiltIn::rdist_t | BuiltIn::dist_t, _) if args.len() >= 2 => {
                self.require_positive(rng_builtin_name(call), "the degrees of freedom", args[1]);
            }
            (BuiltIn::rdist_erlang | BuiltIn::dist_erlang, _) if args.len() >= 3 => {
                self.require_positive(rng_builtin_name(call), "the k stage", args[1]);
                self.require_positive(rng_builtin_name(call), "the mean", args[2]);
            }

            // `$vt(T)` is kT/q at the ABSOLUTE temperature T, so T must be above
            // absolute zero. `$vt(-300)` returned a negative thermal voltage --
            // every current built on it came out sign-flipped -- and `$vt(0)` put
            // a NaN straight into the solution, which the simulator then printed
            // as a converged answer. The sibling constraint was already enforced
            // for a `nature`'s `abstol`.
            (BuiltIn::vt, _) if args.len() >= 1 => {
                self.require_positive("$vt", "the absolute temperature", args[0]);
            }

            (BuiltIn::white_noise, _) => {
                self.require_non_negative("white_noise", "the noise power", args[0]);
            }
            (BuiltIn::flicker_noise, _) => {
                self.require_non_negative("flicker_noise", "the noise power", args[0]);
            }

            (
                BuiltIn::noise_table | BuiltIn::noise_table_log,
                Some(NOISE_TABLE_INLINE | NOISE_TABLE_INLINE_NAME),
            ) => {
                // Enhancement-396: the inline form is a flat list of
                // (frequency, power) PAIRS. An odd length silently dropped the
                // unpaired entry, and an empty or single-entry array made the
                // device contribute NO NOISE AT ALL -- a spec that looks present
                // and is not. A negative power is not a noise power at all: it
                // reached the runtime and produced the same spectrum as its
                // positive twin, so the sign was quietly discarded.
                // `noise_table_log` shares this arm, and the name was hardcoded, so
                // a `noise_table_log` call was reported as "noise_table:" -- pointing
                // the author at a function their source does not mention.
                let name = if call == BuiltIn::noise_table_log {
                    "noise_table_log"
                } else {
                    "noise_table"
                };
                // Enhancement-399: a concatenation here skipped every check below
                // and produced a device that contributed no noise at all.
                self.require_array_arg(name, "the table", args[0]);
                // LRM 4.5.1 allows an array IDENTIFIER for this argument, but the
                // table here is materialised at COMPILE time (`noise_table_data`
                // reads the literal elements or the data file), and a parameter or
                // variable array only has values at run time. Accepting one would
                // hand the builtin an EMPTY table -- exactly the silent
                // no-noise-at-all failure Enhancement-399 fixed for `{...}` -- so it
                // is refused, and refused with the reason rather than with the
                // "requires a bit-select [i]" that a bare array reference otherwise
                // collects from the generic argument path.
                if self.is_bare_array_ref_expr(args[0]) {
                    self.bad_arg(name, "the table",
                        "is an array parameter or variable, whose values are only \
                         known at run time; this table is built when the model is \
                         compiled, so it must be an array literal `'{...}` or a data \
                         file name".to_owned(), args[0]);
                }
                if let Expr::Array(ref elems) = self.parent.body.exprs[args[0]] {
                    let elems = elems.clone();
                    if elems.is_empty() {
                        self.bad_arg(name, "table", "is empty, so the device would \
                            contribute no noise at all".to_owned(), args[0]);
                    } else if elems.len() % 2 != 0 {
                        self.bad_arg(name, "table", format!(
                            "has {} entr{}; it must hold (frequency, power) PAIRS, \
                             so the count must be even", elems.len(),
                            if elems.len() == 1 { "y" } else { "ies" }), args[0]);
                    } else {
                        // Enhancement-506: `noise_table_log` interpolates in
                        // log-log space, so ZERO is as unrepresentable as a
                        // negative -- log10(0) is -inf and the whole spectrum came
                        // back NaN, at every frequency, with exit code 0 and no
                        // diagnostic. Both variants shared `require_non_negative`,
                        // which admits exactly the one value the log variant
                        // cannot take. Plain `noise_table` interpolates linearly
                        // and a zero entry is fine there, so only the log form is
                        // tightened; 1e-300 is accepted by both, which is what
                        // makes this a guard about zero and not about smallness.
                        let log = call == BuiltIn::noise_table_log;
                        for (i, &e) in elems.iter().enumerate() {
                            let what = if i % 2 == 0 { "frequency" } else { "noise power" };
                            if log {
                                self.require_positive(name, what, e);
                            } else {
                                self.require_non_negative(name, what, e);
                            }
                        }
                    }
                }
                self.validate_const_expr(args[0])
            }
            // Enhancement-399: an analysis name is matched by string against a
            // fixed set (osdi/stdlib.c `analysis()`); anything else is false in
            // every analysis, so `analysis("tarn")` silently disables the branch
            // it guards. Reported as a lint, not an error, because the set is
            // simulator-defined and another OSDI consumer may match more.
            (BuiltIn::analysis, _) => {
                for &arg in args {
                    self.check_analysis_name("analysis()", arg);
                }
            }

            (func @ (BuiltIn::simparam | BuiltIn::simparam_str), _) => {
                // Enhancement-421: check the NAME, which nothing did.
                //
                // `$simparam` is the third of a family and was the only one left
                // unchecked -- `analysis("nosuch")` warns (L021, E-399),
                // `$limit(.., "nosuchlim", ..)` warns (L020, E-396), `ac_stim("nosuch")`
                // warns (L021, E-420). It is also the only one whose bad name is
                // FATAL: `simparam`/`simparam_str` in osdi/stdlib.c set
                // EVAL_RET_FLAG_FATAL and the analysis dies, where the other three
                // merely go quiet. The severity ordering was exactly inverted.
                //
                // `$simparam(name, default)` is the non-fatal form and is left
                // alone -- returning the default for a name this simulator does
                // not serve is precisely what it is for, and is how a model stays
                // portable across simulators. `$simparam$str` has no such form
                // (SIMPARAM_STR is a single one-argument signature), so every
                // unresolvable name there is fatal.
                let has_default_form = func == BuiltIn::simparam;
                let checkable = !has_default_form || signature == Some(SIMPARAM_NO_DEFAULT);
                if checkable {
                    if let Some(&arg) = args.first() {
                        self.check_simparam_name(
                            if has_default_form { "$simparam" } else { "$simparam$str" },
                            has_default_form,
                            arg,
                        );
                    }
                }
                if self.parent.ctx == BodyCtx::Const {
                    let known = if let Expr::Literal(Literal::String(name)) =
                        &self.parent.body.exprs[args[0]]
                    {
                        matches!(
                            (func, &**name),
                            (
                                BuiltIn::simparam,
                                "minr"
                                    | "imelt"
                                    | "shrink"
                                    | "imax"
                                    | "rthresh"
                                    | "scale"
                                    | "simulatorSubversion"
                                    | "simulatorVersion"
                                    | "tnom"
                            ) | (BuiltIn::simparam_str, "cwd" | "module" | "instance" | "path")
                        )
                    } else {
                        false
                    };

                    self.report(BodyValidationDiagnostic::ConstSimparam {
                        known,
                        expr,
                        stmt: self.stmt,
                    });
                }
            }

            // Enhancement-396: time-like arguments spelled out as constants are
            // checked against what the operator's own definition allows. These
            // used to be accepted and then degrade silently at runtime.
            // Enhancement-396: `$limit` hands the simulator a function NAME, and
            // ngspice resolves it against a fixed table at load time. A name or
            // arity it cannot resolve used to leave a NULL function pointer that
            // the compiled model then CALLED -- an immediate SIGSEGV with no
            // output at all, from source that compiled clean. ngspice refuses to
            // load such a file now; this says the same thing at build time, when
            // the model is in front of the author.
            //
            // A lint rather than an error: the set is simulator-defined, so a
            // different OSDI consumer may legitimately provide more.
            (BuiltIn::limit, _) if args.len() >= 2 => {
                if let Expr::Literal(Literal::String(ref name)) =
                    self.parent.body.exprs[args[1]]
                {
                    let name = name.clone();
                    let nargs = args.len() - 2;
                    let known = matches!(
                        (&*name, nargs),
                        ("pnjlim", 2) | ("fetlim", 1) | ("limitlog", 1) | ("limvds", 0)
                    );
                    if !known {
                        self.report(BodyValidationDiagnostic::UnknownLimitFunction {
                            name: name.to_string().into_boxed_str(),
                            nargs,
                            expr,
                            stmt: self.stmt,
                        });
                    }
                }
            }

            // Enhancement-424: IEEE 1364-2005 17.1.2 gives `$finish`/`$stop` one
            // optional argument with exactly three meanings -- 0, 1 and 2 select
            // how much diagnostic information the simulator prints. Anything else
            // selects nothing. Same shape as the `last_crossing` direction
            // Enhancement-420 rejected, and checked the same way: literals only.
            (func @ (BuiltIn::finish | BuiltIn::stop), _) => {
                if let [code] = args {
                    if let Some(v) = self.const_num(*code) {
                        if v != 0.0 && v != 1.0 && v != 2.0 {
                            let name =
                                if func == BuiltIn::finish { "$finish" } else { "$stop" };
                            self.bad_arg(
                                name,
                                "the diagnostic level",
                                format!(
                                    "is {v}; it must be 0 (print nothing), 1 (print the \
                                     time and location) or 2 (print time, location and \
                                     statistics)"
                                ),
                                *code,
                            );
                        }
                    }
                }
            }

            (BuiltIn::bound_step, _) => {
                if let [step] = args {
                    self.require_positive("$bound_step", "the step bound", *step);
                }
            }

            // Enhancement-420: the degree of a discontinuity is the order of the
            // derivative that jumps -- 0 for the value itself, 1 for its slope,
            // and so on. Below that only -1 means anything: it is the LRM's
            // marker for a limiting discontinuity, written inside a `$limit`
            // function to say the iterate was moved (the LRM's own page-261
            // `spicepnjlim` diode does exactly this, and `lower_builtin` routes
            // it to `LimDiscontinuity`). Anything below -1 names nothing at all
            // and was silently treated as an ordinary non-negative degree.
            //
            // Deliberately NOT `require_non_negative`. That was the first shape
            // of this check and it rejected the LRM's own example -- caught by
            // examples/lrm_examples, which compiles page 261 verbatim.
            (BuiltIn::discontinuity, _) => {
                if let [degree] = args {
                    if let Some(v) = self.const_num(*degree) {
                        if v < -1.0 || !v.is_finite() {
                            self.bad_arg(
                                "$discontinuity",
                                "the degree",
                                format!(
                                    "is {v}; it must be 0 for the value, 1 for the first \
                                     derivative and so on, or -1 for a limiting \
                                     discontinuity inside a $limit function -- nothing \
                                     below -1 names a discontinuity, and it was being \
                                     treated as an ordinary one"
                                ),
                                *degree,
                            );
                        }
                    }
                }
            }

            // Enhancement-420: `ac_stim` names an analysis exactly as `analysis()`
            // does, and ngspice gates the source on `strcmp(src->analysis, "ac")`
            // (osdiacld.c). A name outside the matchable set leaves the stimulus
            // PERMANENTLY INACTIVE -- the model has an AC source that never
            // sources anything. `analysis("nosuch")` has warned since
            // Enhancement-399 and `$limit(.., "nosuchlimit", ..)` since
            // Enhancement-396; `ac_stim` was the one sibling left unchecked, the
            // shape this project keeps finding.
            (BuiltIn::ac_stim, _) => {
                if let Some(&name) = args.first() {
                    self.check_analysis_name("ac_stim", name);
                }
            }

            // Enhancement-420: the LRM defines exactly three directions for
            // `last_crossing` -- +1 rising, -1 falling, 0 either. Anything else
            // was accepted and behaved as 0, so `last_crossing(V(a) - 0.5, 7)`
            // returned the same time as the `either` form with nothing said. A
            // direction is a spelled-out constant in every real model, so the
            // typo is catchable here.
            (BuiltIn::last_crossing, _) if args.len() >= 2 => {
                if let Some(v) = self.const_num(args[1]) {
                    if v != -1.0 && v != 0.0 && v != 1.0 {
                        self.bad_arg(
                            "last_crossing",
                            "the direction",
                            format!(
                                "is {v}; it must be +1 (rising), -1 (falling) or 0 (either), \
                                 and any other value is silently treated as 0"
                            ),
                            args[1],
                        );
                    }
                }
            }

            (BuiltIn::absdelay, _) if args.len() >= 2 => {
                self.require_non_negative("absdelay", "the delay", args[1]);
                if args.len() >= 3 {
                    self.require_positive("absdelay", "the maximum delay", args[2]);
                    if let (Some(d), Some(m)) = (self.const_num(args[1]), self.const_num(args[2])) {
                        if d > m {
                            self.bad_arg("absdelay", "the delay", format!(
                                "is {d}, which exceeds the declared maximum delay {m}"), args[1]);
                        }
                    }
                }
                if let [other_args @ .., const_expr] = args {
                    if signature == Some(ABSDELAY_MAX) {
                        args = other_args;
                        self.validate_const_expr(*const_expr);
                    }
                }
            }

            (BuiltIn::transition, _) if args.len() >= 2 => {
                for (i, what) in
                    [(1usize, "the delay"), (2, "the rise time"), (3, "the fall time")]
                {
                    if let Some(&a) = args.get(i) {
                        self.require_non_negative("transition", what, a);
                    }
                }
                if let Some(&a) = args.get(4) {
                    self.require_positive("transition", "the time tolerance", a);
                }
                if let [other_args @ .., const_expr] = args {
                    if signature == Some(TRANSITION_DELAY_RISET_FALLT_TOL) {
                        args = other_args;
                        self.validate_const_expr(*const_expr);
                    }
                }
            }

            (BuiltIn::slew, _) if args.len() >= 2 => {
                self.require_positive("slew", "the maximum positive rate", args[1]);
                if let Some(&a) = args.get(2) {
                    if let Some(v) = self.const_num(a) {
                        if !(v < 0.0) {
                            self.bad_arg("slew", "the maximum negative rate", format!(
                                "must be less than zero, but is {v}"), a);
                        }
                    }
                }
            }

            (BuiltIn::idtmod, _) if args.len() >= 3 => {
                self.require_positive("idtmod", "the modulus", args[2]);
                if let [other_args @ .., const_expr] = args {
                    if signature == Some(IDT_IC_ASSERT_TOL) {
                        args = other_args;
                        self.validate_const_expr(*const_expr);
                    }
                }
            }

            (BuiltIn::absdelay, Some(ABSDELAY_MAX))
            | (BuiltIn::transition, Some(TRANSITION_DELAY_RISET_FALLT_TOL))
            | (BuiltIn::ddt, Some(DDT_TOL))
            | (BuiltIn::idt | BuiltIn::idtmod, Some(IDT_IC_ASSERT_TOL)) => {
                if let [other_args @ .., const_expr] = args {
                    // For `ddt`/`idt` this trailing argument is an ABSOLUTE
                    // TOLERANCE, and a tolerance is a magnitude: a negative one
                    // is meaningless. The same quantity is already refused when
                    // it is written as a `nature`'s `abstol` ("not a usable
                    // absolute tolerance"), but supplied inline here it was
                    // accepted without a word. `absdelay` and `transition` are
                    // deliberately excluded -- their trailing constants are the
                    // maximum delay and the time tolerance, both already checked
                    // above, and repeating it here would report them twice.
                    //
                    // A `nature` identifier is the other legal spelling of this
                    // argument; it does not fold to a number, so it passes
                    // through untouched.
                    match call {
                        BuiltIn::ddt => {
                            self.require_positive("ddt", "the absolute tolerance", *const_expr)
                        }
                        BuiltIn::idt => {
                            self.require_positive("idt", "the absolute tolerance", *const_expr)
                        }
                        BuiltIn::idtmod => {
                            self.require_positive("idtmod", "the absolute tolerance", *const_expr)
                        }
                        _ => {}
                    }
                    // Do not type check const expr twice
                    args = other_args;
                    self.validate_const_expr(*const_expr);
                };
            }

            (
                BuiltIn::laplace_nd | BuiltIn::laplace_np | BuiltIn::laplace_zp | BuiltIn::laplace_zd,
                Some(_),
            ) => {
                // args[0] (input signal) and args[1]/args[2] (num/den, or zero/pole) are
                // validated normally below: num/den may be either an array literal (whose
                // elements may be ordinary runtime expressions, e.g. parameters) or a bare
                // reference to a module-body array variable (Enhancement-4) -- neither is
                // required to be a compile-time constant, since each element is lowered as an
                // ordinary MIR value, not constant-folded. Only the optional trailing
                // tolerance/nature argument (unused, see Enhancement-4.md §1.3) still must be
                // constant.
                // Enhancement-399: NO array-literal check here, deliberately.
                // `laplace_*` accepts a concatenation and lowers it correctly --
                // measured: `{1.0}` and `'{1.0}` produce the identical AC
                // response, and examples/arraycast_examples relies on the
                // concatenation form. Only `noise_table` and `$table_model`
                // mishandle it (they yield an EMPTY table), so only they reject
                // it. The rule is "reject what is silently wrong", not "reject
                // everything that is not an array literal".
                if let [_in, num, den, const_args @ ..] = args {
                    self.check_filter_orders(call, *num, *den);
                    args = &args[..3];
                    for arg in const_args {
                        self.validate_const_expr(*arg)
                    }
                }
            }

            (
                BuiltIn::zi_nd | BuiltIn::zi_np | BuiltIn::zi_zd | BuiltIn::zi_zp,
                Some(_),
            ) => {
                if let [_expr, const_args @ ..] = args {
                    if let [num, den, ..] = const_args {
                        self.check_filter_orders(call, *num, *den);
                    }
                    // Enhancement-420: the sampling period T is what the whole
                    // z-domain filter is defined against; `zi_nd(x, '{1}, '{1}, 0.0, 0.0)`
                    // compiled, ran, and returned the INPUT UNCHANGED (y = 1.0 for a
                    // unit input) -- a filter that is not a filter, reported nowhere.
                    // A negative period is no better defined than a zero one.
                    if let ([_num, _den, period, ..], Some(name)) =
                        (const_args, Self::filter_name(call))
                    {
                        self.require_positive(name, "the sampling period", *period);
                    }
                    args = &args[..1];
                    for arg in const_args {
                        self.validate_const_expr(*arg)
                    }
                }
            }

            _ => (),
        }

        for arg in args {
            self.validate_expr(*arg)
        }
    }

    /// Enhancement-396: the compile-time-constant value of `expr`, if it has
    /// one. Only literals are folded here -- that is deliberately narrow. The
    /// point is to catch the spelled-out mistake (`$bound_step(0)`,
    /// `@(timer(0, 0))`) without pretending to know what a runtime expression
    /// will evaluate to.
    /// Enhancement-455: fold a CONSTANT ARITHMETIC EXPRESSION, not just a literal.
    ///
    /// Every value guard below is built on this, and it used to see through a
    /// literal and a unary minus and nothing else. So each guard caught exactly
    /// one spelling of a bad value and missed the identical value written as an
    /// expression:
    ///
    ///     white_noise(-1e-18)     -> refused
    ///     white_noise(0-1e-18)    -> ACCEPTED, and produced the same output noise
    ///                                as the positive power, silently
    ///
    /// The same gap let `$bound_step(1-1)`, `transition(x,0,0-1n,1n)` and
    /// `@(cross(e, 3+4))` through. It was not even consistent across the
    /// compiler: the array-bounds and integer-division checks fold first and DO
    /// catch `arr[2+3]` and `1/(1-1)`.
    ///
    /// A PARAMETER is deliberately still not folded. Its default may be
    /// overridden on the instance or model card, so refusing a model at compile
    /// time for a default that will never be used would be wrong -- the same
    /// reasoning that keeps a parameter's default out of its own range check.
    fn const_num(&self, expr: ExprId) -> Option<f64> {
        const_num_in(self.parent.db, self.parent.body, self.parent.infer, expr, 0)
    }

    /// Is this expression a bare reference to an array PARAMETER or array VARIABLE
    /// (an `array_identifier` in LRM 4.5.1 terms)?
    ///
    /// Checked against the module's declared arrays rather than by expression shape,
    /// because a bare path is also how a legal STRING PARAMETER file name is written
    /// (`parameter string f = "n.tbl"; ... noise_table(f)`) and that one must keep
    /// working.
    fn is_bare_array_ref_expr(&self, expr: ExprId) -> bool {
        let Expr::Path { ref path, port: false } = self.parent.body.exprs[expr] else {
            return false;
        };
        let Some(name) = path.as_ident() else { return false };
        let DefWithBodyId::ModuleId { module, .. } = self.parent.owner else { return false };
        let loc = module.lookup(self.parent.db.upcast());
        let tree = loc.item_tree(self.parent.db.upcast());
        tree[loc.id].param_arrays.iter().any(|arr| arr.base_name == name)
            || tree[loc.id].var_arrays.iter().any(|arr| arr.base_name == name)
    }

    /// Enhancement-399: `{a, b}` is a CONCATENATION; the array literal the LRM
    /// requires in these positions is `'{a, b}`. They differ by one character,
    /// both parse, and the wrong one was accepted in silence -- the builtin then
    /// behaved as though handed an EMPTY table. `$table_model(2.0, {..})`
    /// returned 0.0 where the array literal gave 20.0, and `noise_table({..})`
    /// contributed exactly no noise while its `'{..}` twin worked. Nothing was
    /// reported at compile time or at run time.
    ///
    /// The rule is not new: initialising a parameter array from a concatenation
    /// is already rejected. These builtins simply never applied it, because
    /// every check here was written as `if let Expr::Array(..)` and a
    /// concatenation is a different variant, so the whole check was skipped.
    ///
    /// ONLY a concatenation is rejected. A bare reference to an array VARIABLE
    /// is legitimate in these positions (Enhancement-4) and must keep working,
    /// so this must not become "anything that is not an array literal".
    fn require_array_arg(&mut self, builtin: &str, what: &str, expr: ExprId) {
        if let Expr::Concat { .. } = self.parent.body.exprs[expr] {
            self.bad_arg(
                builtin,
                what,
                "is a concatenation `{...}`, but an array literal `'{...}` is \
                 required here; as written the table is empty and the call \
                 contributes nothing"
                    .to_owned(),
                expr,
            )
        }
    }

    /// Enhancement-399: the analysis names the simulator can actually match,
    /// taken from `osdi/stdlib.c`'s `analysis()`. A name outside this set makes
    /// `analysis(...)` false in every analysis and `@(initial_step(...))` fire
    /// never -- dead code, reported nowhere.
    const ANALYSIS_NAMES: [&'static str; 7] =
        ["ac", "dc", "ic", "nodeset", "noise", "static", "tran"];

    fn check_analysis_name(&mut self, builtin: &str, expr: ExprId) {
        if let Expr::Literal(Literal::String(ref name)) = self.parent.body.exprs[expr] {
            let name = name.clone();
            if !Self::ANALYSIS_NAMES.contains(&&*name) {
                self.report(BodyValidationDiagnostic::UnknownAnalysisName {
                    name: name.to_string().into_boxed_str(),
                    builtin: builtin.to_owned().into_boxed_str(),
                    expr: Some(expr),
                    stmt: self.stmt,
                })
            }
        }
    }

    fn check_simparam_name(&mut self, builtin: &str, numeric: bool, expr: ExprId) {
        let Expr::Literal(Literal::String(ref name)) = self.parent.body.exprs[expr] else {
            return;
        };
        let name = name.clone();
        // Enhancement-215 serves command-line plusargs through this same channel
        // under generated `$test$plusargs$<x>` / `$valset$...` / `$valnum$...`
        // keys. They are meant to be reached through `$test$plusargs` and
        // `$value$plusargs`, but a name spelled with a `$` is plainly reaching for
        // that channel and is not this check's business.
        if name.contains('$') {
            return;
        }
        let known = if numeric {
            SIMPARAM_NAMES.contains(&&*name)
        } else {
            SIMPARAM_STR_NAMES.contains(&&*name)
        };
        if !known {
            self.report(BodyValidationDiagnostic::UnknownSimparam {
                name: name.to_string().into_boxed_str(),
                builtin: builtin.to_owned().into_boxed_str(),
                has_default_form: numeric,
                expr,
                stmt: self.stmt,
            })
        }
    }

    /// Enhancement-405: the numerator and denominator orders of a `laplace_*`/`zi_*` filter.
    ///
    /// Two things were silently wrong. An EMPTY coefficient list -- `zi_nd(x, '{1.0}, '{}, T, 0)`
    /// -- underflowed `den.len() - 1` in lowering and hung the compiler at tens of GB of RSS.
    /// And a numerator of HIGHER order than the denominator was silently TRUNCATED: the
    /// controllable-canonical realization can only carry a direct feedthrough term, so
    /// `laplace_nd(x, '{1.0, tau}, '{1.0})` quietly became the constant 1, and the pure
    /// differentiator `'{0.0, tau}` over `'{1.0}` became identically ZERO.
    ///
    /// An improper transfer function has unbounded gain as frequency grows and has no
    /// state-space realization, so it is rejected rather than approximated -- `ddt` is the
    /// spelling for a genuine derivative. Lengths are only known for a written-out array, so a
    /// runtime array variable is left alone, matching every other check here.
    /// The spelling of a `laplace_*`/`zi_*` builtin, for diagnostics.
    fn filter_name(builtin: BuiltIn) -> Option<&'static str> {
        Some(match builtin {
            BuiltIn::laplace_nd => "laplace_nd",
            BuiltIn::laplace_np => "laplace_np",
            BuiltIn::laplace_zd => "laplace_zd",
            BuiltIn::laplace_zp => "laplace_zp",
            BuiltIn::zi_nd => "zi_nd",
            BuiltIn::zi_np => "zi_np",
            BuiltIn::zi_zd => "zi_zd",
            BuiltIn::zi_zp => "zi_zp",
            _ => return None,
        })
    }

    fn check_filter_orders(&mut self, builtin: BuiltIn, num: ExprId, den: ExprId) {
        let name = match Self::filter_name(builtin) {
            Some(name) => name,
            None => return,
        };
        let num_is_roots = matches!(
            builtin,
            BuiltIn::laplace_zd | BuiltIn::laplace_zp | BuiltIn::zi_zd | BuiltIn::zi_zp
        );
        let den_is_roots = matches!(
            builtin,
            BuiltIn::laplace_np | BuiltIn::laplace_zp | BuiltIn::zi_np | BuiltIn::zi_zp
        );

        // a written-out list; anything else is a runtime value whose length is not known here.
        //
        // Enhancement-505: a bare concatenation counts as written out. `laplace_*`
        // accepts BOTH `'{1.0, tau}` and `{1.0, tau}` and lowers them identically
        // (Enhancement-399 measured that and deliberately allows the second), so a
        // check that reads only `Expr::Array` sees half the models -- one
        // apostrophe apart, the same split Enhancement-457 found in `'{4{0}}` vs
        // `{4{0}}`. A REPLICATION (`{4{0}}`, `rep: Some(..)`) is left alone here:
        // its length is the repetition count times the element count, which is not
        // this function's question.
        let len = |this: &Self, e: ExprId| match this.parent.body.exprs[e] {
            Expr::Array(ref elems) => Some(elems.len()),
            Expr::Concat { rep: None, ref elems } => Some(elems.len()),
            _ => None,
        };
        // Roots arrive as (real, imaginary) pairs, a trailing unpaired element being real.
        // `saturating_sub`, not `- 1`: an empty coefficient list is legal for the numerator
        // (H = 0) and `0 - 1` on a usize is exactly the underflow this release is fixing in
        // `lower_zi` -- it wrapped to usize::MAX and reported an order of 1.8e19.
        let order =
            |n: usize, is_roots: bool| if is_roots { n.div_ceil(2) } else { n.saturating_sub(1) };

        let (num_len, den_len) = (len(self, num), len(self, den));

        // an empty ROOT list is legitimate ("no zeros"); an empty COEFFICIENT list is not
        if den_len == Some(0) && !den_is_roots {
            self.bad_arg(
                name,
                "the denominator",
                "is an empty coefficient list; it needs at least a constant term".to_owned(),
                den,
            );
            return;
        }
        // An empty NUMERATOR is deliberately supported and means H = 0 -- examples/
        // vaflaplace_examples asserts it compiles. Only the denominator was ever the
        // problem, and only because `den.len() - 1` underflowed on it.

        // Enhancement-420: a denominator that is IDENTICALLY ZERO -- every
        // coefficient written out as the literal 0 -- makes the transfer function
        // num/0. `laplace_nd(V(a), '{1}, '{0})` compiled clean and then killed the
        // operating point with "Transient op failed, timestep too small", which
        // names neither the model nor the call, so the author debugs the netlist.
        //
        // Only a COEFFICIENT list is checked. An all-zero ROOT list (`laplace_np`,
        // `laplace_zp`, `zi_np`, `zi_zp`) means poles at the origin -- a pure
        // integrator, perfectly legitimate.
        //
        // A single zero coefficient is not the target either: `'{0.0, 1.0}` is the
        // denominator `s`, again an integrator. Only every element being zero is
        // the degenerate case, and only when every element FOLDS -- one runtime
        // expression in the list and this says nothing, matching the rule the
        // laplace arm states: reject what is silently wrong, not everything that
        // is not an array literal.
        if !den_is_roots {
            // Enhancement-505: `'{0}` was refused here and `{0}` was not, though
            // `laplace_*` accepts both. The concatenation form compiled clean and
            // returned a silent ZERO -- the opposite of the division by zero it
            // actually is -- so the model looked dead rather than wrong.
            let written_out = match self.parent.body.exprs[den] {
                Expr::Array(ref elems) => Some(elems.clone()),
                Expr::Concat { rep: None, ref elems } => Some(elems.clone()),
                _ => None,
            };
            if let Some(elems) = written_out {
                if !elems.is_empty()
                    && elems.iter().all(|&e| self.const_num(e) == Some(0.0))
                {
                    self.bad_arg(
                        name,
                        "the denominator",
                        "is identically zero, so the transfer function is a division by \
                         zero; the filter cannot be realized and the analysis fails with \
                         an error that names neither this model nor this call"
                            .to_owned(),
                        den,
                    );
                    return;
                }
            }
        }

        // ONLY the s-domain. In `z^-1` a numerator of higher order than the denominator is an
        // ordinary FIR filter -- more delay taps, causal and realizable -- and `lower_zi`
        // already pads both polynomials to `max(num, den)` before the bilinear transform, so
        // nothing is dropped there. Rejecting it would have broken working filters; the
        // truncation being fixed is specific to the controllable-canonical s-domain form.
        let s_domain = matches!(
            builtin,
            BuiltIn::laplace_nd | BuiltIn::laplace_np | BuiltIn::laplace_zd | BuiltIn::laplace_zp
        );
        // A denominator whose HIGHEST-order coefficient is zero. `'{1.0, 0.0}` is
        // the polynomial 1 + 0*s -- mathematically identical to `'{1.0}` -- but
        // the order above is taken from the LIST LENGTH, so this reads as order 1
        // and the controllable-canonical realization divides through by that
        // leading zero. The result was a filter with no output at all: `'{1.0}`
        // gave a gain of 1 and `'{1.0, 0.0}` gave 0, over the whole frequency
        // sweep, after a burst of "singular matrix: check node
        // n1#implicit_equation_0" that names an internal node rather than the
        // call. Padding a coefficient vector to a fixed length is an ordinary
        // thing to write when the top term is switched off.
        //
        // The z-domain twins are deliberately excluded: `lower_zi` pads both
        // polynomials to `max(num, den)` before the bilinear transform and
        // handles a trailing zero correctly -- `zi_nd`, `zi_zd` and `zi_np` all
        // return the right gain for exactly this input.
        //
        // Roots are excluded for the same reason as the all-zero check above: a
        // zero ROOT is a pole at the origin, which is a legitimate integrator.
        if s_domain && !den_is_roots {
            if let Expr::Array(ref elems) = self.parent.body.exprs[den] {
                let elems = elems.clone();
                // `> 1` leaves the identically-zero single `'{0}` to the check
                // above, which explains that case better.
                if elems.len() > 1 {
                    if let Some(&last) = elems.last() {
                        if self.const_num(last) == Some(0.0)
                            && !elems.iter().all(|&e| self.const_num(e) == Some(0.0))
                        {
                            self.bad_arg(
                                name,
                                "the denominator",
                                format!(
                                    "has a highest-order coefficient of zero, so its \
                                     effective order is {} rather than the {} its length \
                                     implies; the realization divides by that coefficient \
                                     and the filter produces no output at all -- drop the \
                                     trailing zero",
                                    elems
                                        .iter()
                                        .rposition(|&e| self.const_num(e) != Some(0.0))
                                        .unwrap_or(0),
                                    elems.len() - 1
                                ),
                                den,
                            );
                        }
                    }
                }
            }
        }

        // an empty numerator is H = 0 and has no order to compare
        if let (Some(n @ 1..), Some(d), true) = (num_len, den_len, s_domain) {
            let (no, do_) = (order(n, num_is_roots), order(d, den_is_roots));
            if no > do_ {
                self.bad_arg(
                    name,
                    "the numerator",
                    format!(
                        "is order {no} against a denominator of order {do_}; such a filter has \
                         unbounded gain at high frequency and no state-space realization, and \
                         the extra terms would be silently dropped -- use ddt() for a derivative"
                    ),
                    num,
                );
            }
        }
    }

    fn bad_arg(&mut self, builtin: &str, what: &str, why: String, expr: ExprId) {
        self.report(BodyValidationDiagnostic::InvalidBuiltinArg {
            builtin: builtin.to_owned().into_boxed_str(),
            what: what.to_owned().into_boxed_str(),
            why: why.into_boxed_str(),
            expr,
        })
    }

    /// Enhancement-396: reject a constant argument that must be strictly
    /// positive. A zero or negative time constant is never what the model meant
    /// and the runtime consequences are severe but silent -- `@(timer(0,0))`
    /// fired on EVERY solver evaluation (120 events where 10 were due), a
    /// negative `$bound_step` forced the minimum timestep everywhere (10001
    /// output rows against 108), and `$bound_step(0)` aborted the analysis with
    /// a "Timestep too small" that named neither the model nor the call.
    fn require_positive(&mut self, builtin: &str, what: &str, expr: ExprId) {
        if let Some(v) = self.const_num(expr) {
            if !(v > 0.0) || !v.is_finite() {
                self.bad_arg(builtin, what, format!("must be greater than zero, but is {v}"), expr)
            }
        }
    }

    fn require_non_negative(&mut self, builtin: &str, what: &str, expr: ExprId) {
        if let Some(v) = self.const_num(expr) {
            if v < 0.0 || !v.is_finite() {
                self.bad_arg(builtin, what, format!("must not be negative, but is {v}"), expr)
            }
        }
    }

    fn validate_const_expr(&mut self, expr: ExprId) {
        let old = replace(&mut self.parent.ctx, BodyCtx::Const);
        let sink = self.cond_diagnostic_sink.take();
        self.validate_expr(expr);
        self.cond_diagnostic_sink = sink;
        self.parent.ctx = old;
    }
}

/// Enhancement-59: for each user-function call in `func`'s body, walk the
/// callee's own (independently inferred) call graph; if `func` is reachable
/// the program is mutually recursive -- report it on the call expression that
/// enters the cycle. Each function body's `InferenceResult` is a separate
/// salsa query that never recurses into other bodies, so querying callees
/// here cannot cycle.
fn check_call_cycles(
    db: &dyn HirTyDB,
    func: FunctionId,
    infere: &InferenceResult,
    diagnostics: &mut Vec<BodyValidationDiagnostic>,
) {
    for (expr, resolved) in infere.resolved_calls.iter() {
        let ResolvedFun::User { func: callee, .. } = resolved else { continue };
        let mut path = vec![*callee];
        let mut visited = HashSet::default();
        if calls_reach(db, *callee, func, &mut visited, &mut path) {
            let mut cycle = vec![db.function_data(func).name.clone()];
            cycle.extend(path.iter().map(|f| db.function_data(*f).name.clone()));
            diagnostics.push(BodyValidationDiagnostic::RecursiveFunctionCall {
                expr: *expr,
                cycle,
            });
            return; // one report per function is plenty
        }
    }
}

/// DFS through resolved user-function calls: does `from`'s call graph reach
/// `target`? On success `path` holds the functions along the way (ending in
/// `target`).
fn calls_reach(
    db: &dyn HirTyDB,
    from: FunctionId,
    target: FunctionId,
    visited: &mut HashSet<FunctionId>,
    path: &mut Vec<FunctionId>,
) -> bool {
    if from == target {
        return true;
    }
    if !visited.insert(from) {
        return false;
    }
    let infere = db.inference_result(DefWithBodyId::FunctionId(from));
    for resolved in infere.resolved_calls.values() {
        let ResolvedFun::User { func: callee, .. } = resolved else { continue };
        path.push(*callee);
        if calls_reach(db, *callee, target, visited, path) {
            return true;
        }
        path.pop();
    }
    false
}

/// Enhancement-392: mirrors `hir_lower`'s `MAX_RUNTIME_TABLE`. Kept as a function
/// so the two crates stay textually linked; `hir_ty` cannot depend on `hir_lower`.
/// Enhancement-395: what is wrong with a `$table_model` control string, if
/// anything. `None` means every code in it is implemented.
///
/// LRM tables 9-30/9-31: the string is comma-separated per-dimension
/// sub-strings, optionally followed by `;<column>` selecting the dependent
/// variable. Each sub-string is one interpolation character (`I`, `D`, `1`,
/// `2`, `3`) followed by up to two extrapolation characters (`C`, `L`, `E`),
/// one per end.
///
/// Implemented here: interpolation `1` and `3`, extrapolation `C` and `L`
/// applied to BOTH ends. Everything else the LRM defines is reported rather
/// than silently replaced by linear-with-clamped-ends.
///
/// NOTE ON THE DEFAULT: the LRM makes LINEAR extrapolation the default when no
/// extrapolation character is given; this implementation clamps. That is a
/// deliberate compatibility decision, not an oversight -- flipping it would
/// silently change the answer of every existing model written with `"1"` or
/// `"3"`, including this project's own suites. It is documented rather than
/// changed, and an explicit `L` or `C` always means exactly what it says.
fn table_ctrl_problem(ctrl: &str) -> Option<String> {
    // strip the dependent-variable selector
    let body = match ctrl.split_once(';') {
        Some((head, sel)) => {
            if sel.is_empty() || !sel.chars().all(|c| c.is_ascii_digit()) {
                return Some(format!(
                    "'{sel}' is not a dependent-variable column number"
                ));
            }
            head
        }
        None => ctrl,
    };
    for sub in body.split(',') {
        // whitespace anywhere in a sub-string is ignored, so "3 L" keeps working
        let sub: String = sub.chars().filter(|c| !c.is_whitespace()).collect();
        let sub = sub.as_str();
        let mut chars = sub.chars();
        let Some(first) = chars.next() else { continue };
        let rest: String = match first {
            '1' | '3' => chars.collect(),
            '2' => {
                return Some(
                    "quadratic spline interpolation ('2') is not implemented; use '1' or '3'"
                        .to_owned(),
                )
            }
            'D' | 'd' => {
                return Some(
                    "closest-point lookup ('D') is not implemented; use '1' or '3'".to_owned()
                )
            }
            'I' | 'i' => {
                return Some("column selection ('I') is not implemented".to_owned())
            }
            'C' | 'L' | 'c' | 'l' | 'E' | 'e' => {
                // no interpolation character: the whole sub-string is extrapolation
                sub.to_owned()
            }
            other => return Some(format!("'{other}' is not an interpolation control character")),
        };
        let ext: Vec<char> = rest.chars().collect();
        if ext.len() > 2 {
            return Some(format!("'{sub}' has more than two extrapolation characters"));
        }
        for &c in &ext {
            match c {
                'C' | 'L' | 'c' | 'l' => {}
                'E' | 'e' => {
                    return Some(
                        "error-on-extrapolation ('E') is not implemented; it would silently \
                         clamp instead, so it is rejected rather than ignored"
                            .to_owned(),
                    )
                }
                other => {
                    return Some(format!("'{other}' is not an extrapolation control character"))
                }
            }
        }
        if ext.len() == 2 && ext[0].to_ascii_uppercase() != ext[1].to_ascii_uppercase() {
            return Some(format!(
                "'{sub}' asks for a different extrapolation method at each end, which is not \
                 implemented; both ends use the same method"
            ));
        }
    }
    None
}

fn hir_lower_max_runtime_table() -> usize {
    256
}

/// Fold `expr` to a number if its value is fixed at compile time.
///
/// Every value guard in this file asks this question, and until now the answer
/// was "only if it is spelled as a literal". A `localparam` is a compile-time
/// constant that the LRM forbids from being overridden, so the compiler knows
/// its value exactly -- yet naming one bypassed every check. The same bad
/// value, six ways:
///
/// ```verilog
/// white_noise(-1e-12)                          // rejected
/// white_noise(-1e-12*1.0)                      // rejected -- folding IS applied
/// localparam real q = -1e-12; white_noise(q)   // accepted, silently
/// ```
///
/// That gap is not academic: models name their constants. It reached
/// `$bound_step`, `@(timer)`, `@(cross)`, `transition`, `absdelay`, `zi_nd`,
/// `last_crossing`, `white_noise`, `flicker_noise` and the parameter-range
/// emptiness check -- eleven guard sites, one cause.
///
/// A `parameter` is deliberately NOT folded. Its declared value is a DEFAULT
/// that the model card may override, so it is not what the model will run with,
/// and refusing a module because of its default would police a value no
/// simulation need ever use. That is the same rule under which a parameter's
/// default is not checked against its own `from`/`exclude` range.
fn const_num_in(
    db: &dyn HirTyDB,
    body: &Body,
    infer: &InferenceResult,
    expr: ExprId,
    depth: u32,
) -> Option<f64> {
    // A localparam may be defined in terms of another; the chain is finite
    // (cycles are rejected before this runs) but bound the recursion anyway so
    // a malformed tree cannot blow the stack while diagnostics are being built.
    if depth > 32 {
        return None;
    }
    match body.exprs[expr] {
        Expr::Literal(Literal::Float(v)) => Some(f64::from(v)),
        Expr::Literal(Literal::Int(v)) => Some(v as f64),
        Expr::UnaryOp { expr: inner, op: UnaryOp::Neg } => {
            const_num_in(db, body, infer, inner, depth).map(|v| -v)
        }
        Expr::UnaryOp { expr: inner, op: UnaryOp::Identity } => {
            const_num_in(db, body, infer, inner, depth)
        }
        Expr::BinaryOp { lhs, rhs, op: Some(op) } => {
            let l = const_num_in(db, body, infer, lhs, depth)?;
            let r = const_num_in(db, body, infer, rhs, depth)?;
            match op {
                BinaryOp::Addition => Some(l + r),
                BinaryOp::Subtraction => Some(l - r),
                BinaryOp::Multiplication => Some(l * r),
                // A zero divisor is left to the division checks, which
                // report it themselves; folding it here would hand the
                // caller an inf and produce a second, confusing complaint.
                BinaryOp::Division if r != 0.0 => Some(l / r),
                _ => None,
            }
        }
        Expr::Path { port: false, .. } => match infer.expr_types[expr] {
            Ty::Param(_, param) => const_param_value(db, param, depth + 1),
            _ => None,
        },
        _ => None,
    }
}

/// The compile-time value of a `localparam`, or `None` for anything the
/// compiler cannot pin down (an overridable `parameter` included -- see
/// [`const_num_in`]).
fn const_param_value(db: &dyn HirTyDB, param: ParamId, depth: u32) -> Option<f64> {
    if depth > 32 || !db.param_data(param).is_local {
        return None;
    }
    let owner = DefWithBodyId::ParamId(param);
    let body = db.body(owner);
    let infer = db.inference_result(owner);
    let default = db.param_exprs(param).default;
    const_num_in(db, &body, &infer, default, depth)
}

/// Enhancement-506: the `$dist_*`/`$rdist_*` spelling the AUTHOR wrote.
///
/// The validation arms above deliberately serve both families at once -- the LRM
/// domain rule is the same for `$dist_normal` and `$rdist_normal`, and checking
/// them together is what keeps the two spellings from drifting apart. The
/// diagnostic, though, has to name the call that is actually in the source.
fn rng_builtin_name(call: BuiltIn) -> &'static str {
    match call {
        BuiltIn::dist_uniform => "$dist_uniform",
        BuiltIn::dist_normal => "$dist_normal",
        BuiltIn::dist_exponential => "$dist_exponential",
        BuiltIn::dist_poisson => "$dist_poisson",
        BuiltIn::dist_chi_square => "$dist_chi_square",
        BuiltIn::dist_t => "$dist_t",
        BuiltIn::dist_erlang => "$dist_erlang",
        BuiltIn::rdist_uniform => "$rdist_uniform",
        BuiltIn::rdist_normal => "$rdist_normal",
        BuiltIn::rdist_exponential => "$rdist_exponential",
        BuiltIn::rdist_poisson => "$rdist_poisson",
        BuiltIn::rdist_chi_square => "$rdist_chi_square",
        BuiltIn::rdist_t => "$rdist_t",
        _ => "$rdist_erlang",
    }
}
