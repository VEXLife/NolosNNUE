use crate::board::{Board, Rule};
use crate::network::Network;
use crate::search::{Limits, ResultInfo, Search, Table, MATE};
use std::sync::Arc;

struct BoardInput {
    think: bool,
    rows: Vec<(usize, usize, u8)>,
    error: Option<String>,
}

pub struct Engine {
    pub board: Board,
    pub own: u8,
    pub search: Option<Search>,
    pub limits: Limits,
    pub ended: bool,
    network: Option<Arc<Network>>,
    table: Option<Table>,
    input: Option<BoardInput>,
    hash_kb: usize,
    time_left: Option<f64>,
    increment: f64,
    pending_error: Option<String>,
    commit_search: bool,
    show_detail: bool,
    selective_search: bool,
    int16_precision: bool,
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

impl Engine {
    pub fn new() -> Self {
        Self {
            board: Board::new(15, Rule::Freestyle).unwrap(),
            own: 1,
            search: None,
            limits: Limits::default(),
            ended: false,
            network: None,
            table: Some(Table::new(4096)),
            input: None,
            hash_kb: 4096,
            time_left: None,
            increment: 0.0,
            pending_error: None,
            commit_search: true,
            show_detail: false,
            selective_search: false,
            int16_precision: false,
        }
    }

    pub fn load_network(&mut self, bytes: &[u8]) -> Result<(), String> {
        if self.search.is_some() || self.input.is_some() {
            return Err("finish or stop the current operation before loading weights".into());
        }
        let net = Network::load(bytes)?;
        let net = if self.int16_precision {
            net.with_precision("int16")?
        } else {
            net
        };
        self.network = Some(net.clone());
        self.board.set_network(Some(net));
        self.table.as_mut().unwrap().clear();
        Ok(())
    }

    pub fn set_precision(&mut self, precision: &str) -> Result<(), String> {
        if self.search.is_some() || self.input.is_some() {
            return Err("finish or stop the current operation before changing precision".into());
        }
        let enabled = match precision {
            "fp32" => false,
            "int16" => true,
            _ => return Err("precision must be fp32 or int16".into()),
        };
        if enabled == self.int16_precision {
            return Ok(());
        }
        if let Some(net) = &self.network {
            let net = net.with_precision(precision)?;
            self.network = Some(net.clone());
            self.board.set_network(Some(net));
        }
        self.int16_precision = enabled;
        self.clear_hash();
        Ok(())
    }

    pub fn unload_network(&mut self) -> Result<(), String> {
        if self.search.is_some() || self.input.is_some() {
            return Err("finish or stop the current operation before changing evaluator".into());
        }
        self.network = None;
        self.board.set_network(None);
        self.table.as_mut().unwrap().clear();
        Ok(())
    }

    pub fn busy(&self) -> bool {
        self.search.is_some()
    }

    fn cancel(&mut self) {
        if let Some(job) = self.search.take() {
            self.table = Some(job.table);
        }
    }

    fn clear_hash(&mut self) {
        if let Some(job) = &mut self.search {
            job.table.clear();
        } else if let Some(table) = &mut self.table {
            table.clear();
        }
    }

    fn error(s: impl AsRef<str>) -> Vec<String> {
        vec![format!("ERROR {}", s.as_ref())]
    }

    fn coord(&self, text: &str) -> Result<usize, String> {
        let parts: Vec<&str> = text.split(',').collect();
        if parts.len() != 2 {
            return Err("expected X,Y".into());
        }
        let x = parts[0].trim().parse::<usize>().map_err(|_| "invalid X")?;
        let y = parts[1].trim().parse::<usize>().map_err(|_| "invalid Y")?;
        if x >= self.board.size || y >= self.board.size {
            return Err("coordinate outside board".into());
        }
        Ok(y * self.board.size + x)
    }

