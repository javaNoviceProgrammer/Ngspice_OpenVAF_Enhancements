use std::fmt::Display;

use hir::{Node, Parameter};
use lasso::Spur;
use mir::{FunctionSignature, Param};
use stdx::Ieee64;

use crate::fmt::{DisplayKind, FmtArg};
use crate::LimitState;

#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum ParamInfoKind {
    Invalid,
    MinInclusive,
    MaxInclusive,
    MinExclusive,
    MaxExclusive,
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub enum RetFlag {
    Abort,
    Finish,
    Stop,
    Limited,
    /// Enhancement-55: `$discontinuity(n >= 0)` announced a discontinuity at
    /// this evaluation; the simulator may reject the current timestep and
    /// retry with a smaller one (sharp event resolution), in addition to the
    /// E-24 bound_step clamp on the next step.
    Discont,
}

/// The statistical-distribution family selected for a `$random`/`$dist_*`/`$rdist_*`
/// system-function call (Enhancement-10). Each variant maps to one deterministic
/// `osdi_rng_*` runtime function in `openvaf/osdi/stdlib.c`.
///
/// The runtime functions are *pure* functions of `(seed, salt)` plus the trailing
/// real distribution parameters -- they do not read or advance any persistent state.
/// `salt` is a per-call-site constant (the call `ExprId`), so distinct call sites
/// draw from independent streams while a given `(seed, salt)` is fully reproducible
/// and stable across Newton iterations (which the seed-writeback the LRM nominally
/// prescribes would not be -- see Enhancement-10.md).
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum RngFun {
    /// `$random` / `$arandom`: uniform signed 32-bit integer (no distribution params).
    Random,
    /// `$rdist_uniform`: uniform real in `[start, end)`.
    Uniform,
    /// `$dist_uniform`: uniform integer in `[start, end]` (inclusive).
    UniformInt,
    /// `$rdist_normal` / `$dist_normal`: gaussian with `(mean, std_dev)`.
    Normal,
    /// `$rdist_exponential` / `$dist_exponential`: exponential with `(mean)`.
    Exponential,
    /// `$rdist_poisson` / `$dist_poisson`: poisson count with `(mean)`.
    Poisson,
    /// `$rdist_chi_square` / `$dist_chi_square`: chi-square with `(dof)`.
    ChiSquare,
    /// `$rdist_t` / `$dist_t`: student-t with `(dof)`.
    StudentT,
    /// `$rdist_erlang` / `$dist_erlang`: erlang with `(k, mean)`.
    Erlang,
}

impl RngFun {
    /// Name of the corresponding runtime function in `openvaf/osdi/stdlib.c`.
    pub fn stdlib_name(self) -> &'static str {
        match self {
            RngFun::Random => "osdi_rng_random",
            RngFun::Uniform => "osdi_rng_uniform",
            RngFun::UniformInt => "osdi_rng_uniform_int",
            RngFun::Normal => "osdi_rng_normal",
            RngFun::Exponential => "osdi_rng_exponential",
            RngFun::Poisson => "osdi_rng_poisson",
            RngFun::ChiSquare => "osdi_rng_chi_square",
            RngFun::StudentT => "osdi_rng_t",
            RngFun::Erlang => "osdi_rng_erlang",
        }
    }

    /// Number of trailing real (`double`) distribution-parameter arguments, in
    /// addition to the leading `(seed, salt)` integer pair every `osdi_rng_*`
    /// function takes.
    pub fn num_real_params(self) -> u16 {
        match self {
            RngFun::Random => 0,
            RngFun::Exponential | RngFun::Poisson | RngFun::ChiSquare | RngFun::StudentT => 1,
            RngFun::Uniform | RngFun::UniformInt | RngFun::Normal | RngFun::Erlang => 2,
        }
    }
}

impl std::fmt::Display for RetFlag {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let txt = match self {
            Self::Abort => "abort",
            Self::Finish => "finish",
            Self::Stop => "stop",
            Self::Limited => "limited",
            Self::Discont => "discont",
        };
        write!(f, "{}", txt)
    }
}

