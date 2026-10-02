use nolos_nnue::board::{mix64, Board, Rule};
use nolos_nnue::experiment::*;
use nolos_nnue::search::MATE;
use std::io::{BufWriter, IsTerminal, Write};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

struct Sample {
    board: Board,
    side: u8,
    score: i32,
    depth: usize,
    nodes: u64,
}

fn main() {
    if let Err(e) = work() {
        eprintln!("selfplay: {e}");
        std::process::exit(1);
    }
}

fn work() -> Result<(), String> {
    let args = arguments()?;
    validate_keys(
        &args,
        &[
            "games",
            "size",
            "rule",
            "seed",
            "nodes",
            "depth",
            "branch",
            "threads",
            "output",
            "weights",
            "exploration",
            "max-plies",
        ],
    )?;
    let games = number(&args, "games", 128usize)?;
    let size = number(&args, "size", 15usize)?;
    let rule = Rule::from_id(number(&args, "rule", 0i32)?)?;
    Board::new(size, rule)?;
    let seed = number(&args, "seed", 1u64)?;
    let threads = number(&args, "threads", 1usize)?;
    let max_plies = number(&args, "max-plies", size * size)?;
    let exploration = number(&args, "exploration", 0.10f64)?;
    if games == 0
        || threads == 0
        || threads > 256
        || max_plies < 7
        || !exploration.is_finite()
        || !(0.0..=1.0).contains(&exploration)
    {
        return Err("invalid games, threads, max-plies, or exploration".into());
    }
    let path = args
        .get("output")
        .map(String::as_str)
        .unwrap_or("selfplay.jsonl");
    let teacher = args.get("weights").map(String::as_str).unwrap_or("hce");
    let network = weights(teacher)?;
    let limits = standard_limits(&args)?;
    let file = std::fs::File::create(path).map_err(|e| e.to_string())?;
    let (tx, rx) = std::sync::mpsc::sync_channel::<(usize, Vec<Sample>, Option<u8>)>(threads * 2);
    let next = Arc::new(AtomicUsize::new(0));
    let mut handles = Vec::new();
    for _ in 0..threads.min(games) {
        let (tx, next, network, limits) =
            (tx.clone(), next.clone(), network.clone(), limits.clone());
        handles.push(std::thread::spawn(move || -> Result<(), String> {
            let mut player = Player::new(network, limits);
            loop {
                let game = next.fetch_add(1, Ordering::Relaxed);
                if game >= games {
                    break;
                }
                player.reset();
                let game_seed = mix64(seed ^ game as u64);
                let mut rng = Rng(game_seed ^ 0xa73e);
                let mut board = opening(game_seed, size, rule);
                let mut samples = Vec::new();
                let mut winner = None;
                while board.history.len() < max_plies.min(size * size) {
                    let side = (board.history.len() % 2 + 1) as u8;
                    let result = player.choose(&board, side)?;
                    let mut p = result.best.unwrap();
                    // Explore only non-tactical early positions; labels describe
                    // the searched position, while outcomes come from actual play.
                    let tactical = board.candidates().iter().any(|q| {
                        [side, 3 - side]
                            .iter()
                            .any(|c| board.would_win(*q, *c) && board.legal(*q, *c))
                    });
                    if !tactical
                        && board.history.len() < 20
                        && result.score.abs() < 1500
                        && rng.uniform() < exploration
                    {
                        let mut candidates = board.candidates();
                        candidates.retain(|q| board.legal(*q, side));
                        candidates.sort_by_key(|q| {
                            -(board.move_score(*q, side) * 2 + board.move_score(*q, 3 - side))
                        });
                        if !candidates.is_empty() {
                            p = candidates[rng.index(candidates.len().min(5))];
                        }
                    }
                    if result.depth > 0 && result.score.abs() < MATE - 500 {
                        samples.push(Sample {
                            board: board.clone(),
                            side,
                            score: result.score,
                            depth: result.depth,
                            nodes: result.nodes,
                        });
                    }
                    if !board.legal(p, side) {
                        return Err("search produced an illegal move".into());
                    }
                    board.make(p, side);
                    if board.would_win(p, side) {
                        winner = Some(side);
                        break;
                    }
                }
                // Only a full board is a genuine draw. Truncation stays unlabeled.
                if winner.is_none() && board.history.len() == size * size {
                    winner = Some(0);
                }
                tx.send((game, samples, winner))
                    .map_err(|e| e.to_string())?;
            }
            Ok(())
        }));
    }
    drop(tx);
    let mut writer = BufWriter::new(file);
    let interactive = std::io::stderr().is_terminal();
    let mut progress_visible = false;
    let (mut positions, mut finished, mut truncated) = (0usize, 0usize, 0usize);
    for (game, samples, winner) in rx {
        finished += 1;
        if winner.is_none() {
            truncated += 1;
        }
        for sample in samples {
            let board: String = sample
                .board
                .cells
                .iter()
                .map(|c| (b'0' + *c) as char)
                .collect();
            let outcome = match winner {
                Some(0) => "0.5".to_string(),
                Some(c) => if c == sample.side { "1" } else { "0" }.into(),
                None => "null".into(),
            };
            let features = sample
                .board
                .counts
                .iter()
                .enumerate()
                .filter(|(_, n)| **n > 0)
                .map(|(id, n)| format!("[{id},{n}]"))
                .collect::<Vec<_>>()
                .join(",");
            writeln!(writer, "{{\"game\":{game},\"seed\":{seed},\"size\":{size},\"rule\":{},\"side\":{},\"board\":\"{board}\",\"score\":{},\"outcome\":{outcome},\"depth\":{},\"nodes\":{},\"features\":[{features}]}}",
                rule.id(), sample.side, sample.score, sample.depth, sample.nodes).map_err(|e| e.to_string())?;
            positions += 1;
        }
        if finished % 16 == 0 || finished == games {
            let progress = format!(
                "selfplay {finished}/{games}, {positions} positions, {truncated} truncated games"
            );
            if interactive {
                eprint!("\r{progress}");
                std::io::stderr().flush().map_err(|e| e.to_string())?;
                progress_visible = true;
            } else {
                eprintln!("{progress}");
            }
        }
    }
    if progress_visible {
        eprintln!();
    }
    writer.flush().map_err(|e| e.to_string())?;
    for handle in handles {
        handle.join().map_err(|_| "selfplay worker panicked")??;
    }
    if positions == 0 {
        return Err("no completed-search training positions generated".into());
    }
    eprintln!("saved {path}: {positions} positions, teacher={teacher}, external_data=false");
    Ok(())
}
