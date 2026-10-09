use crate::network::{canonical, invert, Network, FEATURES, HIDDEN, NORMALIZER};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

pub const DIRS: [(isize, isize); 4] = [(1, 0), (0, 1), (1, 1), (1, -1)];
type WinMasks = [[u8; 2]; 2];
// Four directions, at most five dependent centers on either side.
type WinUndo = [WinMasks; 40];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rule {
    Freestyle,
    Standard,
    Renju,
}

impl Rule {
    pub fn from_id(id: i32) -> Result<Self, String> {
        match id {
            0 => Ok(Self::Freestyle),
            1 => Ok(Self::Standard),
            2 => Ok(Self::Renju),
            _ => Err("supported Yixin rules: 0=freestyle, 1=standard, 2=renju".into()),
        }
    }
    pub fn id(self) -> u8 {
        match self {
            Self::Freestyle => 0,
            Self::Standard => 1,
            Self::Renju => 2,
        }
    }
}

#[derive(Clone)]
struct Geometry {
    windows: Vec<[i16; 6]>,
    affected: Vec<Vec<(usize, usize)>>,
    scores: Vec<i32>,
    canonical: Vec<usize>,
    inverse: Vec<usize>,
    neighbors: Vec<Vec<usize>>,
    local_affected: Vec<Vec<(usize, usize, usize)>>,
    local_centers: Vec<Vec<usize>>,
    // Five neighbors each way suffice to distinguish five from an overline.
    win_rays: Vec<[[[i16; 5]; 2]; 4]>,
    win_dependents: Vec<Vec<(usize, usize)>>,
}

#[derive(Clone)]
pub struct Board {
    pub size: usize,
    pub cells: Vec<u8>,
    pub history: Vec<(usize, u8)>,
    pub rule: Rule,
    pub counts: Vec<u16>,
    pub hash: u64,
    geometry: Arc<Geometry>,
    patterns: Vec<usize>,
    /// Per cell and color: windows whose pattern makes the cell a four candidate.
    four_counts: Vec<[u8; 2]>,
    neighbor_counts: Vec<u8>,
    // Radius-two coverage, including occupied cells so raw tactical probes
    // can still filter against the current cells without mutating this set.
    candidate_bits: [u64; 7],
    // Per color: directional bits for >=5 and exactly 5. Keep both so a
    // protocol rule change never invalidates the geometric cache.
    win_masks: Vec<WinMasks>,
    win_undo: Vec<WinUndo>,
    win_cache_enabled: bool,
    pub hce: i32,
    pub network: Option<Arc<Network>>,
    spatial_state: Option<crate::spatial::SpatialState>,
    quantized_state: Option<Box<crate::quantized::State>>,
    pub black_acc: [f32; HIDDEN],
    pub white_acc: [f32; HIDDEN],
}

pub fn mix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9e3779b97f4a7c15);
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}

fn pattern_score(id: usize) -> i32 {
    let cells: Vec<u8> = (0..6).map(|i| ((id >> (i * 2)) & 3) as u8).collect();
    let score = |color| {
        let mut v = 0;
        for offset in 0..2 {
            let slice = &cells[offset..offset + 5];
            if slice.iter().all(|c| *c == 0 || *c == color) {
                let n = slice.iter().filter(|c| **c == color).count();
                v += [0, 1, 12, 120, 2400, 0][n];
            }
        }
        if cells[0] == 0 && cells[5] == 0 && cells[1..5].iter().all(|c| *c == color) {
            v += 24000;
        }
        for start in 0..2 {
            if cells[start] == 0
                && cells[start + 4] == 0
                && cells[start + 1..start + 4].iter().all(|c| *c == color)
            {
                v += 1400;
            }
        }
        v
    };
    score(1) - score(2)
}