/// A file-descriptor system function (Enhancement-11 file I/O) that operates on
/// integer file descriptors returned by `$fopen`. Each maps to one `osdi_*`
/// runtime function in `openvaf/osdi/stdlib.c`; all take integer arguments and
/// return an integer.
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum FileOp {
    /// `$fclose(fd)`
    Close,
    /// `$fflush(fd)`
    Flush,
    /// `$fflush()` -- flush every open descriptor
    FlushAll,
    /// `$feof(fd)`
    Eof,
    /// `$ftell(fd)`
    Tell,
    /// `$rewind(fd)`
    Rewind,
    /// `$fseek(fd, offset, whence)`
    Seek,
}

impl FileOp {
    pub fn stdlib_name(self) -> &'static str {
        match self {
            FileOp::Close => "osdi_fclose",
            FileOp::Flush => "osdi_fflush",
            FileOp::FlushAll => "osdi_fflush_all",
            FileOp::Eof => "osdi_feof",
            FileOp::Tell => "osdi_ftell",
            FileOp::Rewind => "osdi_frewind",
            FileOp::Seek => "osdi_fseek",
        }
    }

    /// Number of integer arguments the runtime function takes.
    pub fn num_args(self) -> u16 {
        match self {
            FileOp::FlushAll => 0,
            FileOp::Seek => 3,
            _ => 1,
        }
    }
}

/// Where a `$display`-family formatted string goes (Enhancement-11).
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum PrintDst {
    /// `$display`/`$strobe`/... -> the simulator console (`osdi_log`).
    Console,
    /// `$fdisplay`/`$fwrite`/... -> a file descriptor (`osdi_fputs`); an extra
    /// leading integer descriptor argument is passed.
    File,
    /// `$swrite`/`$sformat` -> returned as a freshly allocated string, which the
    /// caller stores into the destination string variable. The callback returns
    /// a `char*` instead of `void`.
    String,
}

/// A field extracted by `$sscanf`/`$fscanf` (Enhancement-11). These pull the
/// next whitespace-delimited token from the runtime scan cursor set up by
/// `ScanBegin`; the type selects how the token is parsed and thus the callback's
/// return type.
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum ScanKind {
    Int,
    Real,
    Str,
}

