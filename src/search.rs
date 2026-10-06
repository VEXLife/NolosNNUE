use crate::board::{mix64, Board, Rule};
use crate::vcf::Vcf;

pub const MATE: i32 = 30000;
const INF: i32 = 32000;

#[derive(Clone, Copy)]
struct Entry {
    key: u64,
    depth: i16,
    score: i32,
    best: u16,
    flag: u8,
}
impl Default for Entry {
    fn default() -> Self {
        Self {
            key: 0,
            depth: -1,
            score: 0,
            best: u16::MAX,
            flag: 0,
        }
    }
}

pub struct Table {
    entries: Vec<Entry>,
}
impl Table {
    pub fn new(kb: usize) -> Self {
        let n = kb.saturating_mul(1024) / std::mem::size_of::<Entry>();
        Self {
            entries: vec![Entry::default(); n],
        }
    }
    pub fn clear(&mut self) {
        self.entries.fill(Entry::default());
    }
    pub fn bytes(&self) -> usize {
        self.entries.len() * std::mem::size_of::<Entry>()
    }
    fn get(&self, key: u64) -> Option<Entry> {
        if self.entries.is_empty() {
            return None;
        }
        let e = self.entries[key as usize % self.entries.len()];
        if e.depth >= 0 && e.key == key {
            Some(e)
        } else {
            None
        }
    }
    fn put(&mut self, key: u64, depth: i16, score: i32, best: Option<usize>, flag: u8) {
        if self.entries.is_empty() {
            return;
        }
        let i = key as usize % self.entries.len();
        self.entries[i] = Entry {
            key,
            depth,
            score,
            best: best.map(|p| p as u16).unwrap_or(u16::MAX),
            flag,
        };
    }
}

#[derive(Clone, Debug)]
pub struct Limits {
    pub depth: usize,
    pub nodes: u64,
    pub time_ms: f64,
    pub branch: usize,
    pub qdepth: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            depth: 8,
            nodes: 250_000,
            time_ms: 1000.0,
            branch: 16,
            // Exact three-/five-ply shortcuts handle short forcing wins;
            // spend the remaining budget on main-search threat continuations.
            qdepth: 1,
        }
    }
}

#[derive(Clone, Debug)]
pub struct ResultInfo {
    pub best: Option<usize>,
    pub score: i32,
    pub depth: usize,
    pub nodes: u64,
    pub pv: Vec<usize>,
    pub vcf_depth: usize,
}

struct Frame {
    depth: usize,
    qleft: usize,
    qplies: usize,
    ply: usize,
    side: u8,
    alpha: i32,
    beta: i32,
    original_alpha: i32,
    entered: bool,
    moves: Vec<usize>,
    next: usize,
    best_score: i32,
    best_move: Option<usize>,
    pv: Vec<usize>,
    key: u64,
    // The parent has made one move before this frame was pushed.
    played: bool,
    scout: bool,
    forced_extension: bool,
    counter_moves: Vec<usize>,
    reduction: usize,
}
impl Frame {
    fn new(
        depth: usize,
        qleft: usize,
        ply: usize,
        side: u8,
        alpha: i32,
        beta: i32,
        played: bool,
    ) -> Self {
        Self {
            depth,
            qleft,
            qplies: 0,
            ply,
            side,
            alpha,
            beta,
            original_alpha: alpha,
            entered: false,
            moves: Vec::new(),
            next: 0,
            best_score: -INF,
            best_move: None,
            pv: Vec::new(),
            key: 0,
            played,
            scout: false,
            forced_extension: false,
            counter_moves: Vec::new(),
            reduction: 0,
        }
    }
}

/// Resumable explicit-stack alpha-beta. Native and WASM yield between small
/// batches, so YXSTOP is processed by the very same protocol state machine.
pub struct Search {
    pub board: Board,
    pub table: Table,
    pub limits: Limits,
    pub result: ResultInfo,
    pub done: bool,
    pub started_ms: f64,
    /// Diagnostic counters; selective depth includes quiescence/forced extensions.
    pub selective_depth: usize,
    pub vcf_nodes: u64,
    pub aspiration_retries: u64,
    /// Experimental depth/move-count reductions. Off until strength is tested.
    pub selective_search: bool,
    aspiration_width: i32,
    side: u8,
    stack: Vec<Frame>,
    iteration: usize,
    nodes: u64,
    killers: Vec<[usize; 2]>,
    history: Vec<i32>,
    root_fallback: Option<usize>,
    vcf: Option<Vcf>,
}