    pub fn command(&mut self, line: &str, now: f64) -> Vec<String> {
        if self.ended {
            return Vec::new();
        }
        let line = line.trim();
        if line.len() > 8192 {
            return Self::error("command exceeds 8192 bytes");
        }
        if line.is_empty() {
            return Vec::new();
        }
        let (cmd, arg) = line.split_once(char::is_whitespace).unwrap_or((line, ""));
        let cmd = cmd.to_ascii_uppercase();
        let arg = arg.trim();
        // Control commands are accepted even inside a malformed BOARD transaction.
        if cmd == "END" {
            self.cancel();
            self.input = None;
            self.ended = true;
            return Vec::new();
        }
        if cmd == "YXSTOP" {
            self.input = None;
            if let Some(job) = &mut self.search {
                job.stop();
                return self.finish();
            }
            return Vec::new();
        }
        if let Some(input) = &mut self.input {
            if cmd == "DONE" {
                return self.finish_input(now);
            }
            if input.rows.len() >= self.board.size * self.board.size {
                input.error = Some("too many BOARD rows".into());
                return Vec::new();
            }
            let fields: Vec<&str> = line.split(',').collect();
            let row = if fields.len() == 3 {
                match (
                    fields[0].trim().parse::<usize>(),
                    fields[1].trim().parse::<usize>(),
                    fields[2].trim().parse::<u8>(),
                ) {
                    (Ok(x), Ok(y), Ok(c))
                        if x < self.board.size && y < self.board.size && (c == 1 || c == 2) =>
                    {
                        Some((x, y, c))
                    }
                    _ => None,
                }
            } else {
                None
            };
            if let Some(row) = row {
                input.rows.push(row);
            } else {
                input.error = Some("invalid BOARD row; expected X,Y,1 or X,Y,2".into());
            }
            return Vec::new();
        }
        match cmd.as_str() {
            "ABOUT" => vec![
                "name=\"NolosNNUE\", version=\"0.1.0\", author=\"NolosNNUE contributors\"".into(),
            ],
            "START" => match arg
                .parse::<usize>()
                .ok()
                .and_then(|n| Board::new(n, self.board.rule).ok())
            {
                Some(mut board) => {
                    self.cancel();
                    board.set_network(self.network.clone());
                    self.board = board;
                    self.own = 1;
                    self.clear_hash();
                    vec!["OK".into()]
                }
                None => Self::error("supported square board sizes: 5..20"),
            },
            "RESTART" => {
                self.cancel();
                self.board = Board::new(self.board.size, self.board.rule).unwrap();
                self.board.set_network(self.network.clone());
                self.own = 1;
                self.clear_hash();
                vec!["OK".into()]
            }
            "RECTSTART" => {
                let parts: Vec<_> = arg.split(',').collect();
                if parts.len() == 2 && parts[0].trim() == parts[1].trim() {
                    self.command(&format!("START {}", parts[0].trim()), now)
                } else {
                    Self::error("rectangular boards are not supported")
                }
            }
            "INFO" => {
                let (key, value) = arg.split_once(char::is_whitespace).unwrap_or((arg, ""));
                if key.eq_ignore_ascii_case("nnue_precision") {
                    return match self.set_precision(&value.trim().to_ascii_lowercase()) {
                        Ok(()) => Vec::new(),
                        Err(e) => Self::error(e),
                    };
                }
                self.info(arg);
                Vec::new()
            }
            "BOARD" | "YXBOARD" => {
                self.cancel();
                self.input = Some(BoardInput {
                    think: cmd == "BOARD",
                    rows: Vec::new(),
                    error: None,
                });
                Vec::new()
            }
            "BEGIN" => {
                if !self.board.history.is_empty() {
                    return Self::error("BEGIN requires an empty board");
                }
                self.own = 1;
                self.start(now)
            }
            "TURN" => {
                if self.busy() {
                    return Self::error("engine is already thinking");
                }
                match self.coord(arg) {
                    Ok(p) => {
                        if self.board.history.is_empty() {
                            self.own = 2;
                        }
                        let opponent = 3 - self.own;
                        if !self.board.legal(p, opponent) {
                            return Self::error("occupied or forbidden opponent move");
                        }
                        self.board.make(p, opponent);
                        self.start(now)
                    }
                    Err(e) => Self::error(e),
                }
            }
            "TAKEBACK" => {
                self.cancel();
                match self.coord(arg).and_then(|p| self.board.remove(p)) {
                    Ok(()) => {
                        self.clear_hash();
                        vec!["OK".into()]
                    }
                    Err(e) => Self::error(e),
                }
            }
            "PLAY" => {
                if self.busy() {
                    return Self::error("engine is already thinking");
                }
                if self.board.winner().is_some() {
                    return Self::error("game already has a winner");
                }
                match self.coord(arg) {
                    Ok(p) if self.board.legal(p, self.own) => {
                        self.board.make(p, self.own);
                        vec![format!("{},{}", p % self.board.size, p / self.board.size)]
                    }
                    _ => Self::error("invalid PLAY coordinate"),
                }
            }
            "YXHASHCLEAR" => {
                self.clear_hash();
                Vec::new()
            }
            "YXSHOWFORBID" => {
                if self.board.rule != Rule::Renju {
                    return Self::error("YXSHOWFORBID requires INFO rule 2");
                }
                let mut s = String::from("FORBID ");
                for p in 0..self.board.cells.len() {
                    if self.board.forbidden(p) {
                        s.push_str(&format!(
                            "{:02}{:02}",
                            p % self.board.size,
                            p / self.board.size
                        ));
                    }
                }
                s.push('.');
                vec![s]
            }
            "YXSHOWINFO" => vec![
                "MESSAGE INFO MAX_THREAD_NUM 1".into(),
                "MESSAGE INFO MAX_HASH_SIZE 16".into(),
                format!(
                    "MESSAGE NolosNNUE {} | evaluator: {} | search: alpha-beta | threads: 1 | max hash: 64 MB",
                    env!("CARGO_PKG_VERSION"),
                    if self.network.is_none() { "HCE" } else if self.int16_precision { "NNUE int16" } else { "NNUE" }
                ),
            ],
            "YXSHOWHASHUSAGE" => {
                let bytes = self
                    .search
                    .as_ref()
                    .map(|s| s.table.bytes())
                    .unwrap_or_else(|| self.table.as_ref().unwrap().bytes());
                vec![format!("MESSAGE hash {} KB", bytes / 1024)]
            }
            "YXLOADNNUE" => {
                #[cfg(not(target_arch = "wasm32"))]
                {
                    match std::fs::read(arg)
                        .map_err(|e| e.to_string())
                        .and_then(|b| self.load_network(&b))
                    {
                        Ok(()) => vec!["OK".into()],
                        Err(e) => Self::error(e),
                    }
                }
                #[cfg(target_arch = "wasm32")]
                {
                    Self::error("browser host must upload network bytes")
                }
            }
            "YXUNLOADNNUE" => match self.unload_network() {
                Ok(()) => vec!["OK".into()],
                Err(e) => Self::error(e),
            },
            "YXPOLICY" => {
                let scores: Option<Vec<String>> = (0..self.board.cells.len())
                    .map(|p| self.board.policy_score(p, self.own).map(|v| format!("{v:.7}")))
                    .collect();
                match scores {
                    Some(scores) => vec![format!("MESSAGE POLICY {}", scores.join(" "))],
                    None => Self::error("loaded network has no policy head"),
                }
            }
            "YXEVAL" => vec![format!("MESSAGE EVAL {}", self.board.evaluate(self.own))],
            "YXGO" => self.start(now),
            "YXSUGGEST" => {
                if self.busy() {
                    return Self::error("engine is already thinking");
                }
                self.commit_search = false;
                self.start_with_mode(now, false)
            }
            "YXSTATUS" => {
                let cells: String = self
                    .board
                    .cells
                    .iter()
                    .map(|c| (b'0' + *c) as char)
                    .collect();
                let history = self
                    .board
                    .history
                    .iter()
                    .map(|(p, c)| format!("[{p},{c}]"))
                    .collect::<Vec<_>>()
                    .join(",");
                vec![format!("MESSAGE STATUS {{\"size\":{},\"rule\":{},\"next\":{},\"winner\":{},\"board\":\"{cells}\",\"history\":[{history}]}}",
                    self.board.size, self.board.rule.id(), self.board.history.len() % 2 + 1, self.board.winner().unwrap_or(0))]
            }
            _ => vec![format!("UNKNOWN {cmd}")],
        }
    }