fn four_masks() -> &'static [[u8; 2]] {
        static MASKS: std::sync::OnceLock<Vec<[u8; 2]>> = std::sync::OnceLock::new();
        MASKS.get_or_init(|| (0..FEATURES).map(|id| {
            let mut masks = [0; 2];
            for color in 1..=2 {
                for offset in 0..=1 {
                    let mut stones = 0;
                    let mut empty = 0;
                    let mut blocked = false;
                    for j in offset..offset + 5 {
                        let c = (id >> (j * 2)) & 3;
                        if c == color { stones += 1; }
                        else if c == 0 { empty |= 1 << j; }
                        else { blocked = true; }
                    }
                    if !blocked && stones >= 3 { masks[color - 1] |= empty; }
                }
            }
            masks
        }).collect()).as_slice()
}

impl Board {
    pub fn new(size: usize, rule: Rule) -> Result<Self, String> {
        if !(5..=20).contains(&size) {
            return Err("board size must be 5..20".into());
        }
        let mut windows = Vec::new();
        for (dx, dy) in DIRS {
            for y in 0..size {
                for x in 0..size {
                    let px = x as isize - dx;
                    let py = y as isize - dy;
                    if px >= 0 && py >= 0 && px < size as isize && py < size as isize {
                        continue;
                    }
                    let mut line = Vec::new();
                    let (mut xx, mut yy) = (x as isize, y as isize);
                    while xx >= 0 && yy >= 0 && xx < size as isize && yy < size as isize {
                        line.push((yy as usize * size + xx as usize) as i16);
                        xx += dx;
                        yy += dy;
                    }
                    if line.len() < 5 {
                        continue;
                    }
                    // Boundary token 3 is preserved under color inversion.
                    for start in -5isize..line.len() as isize {
                        let mut w = [-1; 6];
                        for (j, p) in w.iter_mut().enumerate() {
                            let k = start + j as isize;
                            if k >= 0 && k < line.len() as isize {
                                *p = line[k as usize];
                            }
                        }
                        windows.push(w);
                    }
                }
            }
        }
        let mut affected = vec![Vec::new(); size * size];
        for (i, w) in windows.iter().enumerate() {
            for (j, p) in w.iter().enumerate() {
                if *p >= 0 {
                    affected[*p as usize].push((i, 2 * j));
                }
            }
        }
        let patterns: Vec<usize> = windows
            .iter()
            .map(|w| {
                w.iter()
                    .enumerate()
                    .fold(0, |id, (j, p)| id | if *p < 0 { 3 << (2 * j) } else { 0 })
            })
            .collect();
        let mut counts = vec![0; FEATURES];
        for id in &patterns {
            counts[canonical(*id)] += 1;
        }
        let scores = (0..FEATURES).map(pattern_score).collect();
        let neighbors = (0..size * size)
            .map(|p| {
                let (x, y) = (p % size, p / size);
                let mut nearby = Vec::new();
                for yy in y.saturating_sub(2)..=(y + 2).min(size - 1) {
                    for xx in x.saturating_sub(2)..=(x + 2).min(size - 1) {
                        nearby.push(yy * size + xx);
                    }
                }
                nearby
            })
            .collect();
        let mut local_affected = vec![Vec::new(); size * size];
        for center in 0..size * size {
            for (direction, (dx, dy)) in DIRS.iter().enumerate() {
                for offset in -4isize..=4 {
                    let x = (center % size) as isize + dx * offset;
                    let y = (center / size) as isize + dy * offset;
                    if x >= 0 && y >= 0 && x < size as isize && y < size as isize {
                        local_affected[y as usize * size + x as usize].push((
                            center,
                            direction,
                            (offset + 4) as usize * 2,
                        ));
                    }
                }
            }
        }
        let local_centers = local_affected
            .iter()
            .map(|items| {
                let mut centers: Vec<_> = items.iter().map(|item| item.0).collect();
                centers.sort_unstable();
                centers.dedup();
                centers
            })
            .collect();
        let win_rays: Vec<[[[i16; 5]; 2]; 4]> = (0..size * size)
            .map(|p| {
                let mut rays = [[[-1; 5]; 2]; 4];
                for (direction, (dx, dy)) in DIRS.iter().enumerate() {
                    for (half, sign) in [-1, 1].iter().enumerate() {
                        for step in 1..=5 {
                            let x = (p % size) as isize + dx * sign * step;
                            let y = (p / size) as isize + dy * sign * step;
                            if x >= 0 && y >= 0 && x < size as isize && y < size as isize {
                                rays[direction][half][step as usize - 1] = (y as usize * size + x as usize) as i16;
                            }
                        }
                    }
                }
                rays
            })
            .collect();
        let mut win_dependents = vec![Vec::new(); size * size];
        for (q, directions) in win_rays.iter().enumerate() {
            for (direction, halves) in directions.iter().enumerate() {
                for p in halves.iter().flatten().filter(|p| **p >= 0) {
                    win_dependents[*p as usize].push((q, direction));
                }
            }
        }
        Ok(Self {
            size,
            cells: vec![0; size * size],
            history: Vec::new(),
            rule,
            counts,
            hash: mix64(size as u64),
            geometry: Arc::new(Geometry {
                windows,
                affected,
                scores,
                canonical: (0..FEATURES).map(canonical).collect(),
                inverse: (0..FEATURES).map(invert).collect(),
                neighbors,
                local_affected,
                local_centers,
                win_rays,
                win_dependents,
            }),
            patterns,
            four_counts: vec![[0; 2]; size * size],
            neighbor_counts: vec![0; size * size],
            candidate_bits: [0; 7],
            win_masks: vec![[[0; 2]; 2]; size * size],
            win_undo: Vec::new(),
            win_cache_enabled: true,
            hce: 0,
            network: None,
            quantized_state: None,
            spatial_state: None,
            black_acc: [0.0; HIDDEN],
            white_acc: [0.0; HIDDEN],
        })
    }