fn to_table(score: i32, ply: usize) -> i32 {
    if score > MATE - 1000 {
        score + ply as i32
    } else if score < -MATE + 1000 {
        score - ply as i32
    } else {
        score
    }
}
fn from_table(score: i32, ply: usize) -> i32 {
    if score > MATE - 1000 {
        score - ply as i32
    } else if score < -MATE + 1000 {
        score + ply as i32
    } else {
        score
    }
}

impl Search {
    pub fn new(mut board: Board, side: u8, limits: Limits, table: Table, now_ms: f64) -> Self {
        board.rebuild_accumulators();
        let mut moves = board.candidates();
        moves.retain(|p| board.legal(*p, side));
        moves.sort_by_cached_key(|p| {
            let scores = board.move_scores(*p);
            -(scores[0] + scores[1])
        });
        let fallback = moves.first().copied();
        let score = board.evaluate(side);
        let vcf = (board.rule == Rule::Freestyle)
            .then(|| Vcf::new(board.clone(), side, 63, (limits.nodes / 8).min(20_000)));
        let mut search = Self {
            history: vec![0; board.cells.len() * 2],
            board,
            table,
            limits,
            result: ResultInfo {
                best: fallback,
                score,
                depth: 0,
                nodes: 0,
                pv: fallback.into_iter().collect(),
                vcf_depth: 0,
            },
            done: fallback.is_none(),
            started_ms: now_ms,
            selective_depth: 0,
            vcf_nodes: 0,
            aspiration_retries: 0,
            selective_search: false,
            aspiration_width: INF,
            side,
            stack: Vec::new(),
            iteration: 1,
            nodes: 0,
            killers: vec![[usize::MAX; 2]; 512],
            root_fallback: fallback,
            vcf,
        };
        if !search.done {
            search.begin_iteration();
        }
        search
    }

    fn begin_iteration(&mut self) {
        let (alpha, beta) = if self.aspiration_width < INF {
            ((self.result.score - self.aspiration_width).max(-INF),
             (self.result.score + self.aspiration_width).min(INF))
        } else { (-INF, INF) };
        self.stack.push(Frame::new(
            self.iteration,
            self.limits.qdepth,
            0,
            self.side,
            alpha,
            beta,
            false,
        ));
    }

    pub fn stop(&mut self) {
        self.done = true;
        self.result.nodes = self.nodes;
    }

    pub fn vcf_active(&self) -> bool {
        self.vcf.is_some()
    }

    pub fn advance(&mut self, batch: usize, now_ms: f64) -> Option<ResultInfo> {
        if self.done {
            return None;
        }
        if now_ms - self.started_ms >= self.limits.time_ms {
            self.stop();
            return None;
        }
        let mut update = None;
        if let Some(vcf) = self.vcf.as_mut() {
            let previous = vcf.nodes;
            let proof = vcf.advance(batch);
            self.nodes += vcf.nodes - previous;
            self.vcf_nodes = vcf.nodes;
            self.result.nodes = self.nodes;
            if let Some(pv) = proof {
                self.result = ResultInfo {
                    best: pv.first().copied(),
                    score: MATE - pv.len() as i32,
                    depth: 0,
                    nodes: self.nodes,
                    vcf_depth: pv.len(),
                    pv,
                };
                self.done = true;
                return Some(self.result.clone());
            }
            if !vcf.done {
                return None;
            }
            self.vcf = None;
        }
        for _ in 0..batch {
            if self.nodes >= self.limits.nodes {
                self.stop();
                break;
            }
            if self.stack.is_empty() {
                break;
            }
            let i = self.stack.len() - 1;
            if !self.stack[i].entered {
                self.nodes += 1;
                if let Some(score) = self.enter(i) {
                    if let Some(info) = self.finish_frame(score) {
                        update = Some(info);
                    }
                    if self.done {
                        break;
                    }
                    continue;
                }
            }
            let i = self.stack.len() - 1;
            if self.stack[i].next == self.stack[i].moves.len() {
                let value = self.stack[i].best_score;
                if let Some(info) = self.finish_frame(value) {
                    update = Some(info);
                }
                if self.done {
                    break;
                }
                continue;
            }
            let f = &mut self.stack[i];
            let p = f.moves[f.next];
            f.next += 1;
            let spends_depth = !f.forced_extension || f.counter_moves.contains(&p);
            let (depth, qleft) = if f.depth > 0 {
                (f.depth - usize::from(spends_depth), f.qleft)
            } else {
                (0, f.qleft.saturating_sub(usize::from(spends_depth)))
            };
            // Search the first move with a full window. Later moves first
            // need only establish whether they improve the current best.
            let scout = f.next > 1 && f.beta - f.alpha > 1;
            // Learned ordering allows a wider frontier: search every candidate,
            // but reduce late quiet moves before re-searching any alpha improvement.
            // The root PV and all tactical/forced moves retain their full depth.
            let spatial = self
                .board
                .network
                .as_ref()
                .is_some_and(|net| net.spatial.is_some());
            let late = if self.selective_search {
                f.depth >= 3 && f.next > if f.ply == 0 { 6 } else { 3 }
            } else if spatial {
                (f.ply > 0 && f.depth >= 3 && f.next > 4)
                    || (f.ply == 0 && f.depth >= 4 && f.next > self.limits.branch.max(4))
            } else {
                f.ply > 0 && f.depth >= 4 && f.next > 4
            };
            // A quiet preparation can fail low at reduced depth despite a
            // forced win at full depth. Keep PV nodes at full depth; use LMR
            // only in null-window nodes, where it remains a selective probe.
            let reduction = if late
                && f.beta - f.alpha <= 1
                && !f.forced_extension
                && {
                    let scores = self.board.move_scores(p);
                    scores[0] < 1200 && scores[1] < 1200
                }
            {
                if self.selective_search {
                    let scale = f.depth.ilog2() as usize * f.next.ilog2() as usize / 2;
                    let pv_guard = usize::from(f.beta - f.alpha > 1);
                    scale.saturating_sub(pv_guard).min(depth.saturating_sub(1))
                } else if spatial && f.depth >= 8 && f.next > 32 {
                    3
                } else if (spatial && f.depth >= 5 && f.next > 16) || (f.depth >= 8 && f.next > 8) {
                    2
                } else {
                    1
                }
            } else {
                0
            };
            let mut child = Frame::new(
                depth.saturating_sub(reduction),
                qleft,
                f.ply + 1,
                3 - f.side,
                if scout { -f.alpha - 1 } else { -f.beta },
                -f.alpha,
                true,
            );
            child.scout = scout;
            child.reduction = reduction;
            child.qplies = if f.depth == 0 { f.qplies + 1 } else { 0 };
            self.board.make(p, f.side);
            self.stack.push(child);
        }
        self.result.nodes = self.nodes;
        update
    }

