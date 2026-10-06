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
    #[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
    if N % 4 == 0 {
        // Full four-lane blocks are in bounds; SIMD keeps the scalar operation order.
        unsafe { wasm_simd(acc, new, old, scale) };
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

#[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
#[inline]
unsafe fn wasm_simd<const N: usize>(acc: &mut [f32; N], new: &[f32], old: &[f32], scale: f32) {
    use std::arch::wasm32::*;
    let scale = f32x4_splat(scale);
    for i in (0..N).step_by(4) {
        let delta = f32x4_sub(
            v128_load(new.as_ptr().add(i).cast()),
            v128_load(old.as_ptr().add(i).cast()),
        );
        let value = f32x4_add(
            v128_load(acc.as_ptr().add(i).cast()),
            f32x4_mul(delta, scale),
        );
        v128_store(acc.as_mut_ptr().add(i).cast(), value);
    }
}

/// Vectorize per-lane activation/products without changing the FP32 sum order.
#[inline]
pub(crate) fn clipped_dot<const N: usize>(black: &[f32; N], white: &[f32; N], head: &[f32; N]) -> f32 {
    #[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
    if N % 4 == 0 {
        return unsafe { wasm_clipped_dot(black, white, head) };
    }
    let mut value = 0.0;
    for i in 0..N {
        value += (black[i].clamp(0.0, 1.0) - white[i].clamp(0.0, 1.0)) * head[i];
    }
    value
}

#[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
#[inline]
unsafe fn wasm_clipped_dot<const N: usize>(black: &[f32; N], white: &[f32; N], head: &[f32; N]) -> f32 {
    use std::arch::wasm32::*;
    let zero = f32x4_splat(0.0);
    let one = f32x4_splat(1.0);
    // Compare/select implements scalar clamp, including signed zero and NaN.
    let clamp = |v| {
        let v = v128_bitselect(zero, v, f32x4_lt(v, zero));
        v128_bitselect(one, v, f32x4_gt(v, one))
    };
    let mut value = 0.0;
    for i in (0..N).step_by(4) {
        let b = clamp(v128_load(black.as_ptr().add(i).cast()));
        let w = clamp(v128_load(white.as_ptr().add(i).cast()));
        let products = f32x4_mul(f32x4_sub(b, w), v128_load(head.as_ptr().add(i).cast()));
        value += f32x4_extract_lane::<0>(products);
        value += f32x4_extract_lane::<1>(products);
        value += f32x4_extract_lane::<2>(products);
        value += f32x4_extract_lane::<3>(products);
    }
    value
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