    pub fn set_network(&mut self, network: Option<Arc<Network>>) {
        self.network = network;
        self.rebuild_accumulators();
    }

    pub fn rebuild_accumulators(&mut self) {
        if self.win_cache_enabled { self.rebuild_win_cache(); }
        self.spatial_state = self
            .network
            .as_ref()
            .and_then(|net| net.spatial.as_ref())
            .map(|net| crate::spatial::SpatialState::new(&self.cells, self.size, net));
        self.quantized_state = self.network.as_ref()
            .and_then(|net| net.quantized.as_ref())
            .map(|net| Box::new(crate::quantized::State::new(
                net, &self.counts, &self.geometry.inverse,
            )));
        self.black_acc = [0.0; HIDDEN];
        self.white_acc = [0.0; HIDDEN];
        if let Some(net) = self.network.as_ref().filter(|net| net.spatial.is_none() && net.quantized.is_none()) {
            self.black_acc = net.bias;
            self.white_acc = net.bias;
            for (id, n) in self.counts.iter().enumerate().filter(|(_, n)| **n > 0) {
                let inv = self.geometry.inverse[id];
                for h in 0..HIDDEN {
                    self.black_acc[h] += *n as f32 / NORMALIZER * net.embedding[id * HIDDEN + h];
                    self.white_acc[h] += *n as f32 / NORMALIZER * net.embedding[inv * HIDDEN + h];
                }
            }
        }
    }

