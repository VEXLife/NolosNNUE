use nolos_nnue::board::{Board, Rule};
use nolos_nnue::network::{Network, FEATURES, HIDDEN};
use nolos_nnue::protocol::Engine;
use nolos_nnue::search::{run, Limits, Search, Table, MATE};
use nolos_nnue::vcf::Vcf;
use std::sync::Arc;

fn vcf_proof(board: Board, side: u8, depth: usize, nodes: u64) -> Option<Vec<usize>> {
    let mut search = Vcf::new(board, side, depth, nodes);
    while !search.done {
        if let Some(pv) = search.advance(1) {
            return Some(pv);
        }
    }
    None
}

#[test]
fn fast_win_rays_match_independent_full_line_scan() {
    fn expected(board: &Board, p: usize, color: u8) -> bool {
        [(1, 0), (0, 1), (1, 1), (1, -1)].iter().any(|(dx, dy)| {
            let mut count = 1;
            for sign in [-1, 1] {
                let (mut x, mut y) = ((p % board.size) as isize + dx * sign,
                                     (p / board.size) as isize + dy * sign);
                while x >= 0 && y >= 0 && x < board.size as isize && y < board.size as isize
                    && board.cells[y as usize * board.size + x as usize] == color {
                    count += 1;
                    x += dx * sign;
                    y += dy * sign;
                }
            }
            if board.rule == Rule::Standard || (board.rule == Rule::Renju && color == 1) {
                count == 5
            } else { count >= 5 }
        })
    }
    for size in [5, 9, 15, 20] {
        let mut board = Board::new(size, Rule::Freestyle).unwrap();
        // Include long lines, edge wins, and the temporary raw-cell mutations
        // used by tactical solvers; no make()/cache update is required.
        for sample in 0..24 {
            for p in 0..size * size {
                board.cells[p] = if sample < 3 { sample as u8 } else {
                    (nolos_nnue::board::mix64((sample * size * size + p) as u64) % 3) as u8
                };
            }
            for rule in [Rule::Freestyle, Rule::Standard, Rule::Renju] {
                board.rule = rule;
                for p in 0..size * size {
                    for color in [1, 2] {
                        assert_eq!(board.would_win(p, color), expected(&board, p, color),
                                   "size={size} sample={sample} rule={rule:?} p={p} color={color}");
                    }
                }
            }
        }
    }
}

#[test]
fn incremental_win_cache_survives_moves_undo_remove_and_rule_changes() {
    fn check(board: &mut Board) {
        for rule in [Rule::Freestyle, Rule::Standard, Rule::Renju] {
            board.rule = rule;
            for p in 0..board.cells.len() {
                for color in [1, 2] {
                    assert_eq!(board.cached_would_win(p, color), board.would_win(p, color),
                               "size={} p={p} color={color} rule={rule:?}", board.size);
                }
            }
        }
    }
    for size in [5, 9, 15, 20] {
        let mut board = Board::new(size, Rule::Freestyle).unwrap();
        check(&mut board);
        for step in 0..size * size {
            let mut p = nolos_nnue::board::mix64(step as u64 + 817) as usize % board.cells.len();
            while board.cells[p] != 0 { p = (p + 1) % board.cells.len(); }
            board.make(p, (step % 2 + 1) as u8);
            check(&mut board);
        }
        while !board.history.is_empty() {
            if board.history.len() % 3 == 0 {
                let p = board.history[board.history.len() / 2].0;
                board.remove(p).unwrap();
            } else { board.undo(); }
            check(&mut board);
        }
        // Explicit long lines exercise exact-five -> overline -> five transitions.
        for p in 0..size { board.make(p, 1); check(&mut board); }
        while board.undo().is_some() { check(&mut board); }
        // Direct tactical probes intentionally leave the cache untouched, then
        // restore cells. Full reconstruction is available for bulk position loads.
        for p in 0..board.cells.len() { board.cells[p] = (p % 3) as u8; }
        board.rebuild_win_cache();
        check(&mut board);
    }
}