impl ScanKind {
    pub fn stdlib_name(self) -> &'static str {
        match self {
            ScanKind::Int => "osdi_scan_int",
            ScanKind::Real => "osdi_scan_real",
            ScanKind::Str => "osdi_scan_str",
        }
    }
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub enum CallBackKind {
    /// A `$display`/`$write`/... formatted print (Enhancement-11 generalised it
    /// with `dst`). All variants share the `snprintf`-based formatting machinery
    /// (`fmt::ins_display`, `osdi::print_callback`); `dst` selects the sink:
    /// console (`osdi_log`), file (`osdi_fputs`, with a leading descriptor arg),
    /// or a returned string (`$swrite`/`$sformat`).
    Print { kind: DisplayKind, arg_tys: Box<[FmtArg]>, dst: PrintDst },
    /// Begin a `$sscanf`/`$fscanf` parse over the given input string; resets the
    /// runtime scan cursor and match count. Args: `(input: ptr)`.
    ScanBegin,
    /// Pull the next field from the scan cursor (see `ScanKind`).
    Scan(ScanKind),
    /// The number of successful conversions since the last `ScanBegin`
    /// (the `$sscanf`/`$fscanf` return value).
    ScanCount,
    /// `$fgets(fd) -> char*`: read one line from the descriptor.
    Fgets,
    /// `osdi_strlen(s) -> int`: length of a string (for `$fgets`'s return count).
    StrLen,
    /// `$ferror(fd)` error message (`-> char*`) and code (`-> int`).
    FerrorMsg,
    FerrorCode,
    /// `$fopen(name [, mode])` -> integer descriptor (Enhancement-11). Args are
    /// `(name: ptr, mode: ptr)`; a missing mode is materialised as a default at
    /// the call site so the runtime signature is uniform.
    Fopen,
    /// A file-descriptor operation on an already-open descriptor (Enhancement-11).
    FileOp(FileOp),
    SimParam,
    SimParamOpt,
    SimParamStr,
    Derivative(Param),
    NodeDerivative(Node),
    ParamInfo(ParamInfoKind, Parameter),
    CollapseHint(Node, Option<Node>),
    LimDiscontinuity,
    Analysis,
    BuiltinLimit { name: Spur, num_args: u32 },
    StoreLimit(LimitState),
    TimeDerivative,
    WhiteNoise { name: Spur, idx: u32 },
    FlickerNoise { name: Spur, idx: u32 },
    NoiseTable(Box<NoiseTable>),
    /// `ac_stim([name][, mag][, phase])` (Enhancement-51): a small-signal AC
    /// stimulus source. `name` is the ANALYSIS name (default "ac"); args are
    /// [mag, phase]. Rides the noise extraction pipeline (same branch/factor
    /// machinery), partitioned into its own descriptor array at the OSDI level.
    AcStim { name: Spur, idx: u32 },
    SetRetFlag(RetFlag),
    /// A `$random`/`$dist_*`/`$rdist_*` draw (Enhancement-10). Resolved to the
    /// matching `osdi_rng_*` runtime function in `general_callbacks`. The call's
    /// MIR arguments are `(seed: int, salt: int, params...: real)`; the callback
    /// returns a `real` (integer-returning builtins cast/round it at the call
    /// site). It carries no per-call-site data (the salt is passed as an argument)
    /// so identical `RngFun`s share a single interned callback.
    Rng(RngFun),
}