    fn update(&mut self, p: usize, color: u8, win_restore: Option<&WinUndo>) {
        let prev = self.cells[p];
        if prev != 0 {
            self.hash ^= mix64((p * 2 + prev as usize) as u64 + 1000);
        }
        if color != 0 {
            self.hash ^= mix64((p * 2 + color as usize) as u64 + 1000);
        }
        self.cells[p] = color;
        if self.win_cache_enabled {
            if let Some(previous) = win_restore {
                for (entry, &(q, _)) in self.geometry.win_dependents[p].iter().enumerate() {
                    self.win_masks[q] = previous[entry];
                }
            } else {
                for &(q, direction) in &self.geometry.win_dependents[p] {
                    for side in [1, 2] {
                        let n = self.win_run(q, side, direction);
                        let masks = &mut self.win_masks[q][side as usize - 1];
                        let bit = 1 << direction;
                        masks[0] = (masks[0] & !bit) | if n >= 5 { bit } else { 0 };
                        masks[1] = (masks[1] & !bit) | if n == 5 { bit } else { 0 };
                    }
                }
            }
        }
        if prev == 0 && color != 0 {
            for q in &self.geometry.neighbors[p] {
                self.neighbor_counts[*q] += 1;
                if self.neighbor_counts[*q] == 1 {
                    self.candidate_bits[*q / 64] |= 1 << (*q % 64);
                }
            }
        } else if prev != 0 && color == 0 {
            for q in &self.geometry.neighbors[p] {
                self.neighbor_counts[*q] -= 1;
                if self.neighbor_counts[*q] == 0 {
                    self.candidate_bits[*q / 64] &= !(1 << (*q % 64));
                }
            }
        }
        if let (Some(state), Some(net)) = (
            &mut self.spatial_state,
            self.network.as_ref().and_then(|net| net.spatial.as_ref()),
        ) {
            state.update(
                &self.geometry.local_affected[p],
                &self.geometry.local_centers[p],
                color,
                net,
            );
        }
        for &(w, shift) in &self.geometry.affected[p] {
            let old = self.patterns[w];
            let new = (old & !(3 << shift)) | ((color as usize) << shift);
            let (old_feature, new_feature) =
                (self.geometry.canonical[old], self.geometry.canonical[new]);
            self.counts[old_feature] -= 1;
            self.counts[new_feature] += 1;
            self.hce += self.geometry.scores[new] - self.geometry.scores[old];
            if let Some(net) = self.network.as_ref().filter(|net| net.spatial.is_none() && net.quantized.is_none()) {
                let (old_inv, new_inv) = (self.geometry.inverse[old], self.geometry.inverse[new]);
                crate::simd::update(
                    &mut self.black_acc,
                    &net.embedding[new_feature * HIDDEN..],
                    &net.embedding[old_feature * HIDDEN..],
                    1.0 / NORMALIZER,
                );
                crate::simd::update(
                    &mut self.white_acc,
                    &net.embedding[new_inv * HIDDEN..],
                    &net.embedding[old_inv * HIDDEN..],
                    1.0 / NORMALIZER,
                );
            }
            if let (Some(state), Some(net)) = (
                &mut self.quantized_state,
                self.network.as_ref().and_then(|net| net.quantized.as_ref()),
            ) {
                let (old_inv, new_inv) = (self.geometry.inverse[old], self.geometry.inverse[new]);
                crate::quantized::update_pair(
                    state, net, new_feature, old_feature, new_inv, old_inv,
                );
            }
            let masks = four_masks();
            let (om, nm) = (masks[old], masks[new]);
            if om != nm {
                for (j, &q) in self.geometry.windows[w].iter().enumerate() {
                    if q < 0 { continue; }
                    let counts = &mut self.four_counts[q as usize];
                    for c in 0..2 {
                        counts[c] = counts[c] + (nm[c] >> j & 1) - (om[c] >> j & 1);
                    }
                }
            }
            self.patterns[w] = new;
        }
    }

    pub fn make(&mut self, p: usize, color: u8) {
        debug_assert!(p < self.cells.len() && self.cells[p] == 0 && (color == 1 || color == 2));
        if self.win_cache_enabled {
            let mut previous = [[[0; 2]; 2]; 40];
            for (entry, &(q, _)) in self.geometry.win_dependents[p].iter().enumerate() {
                previous[entry] = self.win_masks[q];
            }
            self.win_undo.push(previous);
        }
        self.update(p, color, None);
        self.history.push((p, color));
    }