#[test]
fn experimental_selectivity_is_opt_in_and_changes_only_between_searches() {
    let mut engine = Engine::new();
    assert_eq!(engine.command("START 15", 0.0), vec!["OK"]);
    for command in ["YXBOARD", "7,7,1", "8,7,2", "DONE", "INFO max_depth 64",
                    "INFO max_node 1000000", "INFO selective_search 1", "YXSUGGEST"] {
        engine.command(command, 0.0);
    }
    assert!(engine.search.as_ref().unwrap().selective_search);
    engine.command("INFO selective_search 0", 0.0);
    assert!(engine.search.as_ref().unwrap().selective_search);
    engine.command("YXSTOP", 0.0);
    assert_eq!(engine.board.history.len(), 2);
    engine.command("INFO selective_search 0", 0.0);
    engine.command("INFO selective_search 2", 0.0); // Invalid values cannot opt in.
    engine.command("YXSUGGEST", 0.0);
    assert!(!engine.search.as_ref().unwrap().selective_search);
    engine.command("YXSTOP", 0.0);
}

#[test]
fn vcf_proves_forcing_win_but_never_ignores_counterwin_or_limits() {
    let board = position(Rule::Freestyle, &[(4, 7), (5, 7), (6, 7)], &[]);
    let hash = board.hash;
    let counts = board.counts.clone();
    let proof = vcf_proof(board.clone(), 1, 63, 1000).unwrap();
    assert_eq!(proof.len(), 3);
    let mut played = board.clone();
    for (i, p) in proof.iter().enumerate() {
        let side = (i % 2 + 1) as u8;
        assert!(played.legal(*p, side));
        played.make(*p, side);
        assert!(i == proof.len() - 1 || played.winner().is_none());
    }
    assert_eq!(played.winner(), Some(1));
    assert_eq!(board.hash, hash);
    assert_eq!(board.counts, counts);
    assert!(vcf_proof(board.clone(), 1, 1, 1000).is_none());
    assert!(vcf_proof(board, 1, 63, 1).is_none());
    let counter = position(
        Rule::Freestyle,
        &[(4, 7), (5, 7), (6, 7)],
        &[(0, 0), (1, 0), (2, 0), (3, 0)],
    );
    assert!(vcf_proof(counter, 1, 63, 1000).is_none());
}

#[test]
fn pvs_matches_exhaustive_negamax_on_small_quiet_positions() {
    fn exact(board: &mut Board, side: u8, depth: usize, ply: usize) -> i32 {
        if let Some(&(p, color)) = board.history.last() {
            if board.would_win(p, color) {
                return -MATE + ply as i32;
            }
        }
        let mut candidates = board.candidates();
        candidates.retain(|p| board.legal(*p, side));
        if candidates.iter().any(|p| board.would_win(*p, side)) {
            return MATE - ply as i32 - 1;
        }
        if depth == 0 {
            return board.evaluate(side);
        }
        let mut value = -32000;
        for p in candidates {
            board.make(p, side);
            value = value.max(-exact(board, 3 - side, depth - 1, ply + 1));
            board.undo();
        }
        value
    }
    for second_black in [6, 7, 11, 13, 16] {
        let mut board = Board::new(5, Rule::Freestyle).unwrap();
        for (p, color) in [(12, 1), (0, 2), (second_black, 1), (24, 2)] {
            board.make(p, color);
        }
        let expected = exact(&mut board.clone(), 1, 3, 0);
        let (actual, _) = run(
            board,
            1,
            Limits {
                depth: 3,
                nodes: 1_000_000,
                time_ms: 1e9,
                branch: 400,
                qdepth: 0,
            },
            Table::new(1024),
        );
        assert_eq!(actual.depth, 3);
        assert_eq!(actual.score, expected, "second black stone {second_black}");
    }
}

#[test]
fn incremental_candidates_match_full_radius_scan_after_make_undo_and_remove() {
    fn check(board: &Board) {
        let expected: Vec<_> = if board.history.is_empty() {
            vec![(board.size / 2) * board.size + board.size / 2]
        } else {
            (0..board.cells.len())
                .filter(|p| {
                    board.cells[*p] == 0
                        && board.history.iter().any(|(q, _)| {
                            (p % board.size).abs_diff(q % board.size) <= 2
                                && (p / board.size).abs_diff(q / board.size) <= 2
                        })
                })
                .collect()
        };
        assert_eq!(board.candidates(), expected);
    }
    for size in [5, 9, 15, 20] {
        let mut board = Board::new(size, Rule::Freestyle).unwrap();
        check(&board);
        for i in 0..20.min(size * size) {
            let mut p = (nolos_nnue::board::mix64(i as u64 + 15) as usize) % board.cells.len();
            while board.cells[p] != 0 {
                p = (p + 1) % board.cells.len();
            }
            board.make(p, (i % 2 + 1) as u8);
            check(&board);
        }
        board.remove(board.history[3].0).unwrap();
        check(&board);
        while board.undo().is_some() {
            check(&board);
        }
    }
}

