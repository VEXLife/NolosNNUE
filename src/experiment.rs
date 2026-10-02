use crate::board::{mix64, Board, Rule};
use crate::network::Network;
use crate::search::{run, Limits, ResultInfo, Table};
use std::collections::HashMap;
use std::sync::Arc;

pub struct Rng(pub u64);
impl Rng {
    pub fn next_u64(&mut self) -> u64 {
        self.0 = mix64(self.0);
        self.0
    }
    pub fn index(&mut self, n: usize) -> usize {
        (self.next_u64() % n as u64) as usize
    }
    pub fn uniform(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
}

pub fn arguments() -> Result<HashMap<String, String>, String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if !args.len().is_multiple_of(2) {
        return Err("arguments must be --key value pairs".into());
    }
    let mut out = HashMap::new();
    for pair in args.as_chunks::<2>().0 {
        if !pair[0].starts_with("--") {
            return Err(format!("invalid argument {}", pair[0]));
        }
        out.insert(pair[0][2..].to_owned(), pair[1].to_owned());
    }
    Ok(out)
}
pub fn number<T: std::str::FromStr>(
    args: &HashMap<String, String>,
    key: &str,
    default: T,
) -> Result<T, String> {
    args.get(key)
        .map(|s| s.parse::<T>().map_err(|_| format!("invalid --{key}")))
        .unwrap_or(Ok(default))
}
pub fn weights(path: &str) -> Result<Option<Arc<Network>>, String> {
    if path == "hce" {
        Ok(None)
    } else {
        Network::load(&std::fs::read(path).map_err(|e| format!("{path}: {e}"))?).map(Some)
    }
}

pub struct Player {
    pub network: Option<Arc<Network>>,
    pub table: Option<Table>,
    pub limits: Limits,
}
impl Player {
    pub fn new(network: Option<Arc<Network>>, limits: Limits) -> Self {
        Self {
            network,
            table: Some(Table::new(2048)),
            limits,
        }
    }
    pub fn choose(&mut self, board: &Board, side: u8) -> Result<ResultInfo, String> {
        let mut position = board.clone();
        position.set_network(self.network.clone());
        let (result, table) = run(
            position,
            side,
            self.limits.clone(),
            self.table.take().unwrap(),
        );
        self.table = Some(table);
        if result.best.is_none() {
            return Err("no legal move".into());
        }
        Ok(result)
    }
    pub fn reset(&mut self) {
        self.table.as_mut().unwrap().clear();
    }
}

/// Procedural six-ply openings; no book, external engine, or training positions.
/// Filter with the original HCE, and freeze the generator for all generations.
pub fn opening(seed: u64, size: usize, rule: Rule) -> Board {
    let mut rng = Rng(seed);
    for _ in 0..200 {
        let mut b = Board::new(size, rule).unwrap();
        let center = size / 2;
        for ply in 0..6 {
            let side = (ply % 2 + 1) as u8;
            let mut candidates: Vec<usize> = (0..size * size)
                .filter(|p| {
                    let x = p % size;
                    let y = p / size;
                    x.abs_diff(center) <= 2 && y.abs_diff(center) <= 2 && b.cells[*p] == 0
                })
                .collect();
            candidates.retain(|p| b.legal(*p, side) && !b.would_win(*p, side));
            if candidates.is_empty() {
                break;
            }
            let p = if ply == 0 {
                center * size + center
            } else {
                candidates[rng.index(candidates.len())]
            };
            if b.cells[p] != 0 {
                break;
            }
            b.make(p, side);
        }
        let mut tactical = false;
        for p in b.candidates() {
            for side in [1, 2] {
                if b.would_win(p, side) && b.legal(p, side) {
                    tactical = true;
                }
            }
        }
        if b.history.len() == 6 && b.hce.abs() <= 600 && !tactical {
            return b;
        }
    }
    // Rare fallback is still procedural and valid.
    let mut b = Board::new(size, rule).unwrap();
    let c = size / 2;
    for (dx, dy, side) in [
        (0, 0, 1),
        (1, 0, 2),
        (-1, 1, 1),
        (0, 1, 2),
        (1, -1, 1),
        (-1, -1, 2),
    ] {
        let p = (c as isize + dy) as usize * size + (c as isize + dx) as usize;
        b.make(p, side);
    }
    b
}

pub fn standard_limits(args: &HashMap<String, String>) -> Result<Limits, String> {
    let depth = number(args, "depth", 3usize)?;
    let nodes = number(args, "nodes", 2000u64)?;
    let branch = number(args, "branch", 12usize)?;
    if depth == 0 || depth > 64 || nodes == 0 || branch == 0 || branch > 400 {
        return Err("depth 1..64, positive nodes, branch 1..400 required".into());
    }
    Ok(Limits {
        depth,
        nodes,
        branch,
        qdepth: 6,
        time_ms: 1e12,
    })
}

pub fn validate_keys(args: &HashMap<String, String>, allowed: &[&str]) -> Result<(), String> {
    for key in args.keys() {
        if !allowed.contains(&key.as_str()) {
            return Err(format!("unknown argument --{key}"));
        }
    }
    Ok(())
}
