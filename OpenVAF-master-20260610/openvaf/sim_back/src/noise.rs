use lasso::Spur;
use mir::Value;
use stdx::Ieee64;

use crate::dae::SimUnknown;

#[derive(Debug, Clone)]
pub enum NoiseSourceKind {
    WhiteNoise { pwr: Value },
    FlickerNoise { pwr: Value, exp: Value },
    NoiseTable { log: bool, vals: Box<[(Ieee64, Ieee64)]> },
    /// `ac_stim` small-signal stimulus (Enhancement-51): rides the noise
    /// extraction pipeline (same branch/factor machinery) and is partitioned
    /// into its own OSDI descriptor array. `name` here is the ANALYSIS name.
    AcStim { mag: Value, phase: Value },
}

#[derive(Debug)]
pub struct NoiseSource {
    pub name: Spur,
    pub kind: NoiseSourceKind,
    pub hi: SimUnknown,
    pub lo: Option<SimUnknown>,
    pub factor: Value,
    /// Enhancement-54: coefficient of the j*omega part of the signal factor.
    /// A noise wave routed through ddt() carries factor `factor + j*omega *
    /// factor_react`; keeping it as a factor (instead of synthesizing an extra
    /// internal unknown) keeps the matrix small. `F_ZERO` for plain sources.
    pub factor_react: Value,
}

impl NoiseSource {
    pub fn map_vals(&mut self, mut f: impl FnMut(Value) -> Value) {
        self.factor = f(self.factor);
        self.factor_react = f(self.factor_react);
        match &mut self.kind {
            NoiseSourceKind::WhiteNoise { pwr } => *pwr = f(*pwr),
            NoiseSourceKind::FlickerNoise { pwr, exp } => {
                *pwr = f(*pwr);
                *exp = f(*exp);
            }
            NoiseSourceKind::NoiseTable { .. } => (),
            NoiseSourceKind::AcStim { mag, phase } => {
                *mag = f(*mag);
                *phase = f(*phase);
            }
        }
    }
}