#[test]
fn vcf_long_line_from_rapfi_loss_survives_every_off_line_defense() {
    let moves = [
        112, 96, 81, 83, 67, 97, 95, 109, 53, 39, 69, 68, 84, 98, 114, 99, 100, 110, 124, 115, 108,
        85, 113, 86, 78, 101, 71, 88, 73, 102, 70, 72, 87,
    ];
    let mut board = Board::new(15, Rule::Freestyle).unwrap();
    for (i, p) in moves.iter().enumerate() {
        board.make(*p, (i % 2 + 1) as u8);
    }
    let proof = vcf_proof(board.clone(), 2, 63, 20000).unwrap();
    assert_eq!(proof.len(), 7);
    assert_forcing_proof(board, 2, &proof);
}

fn assert_forcing_proof(mut board: Board, attacker: u8, proof: &[usize]) {
    for (i, p) in proof.iter().enumerate() {
        let side = if i % 2 == 0 { attacker } else { 3 - attacker };
        if side != attacker {
            // Independently inspect every legal defense, including squares
            // outside the solver's candidate area. Other replies lose at once.
            for alternative in 0..board.cells.len() {
                if alternative == *p || !board.legal(alternative, side) {
                    continue;
                }
                board.make(alternative, side);
                assert_ne!(board.winner(), Some(side));
                assert!((0..board.cells.len())
                    .any(|q| board.cells[q] == 0 && board.would_win(q, attacker)));
                board.undo();
            }
        }
        assert!(board.legal(*p, side));
        board.make(*p, side);
        assert!(i == proof.len() - 1 || board.winner().is_none());
    }
    assert_eq!(board.winner(), Some(attacker));
}

#[test]
fn root_vcf_proves_seventeen_plies_even_with_normal_depth_one() {
    // Perturbation of the saved Rapfi loss, preserving stone counts. The
    // complete forcing line is checked independently against all defenses.
    let black = [
        112, 81, 67, 95, 53, 69, 84, 114, 100, 124, 108, 113, 78, 71, 73, 70, 29,
    ];
    let white = [
        96, 83, 97, 109, 39, 68, 98, 99, 110, 115, 85, 101, 88, 102, 72, 42,
    ];
    let mut board = Board::new(15, Rule::Freestyle).unwrap();
    for (i, p) in black.iter().enumerate() {
        board.make(*p, 1);
        if let Some(q) = white.get(i) {
            board.make(*q, 2);
        }
    }
    let (result, _) = run(
        board.clone(),
        2,
        Limits {
            depth: 1,
            nodes: 10000,
            time_ms: 1e9,
            branch: 12,
            qdepth: 0,
        },
        Table::new(1024),
    );
    assert_eq!(result.depth, 0); // Do not pretend this was full-width depth 17.
    assert_eq!(result.vcf_depth, 17);
    assert_eq!(result.score, MATE - 17);
    assert_eq!(result.pv.len(), 17);
    assert_forcing_proof(board, 2, &result.pv);
}

#[test]
fn root_vcf_proves_thirty_one_ply_line_with_all_defenses_checked() {
    let black = [
        112, 81, 67, 53, 69, 100, 124, 108, 78, 71, 70, 87, 139, 125, 3, 66, 161,
    ];
    let white = [
        96, 83, 109, 39, 68, 98, 99, 110, 115, 85, 101, 88, 72, 151, 143, 126,
    ];
    let mut board = Board::new(15, Rule::Freestyle).unwrap();
    for (i, p) in black.iter().enumerate() {
        board.make(*p, 1);
        if let Some(q) = white.get(i) {
            board.make(*q, 2);
        }
    }
    let (result, _) = run(
        board.clone(),
        2,
        Limits {
            depth: 1,
            nodes: 10000,
            time_ms: 1e9,
            branch: 12,
            qdepth: 0,
        },
        Table::new(1024),
    );
    assert_eq!(result.depth, 0);
    assert_eq!(result.vcf_depth, 31);
    assert_eq!(result.score, MATE - 31);
    assert_forcing_proof(board, 2, &result.pv);
}

