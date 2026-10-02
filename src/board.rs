use crate::network::{canonical, invert, Network, FEATURES, HIDDEN, NORMALIZER};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

pub const DIRS: [(isize, isize); 4] = [(1, 0), (0, 1), (1, 1), (1, -1)];

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
    pub hce: i32,
    pub network: Option<Arc<Network>>,
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
            }),
            patterns,
            hce: 0,
            network: None,
            black_acc: [0.0; HIDDEN],
            white_acc: [0.0; HIDDEN],
        })
    }

    pub fn set_network(&mut self, network: Option<Arc<Network>>) {
        self.network = network;
        self.rebuild_accumulators();
    }

    pub fn rebuild_accumulators(&mut self) {
        self.black_acc = [0.0; HIDDEN];
        self.white_acc = [0.0; HIDDEN];
        if let Some(net) = &self.network {
            self.black_acc = net.bias;
            self.white_acc = net.bias;
            for (id, n) in self.counts.iter().enumerate().filter(|(_, n)| **n > 0) {
                let inv = invert(id);
                for h in 0..HIDDEN {
                    self.black_acc[h] += *n as f32 / NORMALIZER * net.embedding[id * HIDDEN + h];
                    self.white_acc[h] += *n as f32 / NORMALIZER * net.embedding[inv * HIDDEN + h];
                }
            }
        }
    }

    fn update(&mut self, p: usize, color: u8) {
        let prev = self.cells[p];
        if prev != 0 {
            self.hash ^= mix64((p * 2 + prev as usize) as u64 + 1000);
        }
        if color != 0 {
            self.hash ^= mix64((p * 2 + color as usize) as u64 + 1000);
        }
        self.cells[p] = color;
        for &(w, shift) in &self.geometry.affected[p] {
            let old = self.patterns[w];
            let new = (old & !(3 << shift)) | ((color as usize) << shift);
            let (old_feature, new_feature) = (canonical(old), canonical(new));
            self.counts[old_feature] -= 1;
            self.counts[new_feature] += 1;
            self.hce += self.geometry.scores[new] - self.geometry.scores[old];
            if let Some(net) = &self.network {
                let (old_inv, new_inv) = (invert(old), invert(new));
                for h in 0..HIDDEN {
                    self.black_acc[h] += (net.embedding[new_feature * HIDDEN + h]
                        - net.embedding[old_feature * HIDDEN + h])
                        / NORMALIZER;
                    self.white_acc[h] += (net.embedding[new_inv * HIDDEN + h]
                        - net.embedding[old_inv * HIDDEN + h])
                        / NORMALIZER;
                }
            }
            self.patterns[w] = new;
        }
    }

    pub fn make(&mut self, p: usize, color: u8) {
        debug_assert!(p < self.cells.len() && self.cells[p] == 0 && (color == 1 || color == 2));
        self.update(p, color);
        self.history.push((p, color));
    }

    pub fn undo(&mut self) -> Option<(usize, u8)> {
        let mov = self.history.pop()?;
        self.update(mov.0, 0);
        Some(mov)
    }

    pub fn remove(&mut self, p: usize) -> Result<(), String> {
        if p >= self.cells.len() || self.cells[p] == 0 {
            return Err("no stone at takeback coordinate".into());
        }
        self.update(p, 0);
        self.history.retain(|m| m.0 != p);
        self.rebuild_accumulators();
        Ok(())
    }

    pub fn evaluate(&self, side: u8) -> i32 {
        if let Some(net) = &self.network {
            net.value(&self.black_acc, &self.white_acc, side)
        } else {
            ((if side == 1 { self.hce } else { -self.hce }) / 2 + 20).clamp(-12000, 12000)
        }
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

    pub fn would_win(&self, p: usize, color: u8) -> bool {
        DIRS.iter().any(|d| {
            let n = self.run(p, color, *d);
            if self.rule == Rule::Standard || (self.rule == Rule::Renju && color == 1) {
                n == 5
            } else {
                n >= 5
            }
        })
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
        let mut marked = vec![false; self.cells.len()];
        for &(p, _) in &self.history {
            let (x, y) = ((p % self.size) as isize, (p / self.size) as isize);
            for dy in -2..=2 {
                for dx in -2..=2 {
                    let (xx, yy) = (x + dx, y + dy);
                    if xx >= 0 && yy >= 0 && xx < self.size as isize && yy < self.size as isize {
                        let q = yy as usize * self.size + xx as usize;
                        if self.cells[q] == 0 {
                            marked[q] = true;
                        }
                    }
                }
            }
        }
        marked
            .iter()
            .enumerate()
            .filter_map(|(p, v)| if *v { Some(p) } else { None })
            .collect()
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