    fn finish_input(&mut self, now: f64) -> Vec<String> {
        let input = self.input.take().unwrap();
        if let Some(error) = input.error {
            return Self::error(error);
        }
        let chronological = input.rows.windows(2).all(|w| w[0].2 != w[1].2);
        if self.board.rule == Rule::Renju && !chronological {
            return Self::error("Renju BOARD rows must follow move order");
        }
        let own = if chronological {
            input
                .rows
                .first()
                .map(|r| if r.2 == 1 { 1 } else { 2 })
                .unwrap_or(1)
        } else {
            let ones = input.rows.iter().filter(|r| r.2 == 1).count();
            let twos = input.rows.len() - ones;
            if ones == twos {
                1
            } else {
                2
            }
        };
        let mut board = Board::new(self.board.size, self.board.rule).unwrap();
        board.set_network(self.network.clone());
        for (x, y, field) in input.rows {
            let p = y * board.size + x;
            if board.cells[p] != 0 {
                return Self::error("duplicate BOARD coordinate");
            }
            board.make(p, if field == 1 { own } else { 3 - own });
        }
        self.board = board;
        self.own = own;
        if input.think {
            self.start(now)
        } else {
            Vec::new()
        }
    }

    fn info(&mut self, arg: &str) {
        let (key, value) = arg.split_once(char::is_whitespace).unwrap_or((arg, ""));
        let number = value.trim().parse::<i64>();
        match key.to_ascii_lowercase().as_str() {
            "show_detail" => {
                if let Ok(n) = number {
                    self.show_detail = n > 0;
                }
            }
            "rule" => {
                if let Ok(n) = number {
                    match i32::try_from(n)
                        .map_err(|_| "invalid rule identifier".to_string())
                        .and_then(Rule::from_id)
                    {
                        Ok(rule) => {
                            self.cancel();
                            self.board.rule = rule;
                            self.clear_hash();
                            self.pending_error = None;
                        }
                        Err(e) => self.pending_error = Some(e),
                    }
                }
            }
            "timeout_turn" => {
                if let Ok(n) = number {
                    if n >= 0 {
                        self.limits.time_ms = n as f64;
                    }
                }
            }
            "time_left" => {
                if let Ok(n) = number {
                    self.time_left = if n >= i32::MAX as i64 {
                        None
                    } else {
                        Some(n.max(0) as f64)
                    };
                }
            }
            "time_increment" => {
                if let Ok(n) = number {
                    self.increment = n.max(0) as f64;
                }
            }
            "max_depth" => {
                if let Ok(n) = number {
                    self.limits.depth = if n <= 0 { 400 } else { n.min(400) as usize };
                }
            }
            "max_node" => {
                if let Ok(n) = number {
                    self.limits.nodes = if n <= 0 { u64::MAX } else { n as u64 };
                }
            }
            "selective_search" => {
                if self.search.is_none() {
                    if let Ok(n @ (0 | 1)) = number {
                        self.selective_search = n == 1;
                        self.clear_hash();
                    }
                }
            }
            "hash_size" => {
                if let Ok(n) = number {
                    self.resize_hash(n.max(0) as usize);
                }
            }
            "max_memory" => {
                if let Ok(n) = number {
                    if n > 0 {
                        self.resize_hash((n as usize / 1024 / 2).min(self.hash_kb));
                    }
                }
            }
            // Single search thread is within any positive thread_num limit.
            // Pondering is optional; no background search is performed.
            _ => {}
        }
        if let Some(search) = &mut self.search {
            search.limits.depth = self.limits.depth;
            search.limits.nodes = self.limits.nodes;
            search.limits.time_ms = self.limits.time_ms;
        }
    }

