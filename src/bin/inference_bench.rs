//! Deterministic inference workload and quantization-error diagnostics.
use nolos_nnue::board::{Board, Rule};
use nolos_nnue::experiment::{arguments, number, validate_keys, weights, Rng};
use std::hint::black_box;
use std::time::Instant;

fn main() {
    if let Err(e) = work() {
        eprintln!("inference_bench: {e}");
        std::process::exit(1);
    }
}
fn work() -> Result<(), String> {
    let args = arguments()?;
    validate_keys(&args, &["weights", "precision", "repeats", "samples"])?;
    let net =
        weights(args.get("weights").ok_or("--weights required")?)?.ok_or("weights required")?;
    let quant = net.with_precision("int16")?;
    let precision = args.get("precision").map(String::as_str).unwrap_or("fp32");
    let active = net.with_precision(precision)?;
    let samples = number(&args, "samples", 1000usize)?;
    let repeats = number(&args, "repeats", 100000usize)?;
    if samples == 0 || repeats == 0 {
        return Err("positive samples/repeats required".into());
    }
    let mut rng = Rng(20261005);
    let mut errors = Vec::new();
    for _ in 0..samples {
        let mut b = Board::new(15, Rule::Freestyle)?;
        let plies = 4 + rng.index(60);
        for ply in 0..plies {
            let free: Vec<_> = (0..225).filter(|p| b.cells[*p] == 0).collect();
            let p = free[rng.index(free.len())];
            b.make(p, (ply % 2 + 1) as u8);
            if b.winner().is_some() {
                b.undo();
                break;
            }
        }
        b.set_network(Some(net.clone()));
        let fp = b.evaluate(1);
        b.set_network(Some(quant.clone()));
        errors.push((b.evaluate(1) - fp).abs());
    }
    errors.sort_unstable();
    let mut b = Board::new(15, Rule::Freestyle)?;
    for (i, p) in [112, 113, 97, 127, 96, 128, 81, 66].iter().enumerate() {
        b.make(*p, (i % 2 + 1) as u8);
    }
    b.set_network(Some(active));
    // Same make/evaluate/undo sequence in both modes, independent of search decisions.
    let moves: Vec<_> = (0..225).filter(|p| b.cells[*p] == 0).collect();
    let started = Instant::now();
    let mut checksum = 0i64;
    for i in 0..repeats {
        b.make(moves[i % moves.len()], 1);
        checksum += black_box(b.evaluate(2)) as i64;
        b.undo();
    }
    let seconds = started.elapsed().as_secs_f64();
    let mean = errors.iter().map(|e| *e as f64).sum::<f64>() / samples as f64;
    println!("{{\"precision\":\"{precision}\",\"repeats\":{repeats},\"seconds\":{seconds},\"checksum\":{checksum},\"error_samples\":{samples},\"mean_abs_error\":{mean},\"p95_abs_error\":{},\"max_abs_error\":{}}}", errors[(samples-1)*95/100], errors[samples-1]);
    Ok(())
}