    pub fn undo(&mut self) -> Option<(usize, u8)> {
        let mov = self.history.pop()?;
        let previous = self.win_undo.pop();
        self.update(mov.0, 0, previous.as_ref());
        Some(mov)
    }

    pub fn remove(&mut self, p: usize) -> Result<(), String> {
        if p >= self.cells.len() || self.cells[p] == 0 {
            return Err("no stone at takeback coordinate".into());
        }
        self.win_undo.clear();
        self.update(p, 0, None);
        self.history.retain(|m| m.0 != p);
        self.rebuild_accumulators();
        Ok(())
    }

    pub fn evaluate(&self, side: u8) -> i32 {
        if let Some(net) = &self.network {
            if let Some(state) = &self.quantized_state {
                state.value(net, side)
            } else if let (Some(state), Some(spatial)) = (&self.spatial_state, &net.spatial) {
                state.value(side, spatial)
            } else {
                net.value(&self.black_acc, &self.white_acc, side)
            }
        } else {
            ((if side == 1 { self.hce } else { -self.hce }) / 2 + 20).clamp(-12000, 12000)
        }
    }

    pub fn policy_score(&self, p: usize, side: u8) -> Option<f32> {
        Some(
            self.spatial_state
                .as_ref()?
                .policy(p, side, self.network.as_ref()?.spatial.as_ref()?),
        )
    }

    pub fn move_score(&self, p: usize, color: u8) -> i32 {
        let mut delta = 0;
        for &(w, shift) in &self.geometry.affected[p] {
            let id = self.patterns[w];
            let new = id | ((color as usize) << shift);
            delta += self.geometry.scores[new] - self.geometry.scores[id];
        }
        if color == 1 {
            delta
        } else {
            -delta
        }
    }

    /// Both colors share the same affected windows and old pattern scores.
    pub(crate) fn move_scores(&self, p: usize) -> [i32; 2] {
        let mut delta = [0, 0];
        for &(w, shift) in &self.geometry.affected[p] {
            let id = self.patterns[w];
            let old = self.geometry.scores[id];
            delta[0] += self.geometry.scores[id | (1 << shift)] - old;
            delta[1] += old - self.geometry.scores[id | (2 << shift)];
        }
        delta
    }

    /// Necessary (not sufficient) condition for creating a four. Uses the
    /// incremental six-cell patterns, so callers must not use it during raw
    /// temporary cell probes. Unlike an evaluation threshold it cannot miss
    /// a four because another pattern's score decreases.
    pub(crate) fn could_create_four(&self, p: usize, color: u8) -> bool {
        let masks = four_masks();
        self.geometry.affected[p].iter().any(|&(w, shift)|
            masks[self.patterns[w]][color as usize - 1] & (1 << (shift / 2)) != 0)
    }

    /// Both colors in one pass over the affected windows; index 0 is black.
    pub(crate) fn could_create_four_both(&self, p: usize) -> [bool; 2] {
        let c = self.four_counts[p];
        [c[0] > 0, c[1] > 0]
    }

    pub fn at(&self, x: isize, y: isize) -> u8 {
        if x < 0 || y < 0 || x >= self.size as isize || y >= self.size as isize {
            3
        } else {
            self.cells[y as usize * self.size + x as usize]
        }
    }

    pub fn run(&self, p: usize, color: u8, dir: (isize, isize)) -> usize {
        let (x, y) = ((p % self.size) as isize, (p / self.size) as isize);
        let mut n = 1;
        for sign in [-1, 1] {
            let mut k = 1;
            while self.at(x + k * dir.0 * sign, y + k * dir.1 * sign) == color {
                n += 1;
                k += 1;
            }
        }
        n
    }

