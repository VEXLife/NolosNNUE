//! Optional NOLOS001 int16 embeddings and exact int32 accumulators.
use crate::network::{Network, FEATURES, HIDDEN};

const MAX_UNIT: i32 = 262144;

#[derive(Clone)]
pub struct QuantizedNetwork {
    pub embedding: Vec<i16>,
    pub unit: i32,
    pub bias: [i32; HIDDEN],
}

impl QuantizedNetwork {
    pub fn new(net: &Network) -> Result<Self, String> {
        if net.spatial.is_some() || net.embedding.len() != FEATURES * HIDDEN {
            return Err("int16 precision requires a NOLOS001 network".into());
        }
        let mut unit = MAX_UNIT;
        let max_weight = net.embedding.iter().map(|v| v.abs()).fold(0.0f32, f32::max);
        while max_weight * (unit as f32 / 32.0) > i16::MAX as f32 {
            unit /= 2;
        }
        if unit == 0 {
            return Err("embedding exceeds quantization range".into());
        }
        let embedding_scale = unit as f32 / 32.0;
        let mut embedding = Vec::with_capacity(net.embedding.len());
        for value in &net.embedding {
            let q = (*value * embedding_scale).round();
            if !q.is_finite() || q < i16::MIN as f32 || q > i16::MAX as f32 {
                return Err("embedding exceeds int16 quantization range".into());
            }
            embedding.push(q as i16);
        }
        // Fewer than 2600 windows bound the embedding sum below 86 million.
        // Bias contributes at most 263 million: the total safely fits i32.
        if net.bias.iter().any(|b| !b.is_finite() || b.abs() > 1000.0) {
            return Err("bias exceeds int32 quantization range".into());
        }
        Ok(Self {
            embedding,
            unit,
            bias: net.bias.map(|v| (v * unit as f32).round() as i32),
        })
    }
}

#[derive(Clone)]
pub(crate) struct State {
    pub black: [i32; HIDDEN],
    pub white: [i32; HIDDEN],
}

impl State {
    pub fn new(net: &QuantizedNetwork, counts: &[u16], inverse: &[usize]) -> Self {
        let mut state = Self {
            black: net.bias,
            white: net.bias,
        };
        for (id, n) in counts.iter().enumerate().filter(|(_, n)| **n > 0) {
            for h in 0..HIDDEN {
                state.black[h] += i32::from(*n) * i32::from(net.embedding[id * HIDDEN + h]);
                state.white[h] +=
                    i32::from(*n) * i32::from(net.embedding[inverse[id] * HIDDEN + h]);
            }
        }
        state
    }

    pub fn value(&self, net: &Network, side: u8) -> i32 {
        let unit = net.quantized.as_ref().unwrap().unit;
        let mut products = [0.0; HIDDEN];
        #[cfg(target_arch = "x86_64")]
        if std::is_x86_feature_detected!("avx2") {
            // Fixed-size arrays and runtime detection cover all vector loads.
            unsafe { products_avx2(self, &net.head, unit, &mut products) };
        } else {
            products_scalar(self, &net.head, unit, &mut products);
        }
        #[cfg(not(target_arch = "x86_64"))]
        products_scalar(self, &net.head, unit, &mut products);
        // Preserve the scalar reduction order to isolate quantization error.
        let mut value = 0.0;
        for product in products {
            value += product;
        }
        if side == 2 {
            value = -value;
        }
        ((value + net.tempo) * crate::network::SCALE).round() as i32
    }
}