    fn enter(&mut self, i: usize) -> Option<i32> {
        let (side, ply, depth, qleft) = {
            let f = &self.stack[i];
            (f.side, f.ply, f.depth, f.qleft)
        };
        self.stack[i].entered = true;
        self.selective_depth = self.selective_depth.max(ply);
        if let Some(&(p, color)) = self.board.history.last() {
            if self.board.cached_would_win(p, color) {
                return Some(-MATE + ply as i32);
            }
        }
        if self.board.history.len() == self.board.cells.len() {
            return Some(0);
        }
        if ply > 0 {
            self.stack[i].alpha = self.stack[i].alpha.max(-MATE + ply as i32);
            self.stack[i].beta = self.stack[i].beta.min(MATE - ply as i32 - 1);
            if self.stack[i].alpha >= self.stack[i].beta {
                return Some(self.stack[i].alpha);
            }
        }
        let mut key =
            self.board.hash ^ mix64(side as u64 + 5000) ^ mix64(self.board.rule.id() as u64 + 6000);
        // Quiescence bounds are valid only for the same remaining tactical
        // budget, and must not collide with normal-depth entries.
        if depth == 0 {
            key ^= mix64(qleft as u64 + 7000);
            key ^= mix64(self.stack[i].qplies as u64 + 8000);
            key ^= mix64(self.limits.qdepth.saturating_mul(2).max(2) as u64 + 9000);
        }
        self.stack[i].key = key;
        let entry = self.table.get(key);
        if ply > 0 {
            if let Some(e) = entry.filter(|e| e.depth >= depth as i16) {
                let score = from_table(e.score, ply);
                if e.flag == 0
                    || (e.flag == 1 && score >= self.stack[i].beta)
                    || (e.flag == 2 && score <= self.stack[i].alpha)
                {
                    return Some(score);
                }
            }
        }
        let mut candidates = self.board.candidates();
        let mut wins = Vec::new();
        let mut blocks = Vec::new();
        for p in &candidates {
            if self.board.cached_would_win(*p, side) && self.board.legal(*p, side) {
                wins.push(*p);
            }
            if self.board.cached_would_win(*p, 3 - side) && self.board.legal(*p, 3 - side) {
                blocks.push(*p);
            }
        }
        if !wins.is_empty() {
            let f = &mut self.stack[i];
            f.best_move = Some(wins[0]);
            f.pv = vec![wins[0]];
            return Some(MATE - ply as i32 - 1);
        }
        if blocks.len() >= 2 {
            let fallback = blocks.iter().copied().find(|p| self.board.legal(*p, side));
            self.stack[i].best_move = fallback;
            self.stack[i].pv = fallback.into_iter().collect();
            return Some(-MATE + ply as i32 + 2);
        }
        if blocks.len() == 1 {
            candidates = blocks;
        }
        candidates.retain(|p| self.board.legal(*p, side));
        if candidates.is_empty() {
            return Some(if self.board.history.len() == self.board.cells.len() {
                0
            } else {
                -MATE + ply as i32
            });
        }
        let forced = candidates.len() == 1 && self.board.cached_would_win(candidates[0], 3 - side);
        if self.board.rule == Rule::Freestyle {
            // Check all three-ply wins before any five-ply certificate.
            for &p in &candidates {
                if let Some((a, b)) = self.board.could_create_four(p, side).then(|| self.double_five(p, side)).flatten() {
                    self.stack[i].best_move = Some(p);
                    self.stack[i].pv = vec![p, a, b];
                    return Some(MATE - ply as i32 - 3);
                }
            }
            for &p in &candidates {
                if self.board.could_create_four(p, side) && self.compound_seed(p, side) {
                    if let Some(pv) = self.four_then_double_five(p, side) {
                        self.stack[i].best_move = Some(p);
                        self.stack[i].pv = pv;
                        return Some(MATE - ply as i32 - 5);
                    }
                }
            }
        }
        // Bound speculative counter-four exchanges, after checking exact
        // short wins. A horizon result is heuristic, never a mate certificate.
        if depth == 0 && self.stack[i].qplies >= self.limits.qdepth.saturating_mul(2).max(2) {
            return Some(self.board.evaluate(side));
        }
        let mut threat_defense = false;
        if self.board.rule == Rule::Freestyle && !forced {
            let mut threats = Vec::new();
            for &p in &candidates {
                if self.board.could_create_four(p, 3 - side) && self.double_five(p, 3 - side).is_some() { threats.push(p); }
            }
            if !threats.is_empty() {
                threat_defense = true;
                let mut counters = Vec::new();
                candidates.retain(|&p| {
                    // A counter-four forces the opponent to answer first.
                    if self.creates_four(p, side) { counters.push(p); return true; }
                    self.board.cells[p] = side;
                    let safe = threats.iter().all(|&q| q == p || self.double_five(q, 3 - side).is_none());
                    self.board.cells[p] = 0;
                    safe
                });
                self.stack[i].counter_moves = counters;
                if candidates.is_empty() {
                    self.stack[i].best_move = Some(threats[0]);
                    self.stack[i].pv = vec![threats[0]];
                    return Some(-MATE + ply as i32 + 4);
                }
            }
        }
        // A mandatory reply to an immediate five is not a quiet horizon.
        // Preserve the forcing-search budget for defenses, including at zero.
        self.stack[i].forced_extension = forced || threat_defense;
        if depth == 0 {
            if qleft == 0 && !forced && !threat_defense {
                return Some(self.board.evaluate(side));
            }
            if !forced && !threat_defense {
                let stand_pat = self.board.evaluate(side);
                if stand_pat >= self.stack[i].beta {
                    return Some(stand_pat);
                }
                self.stack[i].best_score = stand_pat;
                self.stack[i].alpha = self.stack[i].alpha.max(stand_pat);
                // Continuous-four quiescence: only threat-producing moves, with
                // all forced defenses handled on the opponent's next node.
                candidates.retain(|p| self.creates_four(*p, side));
                if candidates.is_empty() {
                    return Some(stand_pat);
                }
            }
        }
        let tt_move = entry.map(|e| e.best as usize);
        let previous = if ply == 0 { self.result.best } else { None };
        let killer = self.killers[ply.min(511)];
        candidates.sort_by_cached_key(|p| {
            let scores = self.board.move_scores(*p);
            let own_score = scores[side as usize - 1];
            let other_score = scores[2 - side as usize];
            let priority = if Some(*p) == previous || Some(*p) == tt_move {
                50_000_000
            } else if killer.contains(p) {
                500_000
            } else {
                0
            };
            let tactical = if self.board.policy_score(*p, side).is_some()
                && (own_score >= 2400 || other_score >= 2400)
            {
                2_000_000
            } else {
                0
            };
            -(priority
                + tactical
                + self
                    .board
                    .policy_score(*p, side)
                    .map(|v| (v.clamp(-30.0, 30.0) * 1500.0) as i32)
                    .unwrap_or(0)
                + own_score * 2
                + other_score
                + self.history[(side as usize - 1) * self.board.cells.len() + *p].min(200_000))
        });
        if depth > 0 && !forced && !threat_defense && self.board.policy_score(candidates[0], side).is_none() {
            // Selective search, never prune immediate wins or forced blocks.
            candidates.truncate(if ply == 0 {
                self.limits.branch * 2
            } else {
                self.limits.branch
            });
        }
        self.stack[i].moves = candidates;
        None
    }

