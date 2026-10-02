use std::sync::Arc;

pub const FEATURES: usize = 4096;
pub const HIDDEN: usize = 32;
pub const NORMALIZER: f32 = 32.0;
pub const SCALE: f32 = 600.0;
pub const MAGIC: &[u8; 8] = b"NOLOS001";

/// Six-cell directional pattern embedding -> clipped ReLU -> antisymmetric value.
/// No pretrained parameters are embedded in the engine.
#[derive(Clone)]
pub struct Network {
    pub embedding: Vec<f32>,
    pub bias: [f32; HIDDEN],
    pub head: [f32; HIDDEN],
    pub tempo: f32,
}

pub fn canonical(id: usize) -> usize {
    let reversed = (0..6).fold(0, |v, i| v | (((id >> (i * 2)) & 3) << ((5 - i) * 2)));
    id.min(reversed)
}

pub fn invert(mut id: usize) -> usize {
    let mut out = 0;
    for i in 0..6 {
        let cell = id & 3;
        out |= (if cell == 1 {
            2
        } else if cell == 2 {
            1
        } else {
            cell
        }) << (2 * i);
        id >>= 2;
    }
    canonical(out)
}

fn checksum(bytes: &[u8]) -> u32 {
    bytes
        .iter()
        .fold(2166136261u32, |h, b| (h ^ *b as u32).wrapping_mul(16777619))
}

impl Network {
    pub fn load(bytes: &[u8]) -> Result<Arc<Self>, String> {
        // Header: magic, feature count, hidden count, normalization, scale, payload checksum.
        let expected = 28 + (FEATURES * HIDDEN + HIDDEN * 2 + 1) * 4;
        if bytes.len() != expected || &bytes[..8] != MAGIC {
            return Err("invalid NOLOS001 network length or magic".into());
        }
        let u32_at = |i| u32::from_le_bytes(bytes[i..i + 4].try_into().unwrap());
        if u32_at(8) != FEATURES as u32
            || u32_at(12) != HIDDEN as u32
            || f32::from_bits(u32_at(16)) != NORMALIZER
            || f32::from_bits(u32_at(20)) != SCALE
        {
            return Err("incompatible feature architecture".into());
        }
        if u32_at(24) != checksum(&bytes[28..]) {
            return Err("network checksum mismatch".into());
        }
        let values: Vec<f32> = bytes[28..]
            .as_chunks::<4>()
            .0
            .iter()
            .map(|b| f32::from_le_bytes(*b))
            .collect();
        if values.iter().any(|v| !v.is_finite() || v.abs() > 1000.0) {
            return Err("non-finite or out-of-range network parameters".into());
        }
        let k = FEATURES * HIDDEN;
        Ok(Arc::new(Self {
            embedding: values[..k].to_vec(),
            bias: values[k..k + HIDDEN].try_into().unwrap(),
            head: values[k + HIDDEN..k + 2 * HIDDEN].try_into().unwrap(),
            tempo: values[k + 2 * HIDDEN],
        }))
    }

    pub fn value(&self, black: &[f32; HIDDEN], white: &[f32; HIDDEN], side: u8) -> i32 {
        let mut value = 0.0;
        for i in 0..HIDDEN {
            value += (black[i].clamp(0.0, 1.0) - white[i].clamp(0.0, 1.0)) * self.head[i];
        }
        if side == 2 {
            value = -value;
        }
        ((value + self.tempo) * SCALE)
            .round()
            .clamp(-12000.0, 12000.0) as i32
    }
}