    fn resize_hash(&mut self, kb: usize) {
        // GUI values are KB (not MB). Zero disables the useful table.
        self.hash_kb = kb.min(65536);
        let table = Table::new(self.hash_kb);
        if let Some(search) = &mut self.search {
            search.table = table;
        } else {
            self.table = Some(table);
        }
    }

    fn start(&mut self, now: f64) -> Vec<String> {
        self.start_with_mode(now, true)
    }

    fn start_with_mode(&mut self, now: f64, commit: bool) -> Vec<String> {
        if self.busy() {
            return Self::error("engine is already thinking");
        }
        if let Some(e) = self.pending_error.clone() {
            return Self::error(e);
        }
        if self.board.winner().is_some() {
            return Self::error("game already has a winner");
        }
        self.commit_search = commit;
        let mut limits = self.limits.clone();
        if let Some(left) = self.time_left {
            limits.time_ms = limits
                .time_ms
                .min((left / 25.0 + self.increment * 0.8).min(left * 0.9));
        }
        // Leave a small margin for pipe transport and GUI time accounting.
        limits.time_ms = (limits.time_ms * 0.95).max(0.0);
        self.search = Some(Search::new(
            self.board.clone(),
            self.own,
            limits,
            self.table.take().unwrap(),
            now,
        ));
        self.search.as_mut().unwrap().selective_search = self.selective_search;
        if self.search.as_ref().unwrap().done {
            self.finish()
        } else {
            Vec::new()
        }
    }

