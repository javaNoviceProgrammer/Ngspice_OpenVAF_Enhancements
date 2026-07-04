#[rustfmt::skip]
mod generated;

use generated::builtin_info;
use hir_def::{BuiltIn, Type};

use crate::types::{BuiltinInfo, Signature, SignatureData, TyRequirement};

impl BuiltinInfo {
    const fn new(signatures: &'static [SignatureData], has_side_effects: bool) -> BuiltinInfo {
        let mut min_args = None;
        let mut max_args = None;
        let mut i = 0;
        while i < signatures.len() {
            let arg_cnt = match &signatures[i].args {
                Cow::Borrowed(x) => x.len(),
                Cow::Owned(_) => unreachable!(),
            };
            match min_args {
                None => min_args = Some(arg_cnt),
                Some(old_min) if arg_cnt < old_min => min_args = Some(arg_cnt),
                _ => (),
            }
            match max_args {
                None => max_args = Some(arg_cnt),
                Some(old_max) if arg_cnt > old_max => max_args = Some(arg_cnt),
                _ => (),
            }
            i += 1;
        }
        let min_args = match min_args {
            Some(val) => val,
            None => 0,
        };
        BuiltinInfo { signatures, min_args, max_args, has_side_effects }
    }

    const fn impure_fn(signatures: &'static [SignatureData]) -> BuiltinInfo {
        BuiltinInfo::new(signatures, true)
    }

    const fn pure_fn(signatures: &'static [SignatureData]) -> BuiltinInfo {
        BuiltinInfo::new(signatures, false)
    }

    const fn special_cased_pure(min_args: usize, max_args: Option<usize>) -> BuiltinInfo {
        BuiltinInfo { signatures: &[], min_args, max_args, has_side_effects: false }
    }

    const fn varargs(signatures: &'static [SignatureData], has_side_effects: bool) -> BuiltinInfo {
        let mut min_args = None;
        let mut i = 0;
        while i < signatures.len() {
            let arg_cnt = match &signatures[i].args {
                Cow::Borrowed(x) => x.len(),
                Cow::Owned(_) => unreachable!(),
            };
            match min_args {
                None => min_args = Some(arg_cnt),
                Some(old_min) if arg_cnt < old_min => min_args = Some(arg_cnt),
                _ => (),
            }

            i += 1;
        }

        let min_args = match min_args {
            Some(min_args) => min_args,
            None => 0,
        };
        BuiltinInfo { signatures, has_side_effects, max_args: None, min_args }
    }
}

impl From<BuiltIn> for BuiltinInfo {
    fn from(builtin: BuiltIn) -> Self {
        builtin_info(builtin)
    }
}

use std::borrow::Cow;

use TyRequirement::*;
use Type::*;

macro_rules! bultins {
    {
         $name: ident = $($const: ident)? {
            $(fn $signature: ident($($args: expr),*) -> $ty: ident;)*
        }
        $($rem: tt)*
    } => {
        const $name: BuiltinInfo = BuiltinInfo::new(
            &[$(SignatureData{
                args: Cow::Borrowed(&[$($args),*]),
                return_ty: Type::$ty,
            }),*],
            bultins!(@is_pure $($const)?)
        );
        bultins!(@SIGNATURES [$(stringify!($signature)),*].len(); $($signature),*);
        bultins!($($rem)*);
    };

    {
        fn $name: ident ($($args: expr),*) -> $ty: ident;
        $($rem: tt)*
    } => {
        const $name: BuiltinInfo = BuiltinInfo::impure_fn(
            &[SignatureData{
                args: Cow::Borrowed(&[$($args),*]),
                return_ty: Type::$ty,
            }],
        );
        bultins!($($rem)*);
    };

    {
        const fn $name: ident ($($args: expr),*) -> $ty: ident;
        $($rem: tt)*
    } => {
        const $name: BuiltinInfo = BuiltinInfo::pure_fn(
            &[SignatureData{
                args: Cow::Borrowed(&[$($args),*]),
                return_ty: Type::$ty,
            }],
        );
        bultins!($($rem)*);
    };



    { @is_pure const} => {
        true
    };


    { @is_pure} => {
        false
    };

    { @SIGNATURES $cnt:expr; $name: ident $(,$rem:ident)+} => {
        pub const $name: Signature = Signature(($cnt - [$(stringify!($rem)),*].len() - 1) as u32);
        bultins!(@SIGNATURES $cnt; $($rem),*);
    };


    { @SIGNATURES $cnt:expr; $name: ident } => {
        pub const $name: Signature = Signature($cnt as u32 - 1);
    };


    {} => {};
}