    fn creates_four(&mut self, p: usize, side: u8) -> bool {
        if !self.board.could_create_four(p, side) { return false; }
        self.board.cells[p] = side;
        let (x, y) = (
            (p % self.board.size) as isize,
            (p / self.board.size) as isize,
        );
        let mut found = false;
        'outer: for (dx, dy) in crate::board::DIRS {
            let nearby = (-4..=4).filter(|&k| k != 0 && self.board.at(x + k * dx, y + k * dy) == side).count();
            if nearby < 3 { continue; }
            for k in -4..=4 {
                let (xx, yy) = (x + k * dx, y + k * dy);
                if self.board.at(xx, yy) == 0 {
                    let q = yy as usize * self.board.size + xx as usize;
                    if self.board.would_win(q, side) && self.board.legal(q, side) {
                        found = true;
                        break 'outer;
                    }
                }
            }
        }
        self.board.cells[p] = 0;
        found
    }

    fn double_five(&mut self, p: usize, side: u8) -> Option<(usize, usize)> {
        self.board.cells[p] = side;
        let (x, y) = ((p % self.board.size) as isize, (p / self.board.size) as isize);
        let mut first = None;
        let mut result = None;
        'directions: for (dx, dy) in crate::board::DIRS {
            let nearby = (-4..=4).filter(|&k| k != 0 && self.board.at(x + k * dx, y + k * dy) == side).count();
            if nearby < 3 { continue; }
            for k in -4..=4 {
                let (xx, yy) = (x + k * dx, y + k * dy);
                if self.board.at(xx, yy) != 0 { continue; }
                let q = yy as usize * self.board.size + xx as usize;
                let mut length = 1;
                for sign in [-1, 1] {
                    for distance in 1..=4 {
                        if self.board.at(xx + sign * distance * dx, yy + sign * distance * dy) != side { break; }
                        length += 1;
                    }
                }
                if length >= 5 {
                    if let Some(a) = first {
                        if a != q { result = Some((a, q)); break 'directions; }
                    } else { first = Some(q); }
                }
            }
        }
        self.board.cells[p] = 0;
        result
    }

    // Exact five-ply certificate: force the only block of a four, then
    // create a double five. A defender counter-four invalidates this shortcut.
    fn four_then_double_five(&mut self, p: usize, side: u8) -> Option<Vec<usize>> {
        let candidates = self.board.candidates();
        self.board.cells[p] = side;
        let wins: Vec<_> = candidates.iter().copied().filter(|&q|
            self.board.cells[q] == 0 && self.board.would_win(q, side)).take(2).collect();
        let mut result = None;
        if wins.len() == 1 {
            let q = wins[0];
            self.board.cells[q] = 3 - side;
            let counter = candidates.iter().any(|&r|
                self.board.cells[r] == 0 && self.board.would_win(r, 3 - side));
            if !counter {
                let (x, y) = ((p % self.board.size) as isize, (p / self.board.size) as isize);
                'directions: for (dx, dy) in crate::board::DIRS {
                    for k in -4..=4 {
                        let (xx, yy) = (x + dx * k, y + dy * k);
                        if self.board.at(xx, yy) != 0 { continue; }
                        let r = yy as usize * self.board.size + xx as usize;
                        if let Some((a, b)) = self.double_five(r, side) {
                            result = Some(vec![p, q, r, a, b]);
                            break 'directions;
                        }
                    }
                }
            }
            self.board.cells[q] = 0;
        }
        self.board.cells[p] = 0;
        result
    }

    // Fast, conservative candidate selection for the more expensive
    // certificate check. A missed shortcut still goes through normal search.
    fn compound_seed(&self, p: usize, side: u8) -> bool {
        let (x, y) = ((p % self.board.size) as isize, (p / self.board.size) as isize);
        let mut lines = 0;
        for (dx, dy) in crate::board::DIRS {
            let stones = (-4..=4).filter(|&k| k != 0 && self.board.at(x + dx * k, y + dy * k) == side).count();
            if stones >= 5 { return true; }
            if stones >= 2 { lines += 1; }
        }
        lines >= 2
    }

    fn finish_frame(&mut self, score: i32) -> Option<ResultInfo> {
        let frame = self.stack.pop().unwrap();
        if frame.entered && frame.key != 0 {
            let flag = if score <= frame.original_alpha {
                2
            } else if score >= frame.beta {
                1
            } else {
                0
            };
            self.table.put(
                frame.key,
                frame.depth as i16,
                to_table(score, frame.ply),
                frame.best_move,
                flag,
            );
        }
        if frame.scout || frame.reduction > 0 {
            let parent = self.stack.last().unwrap();
            let value = -score;
            if value > parent.alpha && (frame.reduction > 0 || value < parent.beta) {
                // Leave the move on the board and repeat at the full window;
                // a scout bound must never be accepted as an exact PV value.
                // First verify an LMR improvement at full depth with a scout
                // window. Only a verified PV improvement needs a full window.
                let verify_reduction = frame.reduction > 0;
                let mut repeated = Frame::new(
                    frame.depth + frame.reduction,
                    frame.qleft,
                    frame.ply,
                    frame.side,
                    if verify_reduction { -parent.alpha - 1 } else { -parent.beta },
                    -parent.alpha,
                    true,
                );
                repeated.scout = verify_reduction;
                repeated.qplies = frame.qplies;
                self.stack.push(repeated);
                return None;
            }
        }
        if frame.played {
            self.board.undo();
        }
        if let Some(parent) = self.stack.last_mut() {
            let value = -score;
            if value > parent.best_score {
                parent.best_score = value;
                parent.best_move = Some(parent.moves[parent.next - 1]);
                parent.pv.clear();
                parent.pv.push(parent.moves[parent.next - 1]);
                parent.pv.extend_from_slice(&frame.pv);
            }
            parent.alpha = parent.alpha.max(value);
            if parent.alpha >= parent.beta {
                let p = parent.moves[parent.next - 1];
                let h = (parent.side as usize - 1) * self.board.cells.len() + p;
                self.history[h] =
                    (self.history[h] + (parent.depth * parent.depth) as i32 * 16).min(200_000);
                let killer = &mut self.killers[parent.ply.min(511)];
                if killer[0] != p {
                    killer[1] = killer[0];
                    killer[0] = p;
                }
                parent.next = parent.moves.len();
            }
            None
        } else {
            // A root aspiration bound is not a completed iteration. Widen and
            // retry; interruption retains the previous exact result and PV.
            if self.aspiration_width < INF && (score <= frame.original_alpha || score >= frame.beta) {
                self.aspiration_retries += 1;
                self.aspiration_width = (self.aspiration_width * 2).min(INF);
                self.begin_iteration();
                return None;
            }
            self.result = ResultInfo {
                best: frame.best_move.or(self.root_fallback),
                score,
                depth: self.iteration,
                nodes: self.nodes,
                pv: if frame.pv.is_empty() {
                    self.root_fallback.into_iter().collect()
                } else {
                    frame.pv
                },
                vcf_depth: 0,
            };
            let update = self.result.clone();
            if self.iteration >= self.limits.depth.max(1) || score.abs() >= MATE - 500 {
                self.done = true;
            } else {
                self.iteration += 1;
                self.aspiration_width = if self.iteration >= 4 && score.abs() < MATE - 1000 { 120 } else { INF };
                self.begin_iteration();
            }
            Some(update)
        }
    }
}