    #[inline]
    pub fn would_win(&self, p: usize, color: u8) -> bool {
        let exact = self.rule == Rule::Standard || (self.rule == Rule::Renju && color == 1);
        (0..4).any(|direction| {
            let n = self.win_run(p, color, direction);
            if exact { n == 5 } else { n >= 5 }
        })
    }

    #[inline(always)]
    fn win_run(&self, p: usize, color: u8, direction: usize) -> u8 {
        let mut n = 1;
        for half in &self.geometry.win_rays[p][direction] {
            for q in half {
                if *q < 0 || self.cells[*q as usize] != color { break; }
                n += 1;
            }
        }
        n
    }

    /// O(1) geometric win test on an authoritative make/undo position.
    /// Raw-cell probes must use would_win(), which observes temporary stones.
    /// A geometric win still requires legal() for Renju.
    #[inline]
    pub fn cached_would_win(&self, p: usize, color: u8) -> bool {
        if !self.win_cache_enabled { return self.would_win(p, color); }
        let exact = self.rule == Rule::Standard || (self.rule == Rule::Renju && color == 1);
        self.win_masks[p][color as usize - 1][usize::from(exact)] != 0
    }

    // VCF explores few forced branches; maintaining all candidate threats
    // there costs more than scanning. This copy never returns to main search.
    pub(crate) fn disable_win_cache(&mut self) {
        self.win_cache_enabled = false;
        self.win_undo.clear();
    }

    pub fn rebuild_win_cache(&mut self) {
        self.win_undo.clear();
        for p in 0..self.cells.len() {
            for color in [1, 2] {
                let mut masks = [0; 2];
                for direction in 0..4 {
                    let n = self.win_run(p, color, direction);
                    if n >= 5 { masks[0] |= 1 << direction; }
                    if n == 5 { masks[1] |= 1 << direction; }
                }
                self.win_masks[p][color as usize - 1] = masks;
            }
        }
    }

    pub fn winner(&self) -> Option<u8> {
        self.history.iter().find_map(|(p, color)| {
            if self.would_win(*p, *color) {
                Some(*color)
            } else {
                None
            }
        })
    }

    pub fn candidates(&self) -> Vec<usize> {
        if self.history.is_empty() {
            return vec![(self.size / 2) * self.size + self.size / 2];
        }
        let mut candidates = Vec::new();
        for (word, &bits) in self.candidate_bits.iter().enumerate() {
            let mut bits = bits;
            while bits != 0 {
                let p = word * 64 + bits.trailing_zeros() as usize;
                bits &= bits - 1;
                if self.cells[p] == 0 { candidates.push(p); }
            }
        }
        candidates
    }

    pub fn legal(&mut self, p: usize, side: u8) -> bool {
        p < self.cells.len()
            && self.cells[p] == 0
            && (side != 1 || self.rule != Rule::Renju || !self.forbidden(p))
    }

    /// Exact-five, overline, distinct four groups, and recursive true-three checks.
    /// Only the raw cells change in this rules probe; features/history are untouched.
    pub fn forbidden(&mut self, p: usize) -> bool {
        if p >= self.cells.len() || self.cells[p] != 0 {
            return false;
        }
        let mut memo = HashMap::new();
        self.cells[p] = 1;
        let result = self.forbidden_placed(p, &mut memo);
        self.cells[p] = 0;
        result
    }