fn position(rule: Rule, black: &[(usize, usize)], white: &[(usize, usize)]) -> Board {
    let mut b = Board::new(15, rule).unwrap();
    for &(x, y) in black {
        b.make(y * 15 + x, 1);
    }
    for &(x, y) in white {
        b.make(y * 15 + x, 2);
    }
    b
}
fn limits() -> Limits {
    Limits {
        depth: 3,
        nodes: 20_000,
        time_ms: 1e12,
        branch: 12,
        qdepth: 6,
    }
}

#[test]
fn incremental_features_hash_and_network_match_full_recomputation() {
    let net = Arc::new(Network {
        spatial: None,
        embedding: (0..FEATURES * HIDDEN)
            .map(|i| ((i * 37 % 101) as f32 - 50.0) * 0.0003)
            .collect(),
        bias: [0.4; HIDDEN],
        head: [0.2; HIDDEN],
        tempo: 0.01,
    });
    for size in [5, 9, 15, 20] {
        let mut b = Board::new(size, Rule::Freestyle).unwrap();
        b.set_network(Some(net.clone()));
        let original_hash = b.hash;
        let original_counts = b.counts.clone();
        for k in 0..size * 2 {
            let p = k * 7 % (size * size);
            if b.cells[p] != 0 {
                continue;
            }
            b.make(p, (k % 2 + 1) as u8);
            assert!(b.verify_features());
            let mut rebuilt = b.clone();
            rebuilt.rebuild_accumulators();
            for h in 0..HIDDEN {
                assert!((b.black_acc[h] - rebuilt.black_acc[h]).abs() < 0.0001);
                assert!((b.white_acc[h] - rebuilt.white_acc[h]).abs() < 0.0001);
            }
        }
        while b.undo().is_some() {
            assert!(b.verify_features());
        }
        assert_eq!(b.hash, original_hash);
        assert_eq!(b.counts, original_counts);
    }
}

#[test]
fn features_invariant_under_all_eight_board_symmetries() {
    let b = position(
        Rule::Freestyle,
        &[(1, 2), (5, 5), (8, 9)],
        &[(3, 2), (5, 7), (1, 10)],
    );
    for mirror in [false, true] {
        for rotation in 0..4 {
            let mut other = Board::new(15, Rule::Freestyle).unwrap();
            for &(p, c) in &b.history {
                let (mut x, mut y) = (p % 15, p / 15);
                if mirror {
                    x = 14 - x;
                }
                for _ in 0..rotation {
                    (x, y) = (14 - y, x);
                }
                other.make(y * 15 + x, c);
            }
            assert_eq!(b.counts, other.counts);
            assert_eq!(b.hce, other.hce);
        }
    }
}

#[test]
fn exact_five_and_overline_depend_on_rule_and_color() {
    let stones: Vec<_> = (3..8).map(|x| (x, 7)).collect();
    let p = 7 * 15 + 8;
    let mut free = position(Rule::Freestyle, &stones, &[]);
    assert!(free.would_win(p, 1));
    free.rule = Rule::Standard;
    assert!(!free.would_win(p, 1));
    free.rule = Rule::Renju;
    assert!(free.forbidden(p));
    assert!(!free.legal(p, 1));
    let white = position(Rule::Renju, &[], &stones);
    assert!(white.would_win(p, 2));
}

#[test]
fn renju_double_three_double_four_and_same_direction_double_four() {
    let p = 7 * 15 + 7;
    let mut three = position(Rule::Renju, &[(6, 7), (8, 7), (7, 6), (7, 8)], &[]);
    assert!(three.forbidden(p));
    assert!(three.legal(p, 2));
    assert!(three.verify_features());
    let mut four = position(
        Rule::Renju,
        &[(5, 7), (6, 7), (8, 7), (7, 5), (7, 6), (7, 8)],
        &[],
    );
    assert!(four.forbidden(p));
    // X_XXX_X: the center stone belongs to two different broken fours.
    let mut same = position(Rule::Renju, &[(4, 7), (6, 7), (8, 7), (10, 7)], &[]);
    assert!(same.forbidden(7 * 15 + 7));
}