fn products_scalar(state: &State, head: &[f32; HIDDEN], unit: i32, out: &mut [f32; HIDDEN]) {
    for i in 0..HIDDEN {
        let delta = state.black[i].clamp(0, unit) - state.white[i].clamp(0, unit);
        out[i] = delta as f32 * (1.0 / unit as f32) * head[i];
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn products_avx2(state: &State, head: &[f32; HIDDEN], unit: i32, out: &mut [f32; HIDDEN]) {
    use std::arch::x86_64::*;
    let zero = _mm256_setzero_si256();
    let ceiling = _mm256_set1_epi32(unit);
    let scale = _mm256_set1_ps(1.0 / unit as f32);
    for i in (0..HIDDEN).step_by(8) {
        let black = _mm256_min_epi32(
            ceiling,
            _mm256_max_epi32(zero, _mm256_loadu_si256(state.black.as_ptr().add(i).cast())),
        );
        let white = _mm256_min_epi32(
            ceiling,
            _mm256_max_epi32(zero, _mm256_loadu_si256(state.white.as_ptr().add(i).cast())),
        );
        let delta = _mm256_cvtepi32_ps(_mm256_sub_epi32(black, white));
        let product = _mm256_mul_ps(
            _mm256_mul_ps(delta, scale),
            _mm256_loadu_ps(head.as_ptr().add(i)),
        );
        _mm256_storeu_ps(out.as_mut_ptr().add(i), product);
    }
}

#[inline]
pub(crate) fn update_pair(
    state: &mut State,
    net: &QuantizedNetwork,
    nb: usize,
    ob: usize,
    nw: usize,
    ow: usize,
) {
    let rows = net.embedding.as_chunks::<HIDDEN>().0;
    let (nb, ob, nw, ow) = (&rows[nb], &rows[ob], &rows[nw], &rows[ow]);
    #[cfg(target_arch = "x86_64")]
    if std::is_x86_feature_detected!("avx2") {
        // Each row is exactly HIDDEN elements, and AVX2 is available.
        unsafe { pair_avx2(state, nb, ob, nw, ow) };
        return;
    }
    for h in 0..HIDDEN {
        state.black[h] += i32::from(nb[h]) - i32::from(ob[h]);
        state.white[h] += i32::from(nw[h]) - i32::from(ow[h]);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn pair_avx2(
    state: &mut State,
    nb: &[i16; HIDDEN],
    ob: &[i16; HIDDEN],
    nw: &[i16; HIDDEN],
    ow: &[i16; HIDDEN],
) {
    update_avx2(&mut state.black, nb, ob);
    update_avx2(&mut state.white, nw, ow);
}

#[cfg(test)]
#[inline]
pub(crate) fn update(acc: &mut [i32; HIDDEN], new: &[i16], old: &[i16]) {
    assert!(new.len() >= HIDDEN && old.len() >= HIDDEN);
    #[cfg(target_arch = "x86_64")]
    if std::is_x86_feature_detected!("avx2") {
        // Checked slices and runtime CPU detection make these unaligned loads safe.
        unsafe { update_avx2(acc, new, old) };
        return;
    }
    for h in 0..HIDDEN {
        acc[h] += i32::from(new[h]) - i32::from(old[h]);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn update_avx2(acc: &mut [i32; HIDDEN], new: &[i16], old: &[i16]) {
    use std::arch::x86_64::*;
    for h in (0..HIDDEN).step_by(8) {
        let n = _mm256_cvtepi16_epi32(_mm_loadu_si128(new.as_ptr().add(h).cast()));
        let o = _mm256_cvtepi16_epi32(_mm_loadu_si128(old.as_ptr().add(h).cast()));
        let a = _mm256_loadu_si256(acc.as_ptr().add(h).cast());
        _mm256_storeu_si256(
            acc.as_mut_ptr().add(h).cast(),
            _mm256_add_epi32(a, _mm256_sub_epi32(n, o)),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Rule};
    use std::sync::Arc;

    #[test]
    fn wide_deltas_and_incremental_rebuild_are_exact() {
        let mut acc = [123456; HIDDEN];
        update(&mut acc, &[i16::MAX; HIDDEN], &[i16::MIN; HIDDEN]);
        assert_eq!(acc, [188991; HIDDEN]);
        let net = Arc::new(Network {
            quantized: None,
            spatial: None,
            embedding: (0..FEATURES * HIDDEN)
                .map(|i| ((i * 37 % 101) as f32 - 50.0) * 0.01)
                .collect(),
            bias: [0.4; HIDDEN],
            head: [0.2; HIDDEN],
            tempo: 0.01,
        })
        .with_precision("int16")
        .unwrap();
        for size in [5, 9, 15, 20] {
            let mut b = Board::new(size, Rule::Freestyle).unwrap();
            b.set_network(Some(net.clone()));
            let initial = b.evaluate(1);
            for k in 0..size * 2 {
                let p = k * 7 % (size * size);
                if b.cells[p] != 0 {
                    continue;
                }
                b.make(p, (k % 2 + 1) as u8);
                let mut rebuilt = b.clone();
                rebuilt.rebuild_accumulators();
                assert_eq!(b.evaluate(1), rebuilt.evaluate(1));
                let expected = State::new(
                    net.quantized.as_ref().unwrap(),
                    &b.counts,
                    &(0..FEATURES)
                        .map(crate::network::invert)
                        .collect::<Vec<_>>(),
                );
                let snapshot = b.evaluate(1);
                assert_eq!(snapshot, expected.value(&net, 1));
                assert_eq!(b.evaluate(2), expected.value(&net, 2));
            }
            while !b.history.is_empty() {
                b.undo();
            }
            assert_eq!(b.evaluate(1), initial);
            assert!(net.with_precision("fp32").unwrap().quantized.is_none());
        }
        let state = State {
            black: std::array::from_fn(|i| (i as i32 - 16) * 20000),
            white: std::array::from_fn(|i| (16 - i as i32) * 30000),
        };
        let mut expected = [0.0; HIDDEN];
        products_scalar(
            &state,
            &net.head,
            net.quantized.as_ref().unwrap().unit,
            &mut expected,
        );
        #[cfg(target_arch = "x86_64")]
        if std::is_x86_feature_detected!("avx2") {
            let mut actual = [0.0; HIDDEN];
            unsafe {
                products_avx2(
                    &state,
                    &net.head,
                    net.quantized.as_ref().unwrap().unit,
                    &mut actual,
                );
            }
            assert_eq!(expected.map(f32::to_bits), actual.map(f32::to_bits));
        }
        let mut invalid = (*net).clone();
        invalid.embedding[0] = f32::NAN;
        assert!(QuantizedNetwork::new(&invalid).is_err());
    }
}