impl CallBackKind {
    pub fn signature(&self) -> FunctionSignature {
        match self {
            CallBackKind::SimParam => FunctionSignature {
                name: "simparam".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::SimParamOpt => FunctionSignature {
                name: "simparam_opt".to_owned(),
                params: 2,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::SimParamStr => FunctionSignature {
                name: "simparam_str".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::Derivative(param) => FunctionSignature {
                name: format!("ddx_{}", param),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::NodeDerivative(node) => FunctionSignature {
                name: format!("ddx_node_{:?}", node),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::ParamInfo(kind, param) => FunctionSignature {
                name: format!("set_{:?}({:?})", kind, param),
                params: 0,
                returns: 0,
                has_sideeffects: true,
            },
            CallBackKind::CollapseHint(hi, lo) => FunctionSignature {
                name: format!("collapse_{:?}_{:?}", hi, lo),
                params: 0,
                returns: 0,
                has_sideeffects: true,
            },
            CallBackKind::Print { kind, arg_tys: args, dst } => FunctionSignature {
                name: format!("{:?}[{:?}])", kind, dst),
                // format string + the formatted args, plus (file only) the
                // leading descriptor argument.
                params: args.len() as u16 + 1 + u16::from(*dst == PrintDst::File),
                // the string variant returns the freshly formatted `char*`
                returns: u16::from(*dst == PrintDst::String),
                has_sideeffects: true,
            },
            CallBackKind::Fopen => FunctionSignature {
                name: "fopen".to_owned(),
                params: 2,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::FileOp(op) => FunctionSignature {
                name: format!("{:?}", op),
                params: op.num_args(),
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::ScanBegin => FunctionSignature {
                name: "scanf_begin".to_owned(),
                params: 1,
                returns: 0,
                has_sideeffects: true,
            },
            CallBackKind::Scan(kind) => FunctionSignature {
                name: format!("scan_{:?}", kind),
                params: 0,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::ScanCount => FunctionSignature {
                name: "scanf_count".to_owned(),
                params: 0,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::Fgets => FunctionSignature {
                name: "fgets".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::StrLen => FunctionSignature {
                name: "strlen".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::FerrorMsg => FunctionSignature {
                name: "ferror_msg".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::FerrorCode => FunctionSignature {
                name: "ferror_code".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: true,
            },
            CallBackKind::BuiltinLimit { name, num_args } => FunctionSignature {
                name: format!("$limit[{name:?}]"),
                params: *num_args as u16,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::StoreLimit(state) => FunctionSignature {
                name: format!("$store[{state:?}]"),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::LimDiscontinuity => FunctionSignature {
                name: "$discontinuty[-1]".to_owned(),
                params: 0,
                returns: 0,
                has_sideeffects: true,
            },
            CallBackKind::Analysis => FunctionSignature {
                name: "analysis".to_owned(),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::TimeDerivative => FunctionSignature {
                name: "ddt".to_string(),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::WhiteNoise { name, .. } => FunctionSignature {
                name: format!("white_noise({name:?})"),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::FlickerNoise { name, .. } => FunctionSignature {
                name: format!("flickr_noise({name:?})"),
                params: 2,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::AcStim { name, .. } => FunctionSignature {
                name: format!("ac_stim({name:?})"),
                params: 2,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::NoiseTable(table) => FunctionSignature {
                name: format!(
                    "table_noise{}({:?}, {:?})",
                    if table.log { "lob" } else { "" },
                    table.name,
                    &table.vals
                ),
                params: 1,
                returns: 1,
                has_sideeffects: false,
            },
            CallBackKind::SetRetFlag(flag) => FunctionSignature {
                name: format!("SetRetFlag[{}]", flag),
                params: 0,
                returns: 0,
                has_sideeffects: true,
            },
            CallBackKind::Rng(fun) => FunctionSignature {
                name: format!("rng_{:?}", fun),
                // (seed, salt) integers + the distribution's real parameters
                params: 2 + fun.num_real_params(),
                returns: 1,
                // Pure: a deterministic function of its arguments with no state.
                has_sideeffects: false,
            },
        }
    }
    pub fn is_noise(&self) -> bool {
        matches!(
            self,
            CallBackKind::WhiteNoise { .. }
                | CallBackKind::FlickerNoise { .. }
                | CallBackKind::NoiseTable(_)
                | CallBackKind::AcStim { .. }
        )
    }

    pub fn op_dependent(&self) -> bool {
        matches!(
            self,
            CallBackKind::SimParam
                | CallBackKind::SimParamOpt
                | CallBackKind::StoreLimit(_)
                | CallBackKind::Analysis
                | CallBackKind::SimParamStr
                | CallBackKind::LimDiscontinuity
                | CallBackKind::BuiltinLimit { .. }
        )
    }

    pub fn ignore_if_op_dependent(&self) -> bool {
        matches!(self, CallBackKind::CollapseHint(_, _))
    }

    pub fn tracked(&self) -> bool {
        !matches!(self, CallBackKind::Print { .. })
    }
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct NoiseTable {
    pub name: Spur,
    pub log: bool,
    pub vals: Box<[(Ieee64, Ieee64)]>,
    idx: u32,
}

impl NoiseTable {
    // `vals` are the raw `(frequency, power)` pairs already gathered by the
    // caller from an inline array or a data file (see
    // `BodyLoweringCtx::noise_table_data` in `expr.rs`). For `log == false`
    // the frequency column is `log10`-ed here so that, in both the linear and
    // `_log` cases, `vals` ends up keyed by `log10(frequency)`.
    pub fn new(
        vals: impl IntoIterator<Item = (f64, f64)>,
        log: bool,
        name: Spur,
        idx: u32,
    ) -> Self {
        let mut vals: Vec<(Ieee64, Ieee64)> = if log {
            vals.into_iter().map(|(f, pwr)| (f.into(), pwr.into())).collect()
        } else {
            vals.into_iter().map(|(f, pwr)| (f.log10().into(), pwr.into())).collect()
        };
        vals.sort_unstable_by(|(f1, _), (f2, _)| f1.partial_cmp(f2).unwrap());
        vals.dedup_by_key(|(f, _)| *f);
        Self { name, log, vals: vals.into_boxed_slice(), idx }
    }
}
