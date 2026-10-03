//! Fixed-position diagnostics. Input: size side square:color ... per line.
use nolos_nnue::board::{Board, Rule};
use nolos_nnue::experiment::{arguments, number, validate_keys, weights};
use nolos_nnue::search::{now_ms, Limits, Search, Table};
use std::time::Instant;

fn main() {
    if let Err(e) = work() {
        eprintln!("search_bench: {e}");
        std::process::exit(1);
    }
}

fn work() -> Result<(), String> {
    let args = arguments()?;
    validate_keys(&args, &["input", "weights", "nodes", "repeats", "qdepth"])?;
    let input = args.get("input").ok_or("--input required")?;
    let nodes = number(&args, "nodes", 50_000u64)?;
    let repeats = number(&args, "repeats", 3usize)?;
    let qdepth = number(&args, "qdepth", Limits::default().qdepth)?;
    if nodes == 0 || repeats == 0 {
        return Err("positive nodes/repeats required".into());
    }
    let network = weights(args.get("weights").map(String::as_str).unwrap_or("hce"))?;
    for (position, line) in std::fs::read_to_string(input)
        .map_err(|e| e.to_string())?
        .lines()
        .enumerate()
    {
        let mut fields = line.split_whitespace();
        let size = fields
            .next()
            .ok_or("size missing")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        let side = fields
            .next()
            .ok_or("side missing")?
            .parse::<u8>()
            .map_err(|e| e.to_string())?;
        let mut board = Board::new(size, Rule::Freestyle)?;
        for field in fields {
            let (p, c) = field.split_once(':').ok_or("expected square:color")?;
            let p = p.parse::<usize>().map_err(|e| e.to_string())?;
            let c = c.parse::<u8>().map_err(|e| e.to_string())?;
            if c != (board.history.len() % 2 + 1) as u8
                || !board.legal(p, c)
                || board.winner().is_some()
            {
                return Err("invalid move sequence".into());
            }
            board.make(p, c);
        }
        if side != (board.history.len() % 2 + 1) as u8 || board.winner().is_some() {
            return Err("invalid side or finished position".into());
        }
        board.set_network(network.clone());
        for repeat in 0..repeats {
            let mut search = Search::new(
                board.clone(),
                side,
                Limits {
                    depth: 64,
                    nodes,
                    time_ms: 1e12,
                    branch: 16,
                    qdepth,
                },
                Table::new(65536),
                now_ms(),
            );
            let started = Instant::now();
            let mut vcf_seconds = 0.0;
            while !search.done {
                let vcf = search.vcf_active();
                let phase = Instant::now();
                // One step during VCF isolates its time from the normal-search batch.
                search.advance(if vcf { 1 } else { 128 }, now_ms());
                if vcf {
                    vcf_seconds += phase.elapsed().as_secs_f64();
                }
            }
            let seconds = started.elapsed().as_secs_f64();
            let r = &search.result;
            println!("{{\"position\":{position},\"repeat\":{repeat},\"seconds\":{seconds},\"vcf_seconds\":{vcf_seconds},\"vcf_nodes\":{},\"nodes\":{},\"depth\":{},\"selective_depth\":{},\"vcf_depth\":{},\"score\":{},\"best\":{},\"nps\":{}}}", search.vcf_nodes, r.nodes, r.depth, search.selective_depth, r.vcf_depth, r.score, r.best.map(|p|p.to_string()).unwrap_or("null".into()), r.nodes as f64 / seconds.max(1e-9));
        }
    }
    Ok(())
}
