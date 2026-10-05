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
    pub quantized: Option<Arc<crate::quantized::QuantizedNetwork>>,
    pub embedding: Vec<f32>,
    pub bias: [f32; HIDDEN],
    pub head: [f32; HIDDEN],
    pub tempo: f32,
    pub spatial: Option<crate::spatial::SpatialNetwork>,
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
        if bytes.len() >= 8 && &bytes[..8] == crate::spatial::MAGIC {
            let expected = 28 + crate::spatial::PARAMETERS * 4;
            if bytes.len() != expected {
                return Err("invalid NOLOS002 length".into());
            }
            let at = |i| u32::from_le_bytes(bytes[i..i + 4].try_into().unwrap());
            if at(8) != crate::spatial::FEATURES as u32
                || at(12) != crate::spatial::CHANNELS as u32
                || f32::from_bits(at(16)) != 1.0
                || f32::from_bits(at(20)) != SCALE
            {
                return Err("incompatible spatial architecture".into());
            }
            if at(24) != checksum(&bytes[28..]) {
                return Err("network checksum mismatch".into());
            }
            let values: Vec<_> = bytes[28..]
                .as_chunks::<4>()
                .0
                .iter()
                .map(|b| f32::from_le_bytes(*b))
                .collect();
            if values.iter().any(|v| !v.is_finite() || v.abs() > 1000.0) {
                return Err("non-finite or out-of-range network parameters".into());
            }
            return Ok(Arc::new(Self {
                quantized: None,
                embedding: Vec::new(),
                bias: [0.0; HIDDEN],
                head: [0.0; HIDDEN],
                tempo: 0.0,
                spatial: Some(crate::spatial::SpatialNetwork::from_values(&values)),
            }));
        }
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
            quantized: None,
            embedding: values[..k].to_vec(),
            bias: values[k..k + HIDDEN].try_into().unwrap(),
            head: values[k + HIDDEN..k + 2 * HIDDEN].try_into().unwrap(),
            tempo: values[k + 2 * HIDDEN],
            spatial: None,
        }))
    }

    pub fn with_precision(self: &Arc<Self>, precision: &str) -> Result<Arc<Self>, String> {
        let quantized = match precision {
            "fp32" => None,
            "int16" => Some(Arc::new(crate::quantized::QuantizedNetwork::new(self)?)),
            _ => return Err("precision must be fp32 or int16".into()),
        };
        let mut net = (**self).clone();
        net.quantized = quantized;
        Ok(Arc::new(net))
    }

    pub fn value(&self, black: &[f32; HIDDEN], white: &[f32; HIDDEN], side: u8) -> i32 {
        let mut value = 0.0;
        for i in 0..HIDDEN {
            value += (black[i].clamp(0.0, 1.0) - white[i].clamp(0.0, 1.0)) * self.head[i];
        }
        if side == 2 {
            value = -value;
        }
        ((value + self.tempo) * SCALE).round() as i32
    }
}

#[cfg(test)]
mod value_limit_tests {
    use super::*;
    #[test]
    fn neural_values_expose_large_predictions_for_both_colors_and_tempo() {
        let mut network = Network {
            quantized: None,
            embedding: vec![], bias: [0.0; HIDDEN], head: [10.0; HIDDEN],
            tempo: 0.0, spatial: None,
        };
        assert_eq!(network.value(&[1.0; HIDDEN], &[0.0; HIDDEN], 1), 192000);
        assert_eq!(network.value(&[1.0; HIDDEN], &[0.0; HIDDEN], 2), -192000);
        network.tempo = -100.0;
        assert_eq!(network.value(&[0.0; HIDDEN], &[0.0; HIDDEN], 1), -60000);
    }
}