#[cfg(not(target_arch = "wasm32"))]
pub fn now_ms() -> f64 {
    use std::sync::OnceLock;
    use std::time::Instant;
    static EPOCH: OnceLock<Instant> = OnceLock::new();
    EPOCH.get_or_init(Instant::now).elapsed().as_secs_f64() * 1000.0
}

#[cfg(not(target_arch = "wasm32"))]
pub fn run(board: Board, side: u8, limits: Limits, table: Table) -> (ResultInfo, Table) {
    let mut search = Search::new(board, side, limits, table, now_ms());
    while !search.done {
        search.advance(128, now_ms());
    }
    (search.result, search.table)
}

#[cfg(test)]
mod spatial_search_tests {
    use super::*;
    use crate::network::{Network, HIDDEN};
    use crate::spatial::{SpatialNetwork, PARAMETERS};
    use std::sync::Arc;

    fn reported_position() -> Board {
        let mut board = Board::new(15, Rule::Freestyle).unwrap();
        for (i, p) in [112,111,98,126,96,128,97,95,127,82,99,100,113,141,129].into_iter().enumerate() {
            board.make(p, (i % 2 + 1) as u8);
        }
        board
    }

    #[test]
    fn reported_position_keeps_both_defenses_and_counter_four() {
        let mut search = Search::new(reported_position(), 2, Limits::default(), Table::new(0), 0.0);
        let cells = search.board.cells.clone();
        let hash = search.board.hash;
        assert!(search.enter(0).is_none());
        let mut defenses = search.stack[0].moves.clone();
        defenses.sort_unstable();
        assert_eq!(defenses, vec![81,145,156,171]); // g6, k10, g11, g12
        assert_eq!(search.board.cells, cells);
        assert_eq!(search.board.hash, hash);
        // Independently enumerate every square and every opponent response.
        for p in 0..225 {
            if cells[p] != 0 { continue; }
            let mut after = search.board.clone();
            after.make(p, 2);
            let counter_four = (0..225).any(|q| after.cells[q] == 0 && after.would_win(q, 2));
            let survives = !(0..225).any(|q| {
                if after.cells[q] != 0 { return false; }
                after.make(q, 1);
                let wins = (0..225).filter(|&r| after.cells[r] == 0 && after.would_win(r, 1)).count();
                after.undo();
                wins >= 2
            });
            assert_eq!(defenses.contains(&p), counter_four || survives, "square {p}");
        }
    }

