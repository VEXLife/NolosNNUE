//! Bounded, resumable continuous-four proof search for freestyle.
//! Only a proved win is returned. Exhaustion is inconclusive, never a loss.
use crate::board::{Board, Rule, DIRS};
use std::collections::HashSet;

struct Frame {
    side: u8,
    entered: bool,
    moves: Vec<usize>,
    next: usize,
    played: bool,
    key: (u64, u8, usize),
}

pub struct Vcf {
    board: Board,
    attacker: u8,
    start: usize,
    max_plies: usize,
    budget: u64,
    pub nodes: u64,
    pub done: bool,
    stack: Vec<Frame>,
    failed: HashSet<(u64, u8, usize)>,
}

impl Vcf {
    pub fn new(mut board: Board, attacker: u8, max_plies: usize, budget: u64) -> Self {
        board.disable_win_cache();
        // Proof search never uses a static evaluation or NNUE accumulators.
        board.set_network(None);
        let start = board.history.len();
        let unsupported =
            board.rule != Rule::Freestyle || !matches!(attacker, 1 | 2) || board.winner().is_some();
        let mut search = Self {
            board,
            attacker,
            start,
            max_plies,
            budget,
            nodes: 0,
            done: unsupported || budget == 0 || max_plies == 0,
            stack: Vec::new(),
            failed: HashSet::new(),
        };
        search.push(attacker, false);
        search
    }

    fn push(&mut self, side: u8, played: bool) {
        let remaining = self
            .max_plies
            .saturating_sub(self.board.history.len() - self.start);
        self.stack.push(Frame {
            side,
            played,
            entered: false,
            moves: Vec::new(),
            next: 0,
            key: (self.board.hash, side, remaining),
        });
    }

    fn fail(&mut self) {
        let frame = self.stack.pop().unwrap();
        self.failed.insert(frame.key);
        if frame.played {
            self.board.undo();
        }
        if self.stack.is_empty() {
            self.done = true;
        }
    }

    fn proof(&mut self, suffix: &[usize]) -> Option<Vec<usize>> {
        let mut pv: Vec<_> = self.board.history[self.start..]
            .iter()
            .map(|(p, _)| *p)
            .collect();
        pv.extend_from_slice(suffix);
        if pv.len() > self.max_plies {
            return None;
        }
        self.done = true;
        Some(pv)
    }

    fn wins(&mut self, candidates: &[usize], side: u8) -> Vec<usize> {
        candidates
            .iter()
            .copied()
            .filter(|p| self.board.would_win(*p, side) && self.board.legal(*p, side))
            .collect()
    }

    fn creates_four(&mut self, p: usize) -> bool {
        self.board.cells[p] = self.attacker;
        let (x, y) = (
            (p % self.board.size) as isize,
            (p / self.board.size) as isize,
        );
        let mut found = false;
        'directions: for (dx, dy) in DIRS {
            for k in -4..=4 {
                let (xx, yy) = (x + dx * k, y + dy * k);
                if self.board.at(xx, yy) == 0 {
                    let q = yy as usize * self.board.size + xx as usize;
                    if self.board.would_win(q, self.attacker) {
                        found = true;
                        break 'directions;
                    }
                }
            }
        }
        self.board.cells[p] = 0;
        found
    }

    pub fn advance(&mut self, batch: usize) -> Option<Vec<usize>> {
        for _ in 0..batch {
            if self.done {
                break;
            }
            if self.nodes >= self.budget {
                self.done = true;
                break;
            }
            let i = self.stack.len() - 1;
            if !self.stack[i].entered {
                self.nodes += 1;
                self.stack[i].entered = true;
                let side = self.stack[i].side;
                if self.failed.contains(&self.stack[i].key) {
                    self.fail();
                    continue;
                }
                if let Some(&(p, color)) = self.board.history.last() {
                    if self.board.would_win(p, color) {
                        if color == self.attacker {
                            return self.proof(&[]);
                        }
                        self.fail();
                        continue;
                    }
                }
                let ply = self.board.history.len() - self.start;
                if ply >= self.max_plies {
                    self.fail();
                    continue;
                }
                let candidates = self.board.candidates();
                let attack_wins = self.wins(&candidates, self.attacker);
                let defense_wins = self.wins(&candidates, 3 - self.attacker);
                if side == self.attacker {
                    if let Some(p) = attack_wins.first() {
                        return self.proof(&[*p]);
                    }
                    if defense_wins.len() >= 2 {
                        self.fail();
                        continue;
                    }
                    let options = if defense_wins.is_empty() {
                        candidates
                    } else {
                        defense_wins
                    };
                    let mut moves: Vec<_> = options
                        .into_iter()
                        .filter(|p| self.board.legal(*p, side) && self.creates_four(*p))
                        .collect();
                    moves.sort_by_cached_key(|p| -self.board.move_score(*p, side));
                    self.stack[i].moves = moves;
                } else {
                    // A defender's immediate win beats any threat by attacker.
                    if !defense_wins.is_empty() || attack_wins.is_empty() {
                        self.fail();
                        continue;
                    }
                    if attack_wins.len() >= 2 {
                        if let Some(proof) = self.proof(&[attack_wins[0], attack_wins[1]]) {
                            return Some(proof);
                        }
                        self.fail();
                        continue;
                    }
                    // All other defenses allow an immediate five; the sole
                    // blocking move is the only non-losing response to explore.
                    self.stack[i].moves = vec![attack_wins[0]];
                }
            }
            let i = self.stack.len() - 1;
            if self.stack[i].next == self.stack[i].moves.len() {
                self.fail();
                continue;
            }
            let p = self.stack[i].moves[self.stack[i].next];
            self.stack[i].next += 1;
            let side = self.stack[i].side;
            self.board.make(p, side);
            self.push(3 - side, true);
        }
        None
    }
}