// WARNING: THE ORDER OF THE SIGNATURES IS IMPORTANT AND RELIED UPON TO BE STABLE
// ALWAYS ADD NEW SIGNATURES AT THE END!

bultins! {
    FLOW = const {
        fn NATURE_ACCESS_BRANCH(Branch) -> Real;
        fn NATURE_ACCESS_NODES(Node,Node) -> Real;
        fn NATURE_ACCESS_NODE_GND(Node) -> Real;
        fn NATURE_ACCESS_PORT_FLOW(PortFlow) -> Real;
    }

    MAX = {
        fn MAX_INT(Val(Integer),Val(Integer)) -> Integer;
        fn MAX_REAL(Val(Real),Val(Real)) -> Real;
    }

    ABS = const {
        fn ABS_INT(Val(Integer)) -> Integer;
        fn ABS_REAL(Val(Real)) -> Real;
    }

    AC_STIM = const {
        fn AC_STIM_UNIT() -> Real;
        fn AC_STIMT_NAME(Val(String)) -> Real;
        fn AC_STIM_NAME_MAG(Val(String),Val(Real)) -> Real;
        fn AC_STIM_NAME_MAG_PHASE(Val(String),Val(Real),Val(Real)) -> Real;
    }

    const fn REAL_INFO() -> Real;
    const fn REAL_MATH_1(Val(Real)) -> Real;
    const fn REAL_MATH_2(Val(Real),Val(Real)) -> Real;
    const fn INT_MATH_2(Val(Integer),Val(Integer)) -> Integer;


    VT = const {
        fn VT_TEMP() -> Real;
        fn VT_ARG(Val(Real)) -> Real;
    }

    FLICKER_NOISE = const{
        fn FLICKER_NOISE_NO_NAME(Val(Real),Val(Real)) -> Real;
        fn FLICKER_NOISE_NAME(Val(Real),Val(Real),Literal(String)) -> Real;
    }

    WHITE_NOISE = const{
        fn WHITE_NOISE_NO_NAME(Val(Real)) -> Real;
        fn WHITE_NOISE_NAME(Val(Real),Literal(String)) -> Real;
    }


    NOISE_TABLE = const {
        fn NOISE_TABLE_INLINE(ArrayAnyLength{ty: Real}) -> Real;
        fn NOISE_TABLE_FILE(Val(String)) -> Real;
        fn NOISE_TABLE_INLINE_NAME(ArrayAnyLength{ty: Real},Literal(String)) -> Real;
        fn NOISE_TABLE_FILE_NAME(Val(String),Literal(String)) -> Real;
    }

    DDT = const {
        fn DDT_NO_TOL(Val(Real)) -> Real;
        fn DDT_TOL(Val(Real),Val(Real)) -> Real;
        fn DDT_NATURE_TOL(Val(Real),Nature) -> Real;
    }

    IDT = const {
        fn IDT_NO_IC(Val(Real)) -> Real;
        fn IDT_IC(Val(Real),Val(Real)) -> Real;
        fn IDT_IC_ASSERT(Val(Real),Val(Real),Val(Real)) -> Real;
        fn IDT_IC_ASSERT_TOL(Val(Real),Val(Real),Val(Real),Val(Real)) -> Real;
        fn IDT_IC_ASSERT_NATURE(Val(Real),Val(Real),Val(Real),Nature) -> Real;
    }

    IDTMOD = const {
        fn IDTMOD_NO_IC(Val(Real)) -> Real;
        fn IDTMOD_IC(Val(Real),Val(Real)) -> Real;
        fn IDTMOD_IC_MODULUS(Val(Real),Val(Real),Val(Real)) -> Real;
        fn IDTMOD_IC_MODULUS_OFFSET(Val(Real),Val(Real),Val(Real),Val(Real)) -> Real;
        fn IDTMOD_IC_MODULUS_OFFSET_TOL(Val(Real),Val(Real),Val(Real),Val(Real), Val(Real)) -> Real;
        fn IDTMOD_IC_MODULUS_OFFSET_NATURE(Val(Real),Val(Real),Val(Real),Val(Real), Val(Real)) -> Real;
    }

    // all laplace filters have the same signature
    LAPLACE_FILTER = const {
        fn LAPLACE_NO_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}) -> Real;
        fn LAPALCE_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}, Val(Real)) -> Real;
        fn LAPLACE_NATURE_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}, Nature) -> Real;
    }

    // all zi filters have the same signature
    ZI_FILTER = const {
        fn ZI_NO_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}, Val(Real)) -> Real;
        fn ZI_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}, Val(Real), Val(Real)) -> Real;
        fn ZI_NATURE_TOL(Val(Real),ArrayAnyLength{ty: Real},ArrayAnyLength{ty: Real}, Val(Real), Val(Real), Val(Real)) -> Real;
    }

    ABSDELAY = const {
        fn ABSDELAY_NO_MAX(Val(Real), Val(Real)) -> Real;
        fn ABSDELAY_MAX(Val(Real), Val(Real), Val(Real)) -> Real;
    }

    SLEW = const {
        fn SLEW_NO_MAX(Val(Real)) -> Real;
        fn SLEW_POS_MAX(Val(Real),Val(Real)) -> Real;
        fn SLEW_NEG_MAX(Val(Real),Val(Real),Val(Real)) -> Real;
    }


    TRANSITION = const {
        // Enhancement-47: each signature was one argument SHORT (RISET claimed
        // 2 args, FALLT 3, TOL 4) -- a 3-argument call resolved to FALLT and
        // the lowering read args[3] out of bounds (compiler crash); 4-argument
        // calls only worked by accident through TOL.
        // Enhancement-49: the input is a REAL expression per LRM 4.5.7 (the
        // filter smooths piecewise-constant real waveforms -- the canonical
        // comparator writes `real vcout; ... transition(vcout, td, tr, tf)`);
        // it was typed Integer, rejecting every real-valued input. Integer
        // inputs still work through the standard implicit promotion.
        fn TRANSITION_NO_ARGS(Val(Real)) -> Real;
        fn TRANSITION_DELAY(Val(Real),Val(Real)) -> Real;
        fn TRANSITION_DELAY_RISET(Val(Real),Val(Real),Val(Real)) -> Real;
        fn TRANSITION_DELAY_RISET_FALLT(Val(Real),Val(Real),Val(Real),Val(Real)) -> Real;
        fn TRANSITION_DELAY_RISET_FALLT_TOL(Val(Real),Val(Real),Val(Real),Val(Real),Val(Real)) -> Real;
    }


    LAST_CROSSING = const{
        fn LAST_CROSSING_NO_DIRECTION(Val(Real)) -> Real;
        fn LAST_CROSSING_DIRECTION(Val(Real),Val(Integer)) -> Real;
    }

    fn BASIC_IO(Val(Integer)) -> Integer;

     FOPEN = {
        fn FOPEN_NO_MODE(Val(String)) -> Integer;
        fn FOPEN_MODE(Val(String), Val(String)) -> Integer;
    }

    fn FGETS(Var(String),Val(Integer)) -> Integer;
    fn FSEEK(Val(Integer),Val(Integer),Val(Integer)) -> Integer;

    FFLUSH = {
        fn FFLUSH_ALL() -> Integer;
        fn FFLUSH_DESCRIPTOR(Val(Integer)) -> Integer;
    }

    const fn FERROR(Val(Integer),Var(String)) -> Integer;

    FINISH = {
        fn FINISH_ONE() -> Void;
        fn FINISH_NUM(Val(Integer)) -> Void;
    }

    SIMPARAM = const {
        fn SIMPARAM_NO_DEFAULT(Literal(String)) -> Real;
        fn SIMPARAM_DEFAULT(Literal(String),Val(Real)) -> Real;
    }

    const fn SIMPARAM_STR(Literal(String)) -> String;

    RANDOM = const {
        fn RANDOM_NO_SEED() -> Integer;
        fn RANDOM_SEED(Var(Integer)) -> Integer;
    }

    ARANDOM = const {
        fn ARANDOM_NO_SEED() -> Integer;
        fn ARANDOM_SEED(Var(Integer)) -> Integer;
        fn ARANDOM_SEED_NAME(Var(Integer),Literal(String)) -> Integer;
        fn ARNADOM_CONST_SEED(Param(Integer)) -> Integer;
        fn ARNADOM_CONST_SEED_NAME(Param(Integer),Literal(String)) -> Integer;
    }


    RDIST_1_ARG = const {
        fn RDIST_1_ARG_SEED(Var(Integer),Val(Real)) -> Real;
        fn RDIST_1_ARG_CONST_SEED(Param(Integer),Val(Real)) -> Real;
        fn RDIST_1_ARG_CONST_NAME(Var(Integer),Val(Real),Literal(String)) -> Real;
        fn RDIST_1_ARG_CONST_SEED_NAME(Param(Integer),Val(Real),Literal(String)) -> Real;
    }

    RDIST_2_ARG = const {
        fn RDIST_2_ARG_SEED(Var(Integer),Val(Real),Val(Real)) -> Real;
        fn RDIST_2_ARG_CONST_SEED(Param(Integer),Val(Real),Val(Real)) -> Real;
        fn RDIST_2_ARG_CONST_NAME(Var(Integer),Val(Real),Val(Real),Literal(String)) -> Real;
        fn RDIST_2_ARG_CONST_SEED_NAME(Param(Integer),Val(Real),Val(Real),Literal(String)) -> Real;
    }


    DIST_1_ARG = const {
        fn DIST_1_ARG_SEED(Var(Integer),Val(Integer)) -> Real;
        fn DIST_1_ARG_CONST_SEED(Param(Integer),Val(Integer)) -> Real;
        fn DIST_1_ARG_CONST_NAME(Var(Integer),Val(Integer),Literal(String)) -> Real;
        fn DIST_1_ARG_CONST_SEED_NAME(Param(Integer),Val(Integer),Literal(String)) -> Real;
    }

    DIST_2_ARG = const {
        fn DIST_2_ARG_SEED(Var(Integer),Val(Integer),Val(Integer)) -> Real;
        // Enhancement-49 audit: the middle argument said Val(Real) while every
        // sibling signature says Val(Integer) -- the integer-distribution
        // $dist_* functions take integer parameters per the LRM
        fn DIST_2_ARG_CONST_SEED(Param(Integer),Val(Integer),Val(Integer)) -> Real;
        fn DIST_2_ARG_CONST_NAME(Var(Integer),Val(Integer),Val(Integer),Literal(String)) -> Real;
        fn DIST_2_ARG_CONST_SEED_NAME(Param(Integer),Val(Integer),Val(Integer),Literal(String)) -> Real;
    }

    SIMPROBE = const {
        fn SIMPROBE_NO_DEFAULT(Val(String),Val(String))->Real;
        fn SIMPROBE_DEFAULT(Val(String),Val(String),Val(Real))->Real;
    }

    const fn TEST_PLUSARGS(Val(String)) -> Bool;
    const fn VALUE_PLUSARGS(Val(String),Val(String))->Bool;

    fn ANALOG_NODE_ALIAS(Node,Val(String)) -> Integer;

    const fn PARAM_GIVEN(AnyParam) -> Bool;

    const fn PORT_CONNECTED(Node) -> Bool;

    DISCONTINUITY = {
        fn DISCONTINUITY_NO_DEGREE() -> Void;
        fn DISCONTINUITY_DEGREE(Val(Integer)) -> Void;
    }

    fn BOUND_STEP(Val(Real)) -> Void;
}