#[test]
fn renju_fake_three_and_five_priority() {
    let p = 7 * 15 + 7;
    // Horizontal three is blocked; only the vertical three is real.
    let mut fake = position(
        Rule::Renju,
        &[(6, 7), (8, 7), (7, 6), (7, 8)],
        &[(5, 7), (9, 7)],
    );
    assert!(!fake.forbidden(p));
    // Both ways to extend the horizontal apparent three create an overline
    // on a perpendicular line, so it must not count as a real three.
    let mut stones = vec![(6, 7), (8, 7), (7, 6), (7, 8)];
    for x in [5, 9] {
        for y in [4, 5, 6, 8, 9] {
            stones.push((x, y));
        }
    }
    let mut recursive_fake = position(Rule::Renju, &stones, &[]);
    assert!(!recursive_fake.forbidden(p));
    // Exact five wins even when an overline is created in another direction.
    let mut five = position(
        Rule::Renju,
        &[
            (3, 7),
            (4, 7),
            (5, 7),
            (6, 7),
            (7, 3),
            (7, 4),
            (7, 5),
            (7, 6),
            (7, 8),
        ],
        &[],
    );
    assert!(!five.forbidden(p));
    assert!(five.would_win(p, 1));
}

#[test]
fn search_wins_blocks_and_detects_forced_double_threat() {
    let b = position(
        Rule::Freestyle,
        &[(4, 7), (5, 7), (6, 7), (7, 7)],
        &[(3, 7)],
    );
    let (r, _) = run(b, 1, limits(), Table::new(1024));
    assert_eq!(r.best, Some(7 * 15 + 8));
    assert!(r.score >= MATE - 10);
    let b = position(
        Rule::Freestyle,
        &[(3, 7)],
        &[(4, 7), (5, 7), (6, 7), (7, 7)],
    );
    let (r, _) = run(b, 1, limits(), Table::new(1024));
    assert_eq!(r.best, Some(7 * 15 + 8));
    let b = position(Rule::Freestyle, &[(4, 7), (5, 7), (6, 7)], &[]);
    let (r, _) = run(b, 1, limits(), Table::new(1024));
    assert!(r.score >= MATE - 10);
}

#[test]
fn interrupted_search_never_mutates_authoritative_position() {
    let b = position(Rule::Freestyle, &[(7, 7)], &[(8, 7)]);
    let counts = b.counts.clone();
    let hash = b.hash;
    let mut s = Search::new(b.clone(), 1, limits(), Table::new(128), 0.0);
    s.advance(35, 0.0);
    s.stop();
    assert_eq!(b.counts, counts);
    assert_eq!(b.hash, hash);
    assert!(s.result.best.is_some());
    assert!(s.result.nodes <= limits().nodes);
}

#[test]
fn yxboard_is_silent_and_stop_emits_exactly_one_legal_move() {
    let mut e = Engine::new();
    assert_eq!(e.command("start 15\r\n", 0.0), ["OK"]);
    assert!(e.command("yxboard", 0.0).is_empty());
    e.command("7,7,1", 0.0);
    e.command("8,7,2", 0.0);
    assert!(e.command("done", 0.0).is_empty());
    assert!(!e.busy());
    assert_eq!(e.board.history.len(), 2);
    e.command("INFO max_node 1000000", 0.0);
    e.command("INFO timeout_turn 60000", 0.0);
    e.command("BOARD", 0.0);
    e.command("7,7,1", 0.0);
    e.command("8,7,2", 0.0);
    e.command("DONE", 0.0);
    assert!(e.busy());
    e.tick(31, 0.0);
    let out = e.command("yxstop", 0.0);
    assert_eq!(out.len(), 1);
    assert!(!e.busy());
    assert_eq!(e.board.history.len(), 3);
    assert!(e.board.verify_features());
    assert!(e.command("yxstop", 0.0).is_empty());
}

#[test]
fn malformed_board_is_transactional_and_end_is_silent() {
    let mut e = Engine::new();
    e.command("yxboard", 0.0);
    e.command("7,7,1", 0.0);
    e.command("DONE", 0.0);
    let hash = e.board.hash;
    e.command("BOARD", 0.0);
    e.command("2,2,1", 0.0);
    e.command("2,2,2", 0.0);
    assert!(e.command("DONE", 0.0)[0].starts_with("ERROR"));
    assert_eq!(e.board.hash, hash);
    assert!(e.command("INFO irrelevant 9", 0.0).is_empty());
    assert!(e.command("YXNBEST 3", 0.0)[0].starts_with("UNKNOWN"));
    assert!(e.command("END", 0.0).is_empty());
    assert!(e.command("ABOUT", 0.0).is_empty());
}