    #[test]
    fn zero_quiescence_budget_still_searches_mandatory_five_defense() {
        let mut board = reported_position();
        board.make(156, 2); // g11 forces black g12.
        let mut search = Search::new(board, 1, Limits::default(), Table::new(0), 0.0);
        search.vcf = None;
        search.stack.clear();
        search.stack.push(Frame::new(0, 0, 0, 1, -INF, INF, false));
        assert!(search.enter(0).is_none());
        assert_eq!(search.stack[0].moves, vec![171]);
        assert!(search.stack[0].forced_extension);
        search.advance(1, 0.0);
        assert_eq!(search.stack.last().unwrap().qleft, 0);
        assert_eq!(search.board.history.last(), Some(&(171, 1)));
    }

    #[test]
    fn quiet_threat_defenses_extend_but_counter_fours_spend_depth() {
        let mut search = Search::new(reported_position(), 2, Limits::default(), Table::new(0), 0.0);
        search.vcf = None;
        assert!(search.enter(0).is_none());
        assert!(search.stack[0].forced_extension);
        assert_eq!(search.stack[0].counter_moves, vec![156, 171]);
        for (p, expected_depth) in [(81, 1), (156, 0)] {
            let mut trial = Search::new(reported_position(), 2, Limits::default(), Table::new(0), 0.0);
            trial.vcf = None;
            assert!(trial.enter(0).is_none());
            trial.stack[0].moves = vec![p];
            trial.advance(1, 0.0);
            assert_eq!(trial.stack.last().unwrap().depth, expected_depth);
        }
    }