const DDX: BuiltinInfo = BuiltinInfo::special_cased_pure(2, Some(2));
pub const DDX_TEMP: Signature = Signature(0);
pub const DDX_POT_DIFF: Signature = Signature(1);
pub const DDX_POT: Signature = Signature(2);
pub const DDX_FLOW: Signature = Signature(3);

const DISPLAY_FUN: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[]), return_ty: Type::Void }],
    true,
);

// Enhancement-40: `$table_model(x1, ..., xn, <data>[, "ctrl"])` is variadic so
// tables of ANY dimension are accepted (the LRM sets no bound; 1-3D were
// previously hard-coded). The listed signatures cover the 1-D inline-array and
// 1..3-D file forms exactly as before; for higher dimensions `infere_builtin`
// synthesises the precise `[Real x n, Literal(String)(, Literal(String))]`
// signature on the fly, and the lowering dispatches on argument SHAPES rather
// than the resolved signature.
const TABLE_MODEL: BuiltinInfo = BuiltinInfo::varargs(
    &[
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), ArrayAnyLength { ty: Real }]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), ArrayAnyLength { ty: Real }, Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), Literal(String), Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), Val(Real), Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), Val(Real), Literal(String), Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[Val(Real), Val(Real), Val(Real), Literal(String)]),
            return_ty: Type::Real,
        },
        SignatureData {
            args: Cow::Borrowed(&[
                Val(Real),
                Val(Real),
                Val(Real),
                Literal(String),
                Literal(String),
            ]),
            return_ty: Type::Real,
        },
    ],
    false,
);

