use nolos_nnue::board::{mix64, Board, Rule};
use nolos_nnue::experiment::*;
use std::io::Write;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

fn main() {
    if let Err(e) = work() {
        eprintln!("arena: {e}");
        std::process::exit(1);
    }
}

fn work() -> Result<(), String> {
    let args = arguments()?;
    validate_keys(
        &args,
        &[
            "candidate",
            "baseline",
            "pairs",
            "size",
            "rule",
            "seed",
            "depth",
            "nodes",
            "branch",
            "threads",
            "max-plies",
            "output",
        ],
    )?;
    let candidate = args
        .get("candidate")
        .ok_or("--candidate PATH is required")?;
    let baseline = args.get("baseline").map(String::as_str).unwrap_or("hce");
    let candidate_net = weights(candidate)?;
    let baseline_net = weights(baseline)?;
    let pairs = number(&args, "pairs", 64usize)?;
    let threads = number(&args, "threads", 1usize)?;
    let size = number(&args, "size", 15usize)?;
    let rule = Rule::from_id(number(&args, "rule", 0i32)?)?;
    Board::new(size, rule)?;
    let seed = number(&args, "seed", 900000u64)?;
    let max_plies = number(&args, "max-plies", size * size)?;
    if pairs == 0 || threads == 0 || threads > 256 || max_plies < 7 {
        return Err("invalid pairs, threads, or max-plies".into());
    }
    let limits = standard_limits(&args)?;
    let next = Arc::new(AtomicUsize::new(0));
    let (tx, rx) = std::sync::mpsc::channel();
    let mut handles = Vec::new();
    for _ in 0..threads.min(pairs) {
        let (tx, next) = (tx.clone(), next.clone());
        let (cn, bn, limits) = (candidate_net.clone(), baseline_net.clone(), limits.clone());
        handles.push(std::thread::spawn(move || -> Result<(), String> {
            let mut cp = Player::new(cn, limits.clone());
            let mut bp = Player::new(bn, limits);
            loop {
                let pair = next.fetch_add(1, Ordering::Relaxed);
                if pair >= pairs {
                    break;
                }
                let open = opening(mix64(seed ^ pair as u64), size, rule);
                let mut outcomes = Vec::new();
                for candidate_side in [1, 2] {
                    cp.reset();
                    bp.reset();
                    let mut board = open.clone();
                    let mut outcome = None;
                    while board.history.len() < max_plies.min(size * size) {
                        let side = (board.history.len() % 2 + 1) as u8;
                        let player = if side == candidate_side {
                            &mut cp
                        } else {
                            &mut bp
                        };
                        let p = player.choose(&board, side)?.best.unwrap();
                        if !board.legal(p, side) {
                            return Err("illegal arena move".into());
                        }
                        board.make(p, side);
                        if board.would_win(p, side) {
                            outcome = Some(if side == candidate_side { 1.0 } else { 0.0 });
                            break;
                        }
                    }
                    if outcome.is_none() && board.history.len() == size * size {
                        outcome = Some(0.5);
                    }
                    outcomes.push(outcome);
                }
                tx.send((pair, outcomes)).map_err(|e| e.to_string())?;
            }
            Ok(())
        }));
    }
    drop(tx);
    let mut results: Vec<_> = rx.into_iter().collect();
    for handle in handles {
        handle.join().map_err(|_| "arena worker panicked")??;
    }
    results.sort_by_key(|r| r.0);
    let (mut wins, mut losses, mut draws, mut truncated) = (0, 0, 0, 0);
    let mut pair_scores = Vec::new();
    for (_, outcomes) in &results {
        for outcome in outcomes {
            match outcome {
                Some(s) if *s == 1.0 => wins += 1,
                Some(s) if *s == 0.0 => losses += 1,
                Some(_) => draws += 1,
                None => truncated += 1,
            }
        }
        if outcomes.iter().all(|r| r.is_some()) {
            pair_scores.push(outcomes.iter().map(|r| r.unwrap()).sum::<f64>() / 2.0);
        }
    }
    let complete = wins + losses + draws;
    let score = if complete > 0 {
        (wins as f64 + draws as f64 * 0.5) / complete as f64
    } else {
        0.5
    };
    let paired_mean = if pair_scores.is_empty() {
        0.5
    } else {
        pair_scores.iter().sum::<f64>() / pair_scores.len() as f64
    };
    // Approximate 95% interval over independent opening pairs, not correlated games.
    let error = if pair_scores.len() > 1 {
        let variance = pair_scores
            .iter()
            .map(|s| (s - paired_mean).powi(2))
            .sum::<f64>()
            / (pair_scores.len() - 1) as f64;
        1.96 * (variance / pair_scores.len() as f64).sqrt()
    } else {
        0.5
    };
    let lower = if pair_scores.len() < 32 {
        0.0
    } else {
        (paired_mean - error).max(0.0)
    };
    let upper = if pair_scores.len() < 32 {
        1.0
    } else {
        (paired_mean + error).min(1.0)
    };
    let elo = if score > 0.0 && score < 1.0 {
        format!("{:.2}", 400.0 * (score / (1.0 - score)).log10())
    } else {
        "null".into()
    };
    let serialized = results
        .iter()
        .map(|(pair, outcomes)| {
            format!(
                "{{\"pair\":{pair},\"scores\":[{}]}}",
                outcomes
                    .iter()
                    .map(|s| s.map(|v| v.to_string()).unwrap_or("null".into()))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let report = format!("{{\"schema\":1,\"seed\":{seed},\"rule\":{},\"size\":{size},\"pairs\":{pairs},\"complete_pairs\":{},\"games\":{},\"wins\":{wins},\"losses\":{losses},\"draws\":{draws},\"truncated\":{truncated},\"score\":{score:.6},\"paired_mean\":{paired_mean:.6},\"paired_ci95\":[{lower:.6},{upper:.6}],\"relative_elo\":{elo},\"nodes\":{},\"depth\":{},\"branch\":{},\"results\":[{serialized}]}}",
        rule.id(), pair_scores.len(), pairs * 2, limits.nodes, limits.depth, limits.branch);
    if let Some(path) = args.get("output") {
        std::fs::File::create(path)
            .and_then(|mut f| writeln!(f, "{report}"))
            .map_err(|e| e.to_string())?;
    }
    println!("{report}");
    eprintln!("candidate vs {baseline}: {wins}W/{losses}L/{draws}D, {truncated} truncated, score={score:.3}, paired CI≈[{lower:.3},{upper:.3}]");
    Ok(())
}