#[test]
fn yixin_rule_two_and_forbid_wire_format() {
    let mut e = Engine::new();
    e.command("INFO rule 2", 0.0);
    assert_eq!(e.board.rule, Rule::Renju);
    e.board = position(Rule::Renju, &[(6, 7), (8, 7), (7, 6), (7, 8)], &[]);
    let line = e.command("YXSHOWFORBID", 0.0).remove(0);
    assert!(line.starts_with("FORBID ") && line.ends_with('.'));
    assert!(line.contains("0707"));
    assert!(e.board.verify_features());
}

#[test]
fn node_limit_and_zero_hash_are_exactly_respected() {
    let mut l = limits();
    l.nodes = 25;
    let b = position(Rule::Freestyle, &[(7, 7)], &[(8, 7)]);
    let (r, t) = run(b, 1, l, Table::new(0));
    assert!(r.nodes <= 25);
    assert_eq!(t.bytes(), 0);
    assert!(r.best.is_some());
}

#[test]
fn white_engine_color_is_inferred_from_chronological_board_fields() {
    let mut e = Engine::new();
    e.command("YXBOARD", 0.0);
    e.command("7,7,2", 0.0);
    e.command("DONE", 0.0);
    assert_eq!(e.own, 2);
    assert_eq!(e.board.cells[112], 1);
    assert_eq!(e.command("PLAY 8,7", 0.0), ["8,7"]);
    assert_eq!(e.board.cells[113], 2);
}

#[test]
fn suggestion_stop_never_commits_a_move() {
    let mut e = Engine::new();
    e.command("YXSUGGEST", 0.0);
    e.tick(30, 0.0);
    let out = e.command("YXSTOP", 0.0);
    assert_eq!(out.len(), 1);
    assert!(out[0].starts_with("SUGGEST "));
    assert!(e.board.history.is_empty());
    assert!(e.board.verify_features());
}

#[test]
fn network_loader_rejects_bad_header_checksum_and_nonfinite_parameters() {
    use nolos_nnue::network::{MAGIC, NORMALIZER, SCALE};
    fn fnv(bytes: &[u8]) -> u32 {
        bytes
            .iter()
            .fold(2166136261u32, |h, b| (h ^ *b as u32).wrapping_mul(16777619))
    }
    let mut bytes = Vec::from(*MAGIC);
    bytes.extend_from_slice(&(FEATURES as u32).to_le_bytes());
    bytes.extend_from_slice(&(HIDDEN as u32).to_le_bytes());
    bytes.extend_from_slice(&NORMALIZER.to_le_bytes());
    bytes.extend_from_slice(&SCALE.to_le_bytes());
    let payload = vec![0; (FEATURES * HIDDEN + HIDDEN * 2 + 1) * 4];
    bytes.extend_from_slice(&fnv(&payload).to_le_bytes());
    bytes.extend(payload);
    assert!(Network::load(&bytes).is_ok());
    let mut corrupt = bytes.clone();
    corrupt[30] ^= 1;
    assert!(Network::load(&corrupt).is_err());
    let mut incompatible = bytes.clone();
    incompatible[12] = 64;
    assert!(Network::load(&incompatible).is_err());
    bytes[28..32].copy_from_slice(&f32::NAN.to_le_bytes());
    let checksum = fnv(&bytes[28..]);
    bytes[24..28].copy_from_slice(&checksum.to_le_bytes());
    assert!(Network::load(&bytes).is_err());
}

#[test]
fn yixin_startup_reports_visible_engine_identity_and_limits() {
    let mut e = Engine::new();
    let out = e.command("yxshowinfo", 0.0);
    assert!(out.iter().any(|s| s == "MESSAGE INFO MAX_THREAD_NUM 1"));
    assert!(out.iter().any(|s| s == "MESSAGE INFO MAX_HASH_SIZE 16"));
    assert!(out
        .iter()
        .any(|s| s.starts_with("MESSAGE NolosNNUE ") && s.contains("evaluator: HCE")));
}

