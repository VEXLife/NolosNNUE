//! NOLOS002: per-intersection directional features, value and policy heads.
use crate::board::DIRS;
use std::sync::OnceLock;

pub const FEATURES: usize = 1 << 18;
pub const CHANNELS: usize = 16;
pub const VALUE_HIDDEN: usize = 32;
pub const MAGIC: &[u8; 8] = b"NOLOS002";
pub const PARAMETERS: usize = FEATURES * CHANNELS
    + CHANNELS
    + CHANNELS * 2
    + 1
    + CHANNELS * 2 * VALUE_HIDDEN
    + VALUE_HIDDEN
    + VALUE_HIDDEN
    + 1;

pub struct Lookup {
    pub canonical: Vec<usize>,
    pub inverse: Vec<usize>,
}

pub fn lookup() -> &'static Lookup {
    static TABLE: OnceLock<Lookup> = OnceLock::new();
    TABLE.get_or_init(|| {
        let canonical: Vec<_> = (0..FEATURES)
            .map(|id| {
                let reversed = (0..9).fold(0, |v, i| v | (((id >> (2 * i)) & 3) << (2 * (8 - i))));
                id.min(reversed)
            })
            .collect();
        let inverse = (0..FEATURES)
            .map(|id| {
                let swapped = (0..9).fold(0, |v, i| {
                    let cell = (id >> (2 * i)) & 3;
                    v | (match cell {
                        1 => 2,
                        2 => 1,
                        other => other,
                    } << (2 * i))
                });
                canonical[swapped]
            })
            .collect();
        Lookup { canonical, inverse }
    })
}

#[derive(Clone)]
pub struct SpatialNetwork {
    pub embedding: Vec<f32>,
    pub local_bias: [f32; CHANNELS],
    pub policy: [f32; CHANNELS * 2],
    pub policy_bias: f32,
    pub value_in: Vec<f32>,
    pub value_bias: [f32; VALUE_HIDDEN],
    pub value_out: [f32; VALUE_HIDDEN],
    pub value_out_bias: f32,
}

impl SpatialNetwork {
    pub fn from_values(values: &[f32]) -> Self {
        let mut k = FEATURES * CHANNELS;
        let embedding = values[..k].to_vec();
        let local_bias = values[k..k + CHANNELS].try_into().unwrap();
        k += CHANNELS;
        let policy = values[k..k + CHANNELS * 2].try_into().unwrap();
        k += CHANNELS * 2;
        let policy_bias = values[k];
        k += 1;
        let value_in = values[k..k + CHANNELS * 2 * VALUE_HIDDEN].to_vec();
        k += CHANNELS * 2 * VALUE_HIDDEN;
        let value_bias = values[k..k + VALUE_HIDDEN].try_into().unwrap();
        k += VALUE_HIDDEN;
        let value_out = values[k..k + VALUE_HIDDEN].try_into().unwrap();
        k += VALUE_HIDDEN;
        Self {
            embedding,
            local_bias,
            policy,
            policy_bias,
            value_in,
            value_bias,
            value_out,
            value_out_bias: values[k],
        }
    }
}

#[derive(Clone)]
pub struct SpatialState {
    pub patterns: Vec<[usize; 4]>,
    pub black: Vec<[f32; CHANNELS]>,
    pub white: Vec<[f32; CHANNELS]>,
    pub black_sum: [f32; CHANNELS],
    pub white_sum: [f32; CHANNELS],
}

impl SpatialState {
    pub fn new(cells: &[u8], size: usize, net: &SpatialNetwork) -> Self {
        let mut state = Self {
            patterns: vec![[0; 4]; cells.len()],
            black: vec![net.local_bias; cells.len()],
            white: vec![net.local_bias; cells.len()],
            black_sum: [0.0; CHANNELS],
            white_sum: [0.0; CHANNELS],
        };
        let table = lookup();
        for p in 0..cells.len() {
            let (x, y) = ((p % size) as isize, (p / size) as isize);
            for (d, (dx, dy)) in DIRS.iter().enumerate() {
                let mut id = 0;
                for k in -4isize..=4 {
                    let (xx, yy) = (x + dx * k, y + dy * k);
                    let cell = if xx < 0 || yy < 0 || xx >= size as isize || yy >= size as isize {
                        3
                    } else {
                        cells[yy as usize * size + xx as usize] as usize
                    };
                    id |= cell << (2 * (k + 4));
                }
                state.patterns[p][d] = id;
                let black = table.canonical[id] * CHANNELS;
                let white = table.inverse[id] * CHANNELS;
                for h in 0..CHANNELS {
                    state.black[p][h] += net.embedding[black + h] * 0.5;
                    state.white[p][h] += net.embedding[white + h] * 0.5;
                }
            }
            for h in 0..CHANNELS {
                state.black_sum[h] += state.black[p][h].max(0.0);
                state.white_sum[h] += state.white[p][h].max(0.0);
            }
        }
        state
    }

    pub fn update(
        &mut self,
        affected: &[(usize, usize, usize)],
        centers: &[usize],
        color: u8,
        net: &SpatialNetwork,
    ) {
        for p in centers {
            for h in 0..CHANNELS {
                self.black_sum[h] -= self.black[*p][h].max(0.0);
                self.white_sum[h] -= self.white[*p][h].max(0.0);
            }
        }
        let table = lookup();
        for &(p, d, shift) in affected {
            let old = self.patterns[p][d];
            let new = (old & !(3 << shift)) | ((color as usize) << shift);
            let (ob, nb, ow, nw) = (
                table.canonical[old] * CHANNELS,
                table.canonical[new] * CHANNELS,
                table.inverse[old] * CHANNELS,
                table.inverse[new] * CHANNELS,
            );
            for h in 0..CHANNELS {
                self.black[p][h] += (net.embedding[nb + h] - net.embedding[ob + h]) * 0.5;
                self.white[p][h] += (net.embedding[nw + h] - net.embedding[ow + h]) * 0.5;
            }
            self.patterns[p][d] = new;
        }
        for p in centers {
            for h in 0..CHANNELS {
                self.black_sum[h] += self.black[*p][h].max(0.0);
                self.white_sum[h] += self.white[*p][h].max(0.0);
            }
        }
    }

    pub fn value(&self, side: u8, net: &SpatialNetwork) -> i32 {
        let (own, opponent) = if side == 1 {
            (&self.black_sum, &self.white_sum)
        } else {
            (&self.white_sum, &self.black_sum)
        };
        let normalizer = self.patterns.len() as f32;
        let mut value = net.value_out_bias;
        for h in 0..VALUE_HIDDEN {
            let mut hidden = net.value_bias[h];
            for c in 0..CHANNELS {
                hidden += (own[c] * net.value_in[h * CHANNELS * 2 + c]
                    + opponent[c] * net.value_in[h * CHANNELS * 2 + CHANNELS + c])
                    / normalizer;
            }
            value += hidden.max(0.0) * net.value_out[h];
        }
        (value * 600.0).round() as i32
    }

    pub fn policy(&self, p: usize, side: u8, net: &SpatialNetwork) -> f32 {
        let (own, opponent) = if side == 1 {
            (&self.black[p], &self.white[p])
        } else {
            (&self.white[p], &self.black[p])
        };
        let mut value = net.policy_bias;
        for c in 0..CHANNELS {
            value +=
                own[c].max(0.0) * net.policy[c] + opponent[c].max(0.0) * net.policy[CHANNELS + c];
        }
        value
    }
}
