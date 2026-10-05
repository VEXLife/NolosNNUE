//! Exact lane-wise accumulator updates; no FMA or reordered reductions.
#[inline]
pub(crate) fn update<const N: usize>(acc: &mut [f32; N], new: &[f32], old: &[f32], scale: f32) {
    assert!(new.len() >= N && old.len() >= N);
    #[cfg(target_arch = "x86_64")]
    if N % 8 == 0 && std::is_x86_feature_detected!("avx") {
        // Runtime detection guarantees AVX support; bounds checked above.
        unsafe { avx(acc, new, old, scale) };
        return;
    }
    scalar(acc, new, old, scale);
}

#[inline]
fn scalar<const N: usize>(acc: &mut [f32; N], new: &[f32], old: &[f32], scale: f32) {
    for i in 0..N {
        acc[i] += (new[i] - old[i]) * scale;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx")]
unsafe fn avx<const N: usize>(acc: &mut [f32; N], new: &[f32], old: &[f32], scale: f32) {
    use std::arch::x86_64::*;
    let scale = _mm256_set1_ps(scale);
    for i in (0..N).step_by(8) {
        let delta = _mm256_sub_ps(
            _mm256_loadu_ps(new.as_ptr().add(i)),
            _mm256_loadu_ps(old.as_ptr().add(i)),
        );
        let value = _mm256_add_ps(
            _mm256_loadu_ps(acc.as_ptr().add(i)),
            _mm256_mul_ps(delta, scale),
        );
        _mm256_storeu_ps(acc.as_mut_ptr().add(i), value);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dispatched_updates_match_scalar_bits() {
        let mut seed = 17u32;
        let mut next = || {
            seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
            (seed as i32 as f32) / 2147483648.0
        };
        let mut expected = [0.0; 32];
        let mut actual = expected;
        for scale in [1.0 / 32.0, 0.5] {
            for _ in 0..1000 {
                let new: [f32; 32] = std::array::from_fn(|_| next());
                let old: [f32; 32] = std::array::from_fn(|_| next());
                scalar(&mut expected, &new, &old, scale);
                update(&mut actual, &new, &old, scale);
                assert_eq!(actual.map(f32::to_bits), expected.map(f32::to_bits));
            }
        }
        let mut short = [0.0; 7];
        update(&mut short, &[1.0; 7], &[0.0; 7], 0.5);
        assert_eq!(short, [0.5; 7]);
    }
}