#[test]
fn yixin_detail_reports_iterations_and_final_stats_without_extra_moves() {
    let mut e = Engine::new();
    e.command("INFO show_detail 3", 0.0);
    e.command("INFO max_depth 2", 0.0);
    e.command("INFO max_node 100000", 0.0);
    e.command("BEGIN", 0.0);
    let mut out = Vec::new();
    while e.busy() {
        out.extend(e.tick(1, 0.0));
    }
    assert!(out.iter().any(|s| s.starts_with("MESSAGE depth=1 nodes=")
        && s.contains("eval=")
        && s.contains(" PV ")));
    assert!(out.iter().any(|s| s.starts_with("MESSAGE depth=2 nodes=")));
    assert!(out.iter().any(|s| s.starts_with("MESSAGE REALTIME PV ")));
    assert_eq!(
        out.iter()
            .filter(|s| s.starts_with("MESSAGE depth=2 "))
            .count(),
        1
    );
    assert_eq!(out.iter().filter(|s| !s.contains(' ')).count(), 1);
    assert_eq!(e.board.history.len(), 1);
}

#[test]
fn yixin_detail_reports_depth_zero_on_timeout_and_stop_can_be_quiet() {
    let mut e = Engine::new();
    e.command("INFO show_detail 3", 0.0);
    e.command("INFO timeout_turn 0", 0.0);
    e.command("YXSUGGEST", 0.0);
    let out = e.tick(64, 0.0);
    assert!(out
        .iter()
        .any(|s| s.starts_with("MESSAGE depth=0 nodes=0 ")));
    assert!(out.last().unwrap().starts_with("SUGGEST "));
    assert!(e.board.history.is_empty());

    e.command("INFO timeout_turn 60000", 0.0);
    e.command("YXSUGGEST", 0.0);
    e.tick(10, 0.0);
    let out = e.command("YXSTOP", 0.0);
    assert!(out.iter().any(|s| s.starts_with("MESSAGE depth=")));
    assert!(out.last().unwrap().starts_with("SUGGEST "));
    assert!(e.command("YXSTOP", 0.0).is_empty());
    e.command("INFO show_detail 0", 0.0);
    e.command("YXSUGGEST", 0.0);
    assert_eq!(e.command("YXSTOP", 0.0).len(), 1);
}

#[test]
fn spatial_incremental_value_and_policy_match_full_rebuild() {
    use nolos_nnue::spatial::{SpatialNetwork, PARAMETERS};
    let values: Vec<f32> = (0..PARAMETERS)
        .map(|i| ((nolos_nnue::board::mix64(i as u64 + 17) % 10000) as f32 / 10000.0 - 0.5) * 0.3)
        .collect();
    let net = std::sync::Arc::new(Network {
        embedding: vec![],
        bias: [0.0; HIDDEN],
        head: [0.0; HIDDEN],
        tempo: 0.0,
        spatial: Some(SpatialNetwork::from_values(&values)),
    });
    for size in [5, 9, 15, 20] {
        let mut board = Board::new(size, Rule::Freestyle).unwrap();
        board.set_network(Some(net.clone()));
        for turn in 0..120 {
            if turn % 3 == 2 && !board.history.is_empty() {
                board.undo();
            } else if let Some(p) =
                (0..size * size).find(|p| board.cells[(p * 17 + turn) % (size * size)] == 0)
            {
                board.make((p * 17 + turn) % (size * size), (turn % 2 + 1) as u8);
            }
            let mut rebuilt = board.clone();
            rebuilt.rebuild_accumulators();
            for side in [1, 2] {
                assert!((board.evaluate(side) - rebuilt.evaluate(side)).abs() <= 1);
                for p in 0..size * size {
                    assert!(
                        (board.policy_score(p, side).unwrap()
                            - rebuilt.policy_score(p, side).unwrap())
                        .abs()
                            < 0.0001
                    );
                }
            }
        }
        while board.undo().is_some() {}
        if size == 15 {
            for turn in 0..20000 {
                let p = (turn * 17) % (size * size);
                board.make(p, (turn % 2 + 1) as u8);
                board.undo();
            }
        }
        let mut rebuilt = board.clone();
        rebuilt.rebuild_accumulators();
        assert!((board.evaluate(1) - rebuilt.evaluate(1)).abs() <= 1);
    }
}
