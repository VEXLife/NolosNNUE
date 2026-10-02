use nolos_nnue::board::{Board, Rule};
use nolos_nnue::network::{Network, FEATURES, HIDDEN};
use nolos_nnue::protocol::Engine;
use nolos_nnue::search::{run, Limits, Search, Table, MATE};
use std::sync::Arc;

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
