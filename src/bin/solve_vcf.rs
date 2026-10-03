//! Offline tactical audit. Each input line: size side square:color ...
use nolos_nnue::board::{Board, Rule};
use nolos_nnue::experiment::{arguments, number, validate_keys};
use nolos_nnue::vcf::Vcf;

fn main() {
    if let Err(error) = work() {
        eprintln!("solve_vcf: {error}");
        std::process::exit(1);
    }
}

fn work() -> Result<(), String> {
    let args = arguments()?;
    validate_keys(&args, &["input", "nodes", "depth"])?;
    let input = args.get("input").ok_or("--input is required")?;
    let budget = number(&args, "nodes", 20_000u64)?;
    let depth = number(&args, "depth", 63usize)?;
    for (index, line) in std::fs::read_to_string(input)
        .map_err(|e| e.to_string())?
        .lines()
        .enumerate()
    {
        let mut fields = line.split_whitespace();
        let mut next = || {
            fields
                .next()
                .ok_or("missing size or side")?
                .parse::<usize>()
                .map_err(|e| e.to_string())
        };
        let size = next()?;
        let side = next()? as u8;
        let mut board = Board::new(size, Rule::Freestyle)?;
        for field in fields {
            let (p, color) = field.split_once(':').ok_or("expected square:color")?;
            let p = p.parse::<usize>().map_err(|e| e.to_string())?;
            let color = color.parse::<u8>().map_err(|e| e.to_string())?;
            if p >= board.cells.len()
                || color != (board.history.len() % 2 + 1) as u8
                || board.winner().is_some()
                || !board.legal(p, color)
            {
                return Err("invalid move sequence".into());
            }
            board.make(p, color);
        }
        if side != (board.history.len() % 2 + 1) as u8 || board.winner().is_some() {
            return Err("invalid side or already finished position".into());
        }
        let mut solver = Vcf::new(board, side, depth, budget);
        let mut proof = None;
        while !solver.done {
            proof = solver.advance(128);
            if proof.is_some() {
                break;
            }
        }
        let pv = proof
            .as_ref()
            .map(|p| {
                p.iter()
                    .map(|q| q.to_string())
                    .collect::<Vec<_>>()
                    .join(",")
            })
            .unwrap_or_default();
        println!(
            "{{\"position\":{index},\"nodes\":{},\"proved\":{},\"pv\":[{pv}]}}",
            solver.nodes,
            proof.is_some()
        );
    }
    Ok(())
}
