use crate::board::{mix64, Board};

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
            qdepth: 6,
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
}

struct Frame {
    depth: usize,
    qleft: usize,
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
    side: u8,
    stack: Vec<Frame>,
    iteration: usize,
    nodes: u64,
    killers: Vec<[usize; 2]>,
    history: Vec<i32>,
    root_fallback: Option<usize>,
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
        moves.sort_by_key(|p| -(board.move_score(*p, side) + board.move_score(*p, 3 - side)));
        let fallback = moves.first().copied();
        let score = board.evaluate(side);
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
            },
            done: fallback.is_none(),
            started_ms: now_ms,
            side,
            stack: Vec::new(),
            iteration: 1,
            nodes: 0,
            killers: vec![[usize::MAX; 2]; 512],
            root_fallback: fallback,
        };
        if !search.done {
            search.begin_iteration();
        }
        search
    }

    fn begin_iteration(&mut self) {
        self.stack.push(Frame::new(
            self.iteration,
            self.limits.qdepth,
            0,
            self.side,
            -INF,
            INF,
            false,
        ));
    }

    pub fn stop(&mut self) {
        self.done = true;
        self.result.nodes = self.nodes;
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
            let (depth, qleft) = if f.depth > 0 {
                (f.depth - 1, f.qleft)
            } else {
                (0, f.qleft.saturating_sub(1))
            };
            let child = Frame::new(depth, qleft, f.ply + 1, 3 - f.side, -f.beta, -f.alpha, true);
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
        if let Some(&(p, color)) = self.board.history.last() {
            if self.board.would_win(p, color) {
                return Some(-MATE + ply as i32);
            }
        }
        if self.board.history.len() == self.board.cells.len() {
            return Some(0);
        }
        let key =
            self.board.hash ^ mix64(side as u64 + 5000) ^ mix64(self.board.rule.id() as u64 + 6000);
        self.stack[i].key = key;
        let entry = self.table.get(key);
        if ply > 0 && depth > 0 {
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
            if self.board.would_win(*p, side) && self.board.legal(*p, side) {
                wins.push(*p);
            }
            if self.board.would_win(*p, 3 - side) && self.board.legal(*p, 3 - side) {
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
        let forced = candidates.len() == 1 && self.board.would_win(candidates[0], 3 - side);
        if depth == 0 {
            if qleft == 0 {
                return Some(self.board.evaluate(side));
            }
            if !forced {
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
            let priority = if Some(*p) == previous || Some(*p) == tt_move {
                50_000_000
            } else if killer.contains(p) {
                500_000
            } else {
                0
            };
            -(priority
                + self.board.move_score(*p, side) * 2
                + self.board.move_score(*p, 3 - side)
                + self.history[(side as usize - 1) * self.board.cells.len() + *p].min(200_000))
        });
        if depth > 0 && !forced {
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
        if self.board.move_score(p, side) < 2400 {
            return false;
        }
        self.board.cells[p] = side;
        let (x, y) = (
            (p % self.board.size) as isize,
            (p / self.board.size) as isize,
        );
        let mut found = false;
        'outer: for (dx, dy) in crate::board::DIRS {
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

    fn finish_frame(&mut self, score: i32) -> Option<ResultInfo> {
        let frame = self.stack.pop().unwrap();
        if frame.depth > 0 {
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
            };
            let update = self.result.clone();
            if self.iteration >= self.limits.depth.max(1) || score.abs() >= MATE - 500 {
                self.done = true;
            } else {
                self.iteration += 1;
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