    pub fn tick(&mut self, batch: usize, now: f64) -> Vec<String> {
        let update = match self.search.as_mut() {
            Some(s) => s.advance(batch, now),
            None => return Vec::new(),
        };
        if self.show_detail && self.search.as_ref().unwrap().done {
            return self.finish();
        }
        let mut out = update
            .as_ref()
            .map(|info| self.analysis(info))
            .unwrap_or_default();
        if self.search.as_ref().unwrap().done {
            out.extend(self.finish());
        }
        out
    }

    fn analysis(&self, info: &ResultInfo) -> Vec<String> {
        let n = self.board.size;
        let pv = info
            .pv
            .iter()
            .map(|p| format!("{},{}", p % n, p / n))
            .collect::<Vec<_>>()
            .join(" ");
        let eval = if info.score.abs() >= MATE - 500 {
            format!(
                "{}M{}",
                if info.score > 0 { "+" } else { "-" },
                MATE - info.score.abs()
            )
        } else {
            info.score.to_string()
        };
        let mut out = vec![
            "INFO NUMPV 1".into(),
            "INFO PV 0".into(),
            format!("INFO DEPTH {}", info.depth),
            format!("INFO NODES {}", info.nodes),
            format!("INFO EVAL {eval}"),
            format!(
                "INFO WINRATE {:.6}",
                1.0 / (1.0 + (-(info.score as f64) / 600.0).exp())
            ),
            format!("INFO BESTLINE {pv}"),
            "INFO PV DONE".into(),
        ];
        if info.vcf_depth > 0 {
            out.push(format!(
                "MESSAGE VCF proof {} plies PV {pv}",
                info.vcf_depth
            ));
        }
        if self.show_detail {
            if let Some(p) = info.best {
                out.push(format!("MESSAGE REALTIME BEST {},{}", p % n, p / n));
            }
            out.push(format!("MESSAGE REALTIME VAL {}", info.score));
            out.push(format!("MESSAGE REALTIME PV {pv}"));
            out.push(format!(
                "MESSAGE depth={} nodes={} eval={eval} winrate={:.1}% PV {pv}",
                info.depth,
                info.nodes,
                100.0 / (1.0 + (-(info.score as f64) / 600.0).exp())
            ));
        }
        out
    }

    fn finish(&mut self) -> Vec<String> {
        let search = self.search.take().unwrap();
        // A time/node limit or YXSTOP may end between completed iterations.
        // Include the final node count and fallback PV even at depth zero.
        let mut out = if self.show_detail {
            self.analysis(&search.result)
        } else {
            Vec::new()
        };
        let info = search.result;
        self.table = Some(search.table);
        if let Some(p) = info.best {
            // search.board may be mid-variation on YXSTOP; only commit to the
            // authoritative protocol board, never to the search copy.
            if !self.board.legal(p, self.own) {
                return Self::error("no legal best move");
            }
            if self.commit_search {
                self.board.make(p, self.own);
                out.push(format!("{},{}", p % self.board.size, p / self.board.size));
            } else {
                out.push(format!(
                    "SUGGEST {},{}",
                    p % self.board.size,
                    p / self.board.size
                ));
            }
            out
        } else {
            Self::error("no legal moves")
        }
    }
}