// Enhancement-30: `analysis(arg1, arg2, ...)` accepts a *list* of analysis-name
// strings (LRM 4.7.1) and returns true if the current analysis matches ANY of them.
// It was previously fixed at one argument, so `analysis("ic", "dc")` failed to
// compile. Varargs: at least one string; extra args accepted (typed AnyVal by the
// generic vararg resize). Pure/read-only, so `has_side_effects = false`.
const ANALYSIS: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Val(String)]), return_ty: Type::Integer }],
    false,
);

pub const LIMIT_BUILTIN_FUNCTION: Signature = Signature(0);
pub const LIMIT_USER_FUNCTION: Signature = Signature(1);
pub const LIMIT_NO_ARG: Signature = Signature(2);

const LIMIT: BuiltinInfo = BuiltinInfo::varargs(
    &[
        SignatureData { args: Cow::Borrowed(&[Val(Real), Literal(String)]), return_ty: Type::Real },
        SignatureData { args: Cow::Borrowed(&[Val(Real), Function]), return_ty: Type::Real },
        SignatureData { args: Cow::Borrowed(&[Val(Real)]), return_ty: Type::Real },
    ],
    false,
);
const FDISPLAY_FUN: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Val(Integer)]), return_ty: Type::Void }],
    true,
);
const SWRITE: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Var(String)]), return_ty: Type::Void }],
    true,
);
const SFORMAT: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Var(String), Val(String)]), return_ty: Type::Void }],
    true,
);
// Enhancement-11: `$fscanf(fd, fmt, args...)` and `$sscanf(str, fmt, args...)`
// both RETURN the number of matched conversions (Integer, not the Void that the
// shared FDISPLAY_FUN gave). `$fscanf`'s first arg is the integer descriptor;
// `$sscanf`'s is the input string. The trailing in-out target arguments are
// unconstrained varargs (they keep their `Var(..)` type for the lowering).
const FSCANF_FUN: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Val(Integer)]), return_ty: Type::Integer }],
    true,
);
const SSCANF_FUN: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Val(String)]), return_ty: Type::Integer }],
    true,
);
const FATAL: BuiltinInfo = BuiltinInfo::varargs(
    &[SignatureData { args: Cow::Borrowed(&[Val(Integer)]), return_ty: Type::Void }],
    true,
);