    fn forbidden_placed(&mut self, p: usize, memo: &mut HashMap<(u64, usize), bool>) -> bool {
        let key_hash = self
            .cells
            .iter()
            .enumerate()
            .filter(|(_, c)| **c != 0)
            .fold(0, |h, (i, c)| h ^ mix64((i * 4 + *c as usize) as u64));
        let key = (key_hash, p);
        if let Some(v) = memo.get(&key) {
            return *v;
        }
        let lengths: Vec<usize> = DIRS.iter().map(|d| self.run(p, 1, *d)).collect();
        // RIF 9.2: attaining an exact five simultaneously has priority.
        if lengths.contains(&5) {
            memo.insert(key, false);
            return false;
        }
        if lengths.iter().any(|n| *n > 5) {
            memo.insert(key, true);
            return true;
        }
        let mut fours = 0;
        for d in DIRS {
            fours += self.four_groups(p, d).len();
        }
        if fours >= 2 {
            memo.insert(key, true);
            return true;
        }
        let (x, y) = ((p % self.size) as isize, (p / self.size) as isize);
        let mut threes: HashSet<Vec<usize>> = HashSet::new();
        for d in DIRS {
            for k in -4isize..=4 {
                let (xx, yy) = (x + k * d.0, y + k * d.1);
                if self.at(xx, yy) != 0 {
                    continue;
                }
                let q = yy as usize * self.size + xx as usize;
                self.cells[q] = 1;
                let groups = self.four_groups(p, d);
                let open_groups: Vec<Vec<usize>> = groups
                    .into_iter()
                    .filter(|(stones, ends)| stones.contains(&q) && ends.len() == 2)
                    .map(|(mut stones, _)| {
                        stones.retain(|s| *s != q);
                        stones
                    })
                    .collect();
                if !open_groups.is_empty()
                    && !self.would_win(q, 1)
                    && !self.forbidden_placed(q, memo)
                {
                    threes.extend(open_groups);
                }
                self.cells[q] = 0;
            }
        }
        let result = threes.len() >= 2;
        memo.insert(key, result);
        result
    }

    fn four_groups(&self, p: usize, d: (isize, isize)) -> HashMap<Vec<usize>, HashSet<usize>> {
        let (x, y) = ((p % self.size) as isize, (p / self.size) as isize);
        let mut groups = HashMap::new();
        for start in -4isize..=0 {
            let mut stones = Vec::new();
            let mut empty = None;
            let mut valid = true;
            for k in start..start + 5 {
                let (xx, yy) = (x + k * d.0, y + k * d.1);
                match self.at(xx, yy) {
                    1 => stones.push(yy as usize * self.size + xx as usize),
                    0 if empty.is_none() => empty = Some(yy as usize * self.size + xx as usize),
                    _ => {
                        valid = false;
                        break;
                    }
                }
            }
            if valid && stones.len() == 4 && stones.contains(&p) {
                let q = empty.unwrap();
                if self.run(q, 1, d) == 5 {
                    stones.sort_unstable();
                    groups.entry(stones).or_insert_with(HashSet::new).insert(q);
                }
            }
        }
        groups
    }

    pub fn verify_features(&self) -> bool {
        let mut counts = vec![0u16; FEATURES];
        let mut hce = 0;
        for w in &self.geometry.windows {
            let id = w.iter().enumerate().fold(0, |id, (j, p)| {
                id | ((if *p < 0 {
                    3
                } else {
                    self.cells[*p as usize] as usize
                }) << (2 * j))
            });
            counts[canonical(id)] += 1;
            hce += self.geometry.scores[id];
        }
        counts == self.counts && hce == self.hce
    }
}

#[cfg(test)]
mod move_score_tests {
    use super::*;

    #[test]
    fn paired_scores_match_actual_pattern_evaluation_changes() {
        for size in [5, 9, 15, 20] {
            let mut board = Board::new(size, Rule::Freestyle).unwrap();
            for step in 0..8 {
                for p in 0..size * size {
                    if board.cells[p] != 0 { continue; }
                    let scores = board.move_scores(p);
                    for side in [1, 2] {
                        let mut child = board.clone();
                        child.make(p, side);
                        let delta = child.hce - board.hce;
                        assert_eq!(scores[side as usize - 1], if side == 1 { delta } else { -delta });
                    }
                }
                let mut p = mix64(step + 981) as usize % board.cells.len();
                while board.cells[p] != 0 { p = (p + 1) % board.cells.len(); }
                board.make(p, (step % 2 + 1) as u8);
            }
        }
    }
}