    #[test]
    fn second_reported_position_preserves_both_quiet_defenses() {
        let mut board = Board::new(15, Rule::Freestyle).unwrap();
        for (i, p) in [112,98,96,128,82,110,113,81,54,68,127,97,143,114,141].into_iter().enumerate() {
            board.make(p, (i % 2 + 1) as u8);
        }
        let mut search = Search::new(board.clone(), 2, Limits::default(), Table::new(0), 0.0);
        assert!(search.enter(0).is_none());
        let mut moves = search.stack[0].moves.clone();
        moves.sort_unstable();
        assert_eq!(moves, vec![99,155]); // j7, f11
        assert!(search.stack[0].forced_extension);
        assert!(search.stack[0].counter_moves.is_empty());
        assert_eq!(search.board.cells, board.cells);
        assert_eq!(search.board.hash, board.hash);
    }

    #[test]
    fn compound_four_certificate_checks_every_defense_and_rejects_counter_four() {
        let mut board = Board::new(15, Rule::Freestyle).unwrap();
        for (x, y) in [(6,7), (7,7), (8,7), (7,6), (7,8)] { board.make(y * 15 + x, 1); }
        board.make(9 * 15 + 7, 2);
        let mut search = Search::new(board.clone(), 1, Limits::default(), Table::new(0), 0.0);
        let pv = search.four_then_double_five(5 * 15 + 7, 1).unwrap();
        assert_eq!(pv.len(), 5);
        for (i, &p) in pv.iter().enumerate() {
            let side = (i % 2 + 1) as u8;
            if side == 2 {
                for q in 0..225 {
                    if q == p || board.cells[q] != 0 { continue; }
                    board.make(q, side);
                    assert_ne!(board.winner(), Some(side));
                    assert!((0..225).any(|r| board.cells[r] == 0 && board.would_win(r, 1)));
                    board.undo();
                }
            }
            board.make(p, side);
            assert_eq!(board.winner(), if i == 4 { Some(1) } else { None });
        }
        assert_eq!(search.board.cells[5 * 15 + 7], 0);
        for x in [4,5,6] { search.board.make(4 * 15 + x, 2); }
        assert!(search.four_then_double_five(5 * 15 + 7, 1).is_none());
        assert_eq!(search.board.cells[4 * 15 + 7], 0);
    }