macro_rules! copied_builtins {
    {$($name: ident = $val: ident)*}=> {
        $(const $name: BuiltinInfo = $val;)*
    };
}

copied_builtins! {
    ACOS = REAL_MATH_1
    ACOSH = REAL_MATH_1
    ASIN = REAL_MATH_1
    ASINH = REAL_MATH_1
    ATAN = REAL_MATH_1
    ATANH = REAL_MATH_1
    COS = REAL_MATH_1
    COSH = REAL_MATH_1
    EXP = REAL_MATH_1
    FLOOR = REAL_MATH_1
    LN = REAL_MATH_1
    LOG = REAL_MATH_1
    CLOG2 = INT_MATH_2
    LOG10 = REAL_MATH_1
    CEIL = REAL_MATH_1
    LIMEXP = REAL_MATH_1
    SIN = REAL_MATH_1
    SINH = REAL_MATH_1
    SQRT = REAL_MATH_1
    TAN = REAL_MATH_1
    TANH = REAL_MATH_1

    ATAN2 = REAL_MATH_2
    HYPOT = REAL_MATH_2
    POW = REAL_MATH_2

    NOISE_TABLE_LOG = NOISE_TABLE

    LAPLACE_ND = LAPLACE_FILTER
    LAPLACE_NP = LAPLACE_FILTER
    LAPLACE_ZD = LAPLACE_FILTER
    LAPLACE_ZP = LAPLACE_FILTER

    ZI_ND = ZI_FILTER
    ZI_NP = ZI_FILTER
    ZI_ZD = ZI_FILTER
    ZI_ZP = ZI_FILTER

    // Types are special cased
    MIN = MAX

    DISPLAY = DISPLAY_FUN
    STROBE = DISPLAY_FUN
    MONITOR = DISPLAY_FUN
    WRITE = DISPLAY_FUN
    DEBUG = DISPLAY_FUN
    ERROR = DISPLAY_FUN
    WARNING = DISPLAY_FUN
    INFO = DISPLAY_FUN

    FDISPLAY = FDISPLAY_FUN
    FSTROBE = FDISPLAY_FUN
    FMONITOR = FDISPLAY_FUN
    FWRITE = FDISPLAY_FUN
    FDEBUG = FDISPLAY_FUN
    SSCANF = SSCANF_FUN
    FSCANF = FSCANF_FUN

    REWIND = BASIC_IO
    FEOF = BASIC_IO
    FCLOSE = BASIC_IO
    FTELL = BASIC_IO

    STOP = FINISH

    ABSTIME = REAL_INFO
    TEMPERATURE = REAL_INFO

    RDIST_CHI_SQUARE = RDIST_1_ARG
    RDIST_EXPONENTIAL = RDIST_1_ARG
    RDIST_POISSON = RDIST_1_ARG
    RDIST_T = RDIST_1_ARG

    RDIST_UNIFORM = RDIST_2_ARG
    RDIST_ERLANG = RDIST_2_ARG
    RDIST_NORMAL = RDIST_2_ARG

    DIST_CHI_SQUARE = DIST_1_ARG
    DIST_EXPONENTIAL = DIST_1_ARG
    DIST_POISSON = DIST_1_ARG
    DIST_T = DIST_1_ARG

    DIST_UNIFORM = DIST_2_ARG
    DIST_ERLANG = DIST_2_ARG
    DIST_NORMAL = DIST_2_ARG

    ANALOG_PORT_ALIAS = ANALOG_NODE_ALIAS

    POTENTIAL = FLOW
}