    #[test]
    fn tactical_horizon_is_bounded_and_its_table_keys_are_distinct() {
        let mut board = reported_position();
        board.make(156, 2);
        let mut search = Search::new(board, 1, Limits::default(), Table::new(1024), 0.0);
        search.vcf = None;
        search.stack.clear();
        let mut capped = Frame::new(0, 0, 1, 1, -INF, INF, false);
        capped.qplies = search.limits.qdepth * 2;
        search.stack.push(capped);
        let score = search.enter(0).unwrap();
        assert!(score.abs() < MATE - 500);
        let capped_key = search.stack[0].key;
        search.table.put(capped_key, 0, score, None, 0);
        search.stack.clear();
        search.stack.push(Frame::new(0, 0, 1, 1, -INF, INF, false));
        assert!(search.enter(0).is_none());
        assert_ne!(search.stack[0].key, capped_key);
    }

    #[test]
    fn four_seed_filter_never_rejects_a_new_five_threat() {
        for size in [5, 9, 15] {
            for sample in 0..4 {
                let mut board = Board::new(size, Rule::Freestyle).unwrap();
                for p in 0..size * size {
                    let r = mix64((p + sample * size * size) as u64 + 918);
                    if r % 5 < 2 { board.make(p, (r % 2 + 1) as u8); }
                }
                for side in [1, 2] {
                    let old: Vec<_> = (0..size * size).map(|q| board.cells[q] == 0 && board.would_win(q, side)).collect();
                    for p in 0..size * size {
                        if board.cells[p] != 0 { continue; }
                        let seed = board.could_create_four(p, side);
                        board.cells[p] = side;
                        let new_threat = (0..size * size).any(|q| board.cells[q] == 0 && !old[q] && board.would_win(q, side));
                        board.cells[p] = 0;
                        assert!(!new_threat || seed, "size={size} sample={sample} side={side} move={p}");
                    }
                }
            }
        }
    }

    #[test]
    fn aspiration_matches_full_window_and_keeps_exact_result_on_retry_stop() {
        fn make_search() -> Search {
            let mut board = Board::new(5, Rule::Standard).unwrap();
            for (p, color) in [(12, 1), (0, 2), (6, 1)] { board.make(p, color); }
            Search::new(board, 2, Limits { depth: 4, nodes: 1_000_000, time_ms: 1e12,
                                        branch: 400, qdepth: 0 }, Table::new(1024), 0.0)
        }
        let mut narrowed = make_search();
        while !narrowed.done { narrowed.advance(128, 0.0); }
        let mut full = make_search();
        while !full.done {
            if full.stack.len() == 1 && !full.stack[0].entered {
                full.aspiration_width = INF;
                let root = &mut full.stack[0];
                root.alpha = -INF;
                root.original_alpha = -INF;
                root.beta = INF;
            }
            full.advance(1, 0.0);
        }
        assert_eq!(narrowed.result.depth, 4);
        assert_eq!(narrowed.result.score, full.result.score);

        let mut interrupted = make_search();
        while interrupted.result.depth < 3 { interrupted.advance(1, 0.0); }
        let exact = interrupted.result.clone();
        // Deliberately force a fail-low at depth four, then stop on retry.
        interrupted.aspiration_width = 1;
        interrupted.stack[0].alpha = 31000;
        interrupted.stack[0].original_alpha = 31000;
        interrupted.stack[0].beta = 31001;
        while interrupted.aspiration_retries == 0 { interrupted.advance(1, 0.0); }
        assert_eq!(interrupted.result.depth, exact.depth);
        assert_eq!(interrupted.result.score, exact.score);
        assert_eq!(interrupted.result.pv, exact.pv);
        interrupted.stop();
        assert_eq!(interrupted.result.depth, 3);
    }

    #[test]
    fn spatial_frontier_keeps_quiet_candidates_and_prioritizes_tactics() {
        let net = Arc::new(Network {
            quantized: None,
            embedding: vec![],
            bias: [0.0; HIDDEN],
            head: [0.0; HIDDEN],
            tempo: 0.0,
            spatial: Some(SpatialNetwork::from_values(&vec![0.0; PARAMETERS])),
        });
        let mut board = Board::new(9, Rule::Freestyle).unwrap();
        for (p, color) in [(39, 1), (38, 2), (40, 1), (8, 2), (41, 1), (72, 2)] {
            board.make(p, color);
        }
        board.set_network(Some(net));
        let count = board.candidates().len();
        let mut search = Search::new(
            board,
            1,
            Limits {
                branch: 1,
                ..Limits::default()
            },
            Table::new(0),
            0.0,
        );
        assert!(search.enter(0).is_none());
        assert_eq!(search.stack[0].moves.len(), count);
        assert!(search.board.move_score(search.stack[0].moves[0], 1) >= 2400);
        // The legacy beam is retained for compatible gen9 teacher behavior.
        search.board.set_network(None);
        search.stack.clear();
        search.begin_iteration();
        assert!(search.enter(0).is_none());
        assert_eq!(search.stack[0].moves.len(), 2);
    }
}
