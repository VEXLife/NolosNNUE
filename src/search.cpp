#include "search.h"
#include <iostream>
#include <algorithm>
#include <random>
#include <chrono>
#include <cstring>
#include "ucci.h"

// TranspositionTable 类实现
TranspositionTable::TranspositionTable(size_t size_mb) {
    resize(size_mb);
}

void TranspositionTable::resize(size_t size_mb) {
    // 计算表的大小（条目数）
    size_t entry_size = sizeof(TTEntry);
    size_t entries_count = (size_mb * 1024 * 1024) / entry_size;
    
    // 确保表大小是2的幂次
    size_t power_of_two = 1;
    while (power_of_two < entries_count) {
        power_of_two <<= 1;
    }
    
    table_.resize(power_of_two);
    mask_ = power_of_two - 1;
    clear();
}

void TranspositionTable::clear() {
    memset(table_.data(), 0, table_.size() * sizeof(TTEntry));
}

void TranspositionTable::store(uint64_t hash, const Move& best_move, double value, int depth, TTEntryType type) {
    size_t index = hash & mask_;
    
    TTEntry& entry = table_[index];
    entry.hash = hash;
    entry.best_move = best_move;
    entry.value = value;
    entry.depth = depth;
    entry.type = type;
}

TTEntry* TranspositionTable::probe(uint64_t hash) {
    size_t index = hash & mask_;
    TTEntry& entry = table_[index];
    
    if (entry.hash == hash && entry.depth > 0) {
        return &entry;
    }
    
    return nullptr;
}

Search::Search(std::unique_ptr<Evaluator> evaluator) : 
    evaluator_(std::move(evaluator)), 
    stop_search_(false),
    nodes_searched_(0),
    tt_(64) {
    // 初始化历史启发式表
    for (int i = 0; i < 90; i++) {
        for (int j = 0; j < 90; j++) {
            history_table_[i][j] = 0.0;
        }
    }
    
    // 初始化杀手着法表
    for (int i = 0; i < 100; i++) {
        killer_moves_[i][0] = Move();
        killer_moves_[i][1] = Move();
    }
}

SearchResult Search::find_best_move(const Chessboard& board, const SearchParameters& params) {
    initialize_search(params);
    
    Chessboard working_board = board;
    return iterative_deepening(working_board, params);
}

void Search::stop() {
    stop_search_ = true;
}

bool Search::should_stop() const {
    return stop_search_ || check_time_limit();
}

double Search::alpha_beta(Chessboard& board, int depth, double alpha, double beta, bool is_null_move, std::vector<Move>& pv) {
    // 增加节点计数
    nodes_searched_++;
    
    // 检查是否应该停止搜索
    if (should_stop()) {
        pv.clear();
        return 0.0;
    }
    
    // 置换表查找
    TTEntry* tt_entry = nullptr;
    uint64_t hash = board.get_hash();
    
    if (current_params_.use_transposition_table) {
        tt_entry = tt_.probe(hash);
        if (tt_entry && tt_entry->depth >= depth) {
            // 命中置换表
            if (tt_entry->type == TTEntryType::EXACT) {
                pv.clear();
                if (tt_entry->best_move.from_x != -1) {
                    pv.push_back(tt_entry->best_move);
                }
                return tt_entry->value;
            } else if (tt_entry->type == TTEntryType::LOWER_BOUND) {
                alpha = std::max(alpha, tt_entry->value);
            } else if (tt_entry->type == TTEntryType::UPPER_BOUND) {
                beta = std::min(beta, tt_entry->value);
            }
            
            if (alpha >= beta) {
                pv.clear();
                if (tt_entry->best_move.from_x != -1) {
                    pv.push_back(tt_entry->best_move);
                }
                return tt_entry->value;
            }
        }
    }
    
    // 到达搜索深度，进行静态评估搜索
    if (depth == 0) {
        pv.clear();
        return quiescence_search(board, alpha, beta);
    }
    
    // 生成所有合法移动
    std::vector<Move> moves = board.generate_moves();

    // 如果没有合法移动，检查是否被将死或困毙
    if (moves.empty()) {
        pv.clear();
        double score = 0.0;
        if (board.is_in_check(board.get_current_player())) {
            // 被将死，返回极小值
            score = -10000.0 - depth;
        }
        
        // 存储到置换表
        if (current_params_.use_transposition_table) {
            tt_.store(hash, Move(), score, depth, TTEntryType::EXACT);
        }
        
        return score;
    }
    
    // 使用空步裁剪
    if (current_params_.use_null_move_pruning && !is_null_move && depth >= 3 && 
        board.get_current_player() == Color::RED && alpha < 10000.0) {
        if (null_move_pruning(board, depth, alpha, beta)) {
            // 存储到置换表（上界）
            if (current_params_.use_transposition_table) {
                tt_.store(hash, Move(), beta, depth, TTEntryType::UPPER_BOUND);
            }
            pv.clear();
            return beta;
        }
    }
    
    // 着法排序（考虑置换表中的最佳着法）
    order_moves(moves, board, depth, tt_entry);
    
    double best_score = -100000.0;
    std::vector<Move> best_pv;
    Move best_move;
    
    for (const Move& move : moves) {
        // 执行移动
        bool checkmate = board.make_move(move);
        if (checkmate) {
            board.undo_move(move);

            best_score = 10000.0;
            // 存储到置换表（精确值）
            if (current_params_.use_transposition_table) {
                tt_.store(hash, move, best_score, depth, TTEntryType::EXACT);
            }
            pv.push_back(move);
            return best_score;
        }
        
        // 递归搜索，跟踪PV
        std::vector<Move> child_pv;
        double score = -alpha_beta(board, depth - 1, -beta, -alpha, true, child_pv);
        
        // 撤销移动
        board.undo_move(move);
        
        // 更新最佳分数和PV
        if (score > best_score) {
            best_score = score;
            best_move = move;
            best_pv.clear();
            best_pv.push_back(move);
            best_pv.insert(best_pv.end(), child_pv.begin(), child_pv.end());
        }
        
        // Alpha-Beta剪枝
        if (score > alpha) {
            alpha = score;
            pv = best_pv; // 更新PV
        }
        
        if (alpha >= beta) {
            // 剪枝，更新历史启发式表或杀手着法表
            if (!move.is_capture) {
                update_killer_moves(move, depth);
            } else {
                update_history_table(move, depth, true);
            }
            
            // 存储到置换表（上界）
            if (current_params_.use_transposition_table) {
                tt_.store(hash, best_move, beta, depth, TTEntryType::UPPER_BOUND);
            }
            
            break;
        }
    }
    
    // 存储到置换表
    if (current_params_.use_transposition_table) {
        TTEntryType type;
        if (best_score <= alpha) {
            type = TTEntryType::UPPER_BOUND;
        } else if (best_score >= beta) {
            type = TTEntryType::LOWER_BOUND;
        } else {
            type = TTEntryType::EXACT;
        }
        tt_.store(hash, best_move, best_score, depth, type);
    }
    
    return best_score;
}

SearchResult Search::iterative_deepening(Chessboard& board, const SearchParameters& params) {
    SearchResult result;
    result.best_move = Move();
    result.best_score = 0.0;
    result.depth_reached = 0;
    result.nodes_searched = 0;
    result.pv.clear();
    
    // 迭代加深搜索
    for (int depth = 1; depth <= params.depth; depth++) {
        if (should_stop()) {
            break;
        }
        
        // 记录开始时间
        auto depth_start_time = std::chrono::steady_clock::now();
        
        // 执行Alpha-Beta搜索，跟踪PV
        std::vector<Move> current_pv; // 使用临时变量存储当前深度的PV
        double score = alpha_beta(board, depth, -100000.0, 100000.0, false, current_pv);
        
        // 记录结束时间
        auto depth_end_time = std::chrono::steady_clock::now();
        auto depth_duration = std::chrono::duration_cast<std::chrono::milliseconds>(depth_end_time - depth_start_time);
        
        // 计算NPS（每秒节点数）
        int time_used = static_cast<int>(depth_duration.count());
        int nps = (time_used > 0) ? (nodes_searched_ * 1000 / time_used) : 0;
        
        // 构建PV字符串
        std::string pv_str;
        for (const Move& move : current_pv) {
            pv_str += UcciUtils::move_to_ucci(move) + " ";
        }
        if (!pv_str.empty()) {
            pv_str.pop_back(); // 删除最后一个空格
        }
        
        // 打印搜索信息（新格式）
        std::cout << "info depth " << depth 
                  << " score " << static_cast<int>(board.get_current_player() == Color::RED ? score : -score)
                  << " nps " << nps 
                  << " time " << time_used;
        if (!pv_str.empty()) {
            std::cout << " pv " << pv_str;
        }
        std::cout << std::endl;
        
        // 更新结果的条件：
        // 1. 当前深度搜索完成，没有被中断
        // 2. 或者这是第一层搜索，即使被中断也要使用当前结果
        if (!should_stop() || depth == 1) {
            // 更新结果
            result.best_score = score;
            result.depth_reached = depth;
            result.nodes_searched = nodes_searched_;
            result.pv = current_pv;
            if (!current_pv.empty()) {
                result.best_move = current_pv[0];
            }
        }
        
        // 检查时间限制
        if (check_time_limit()) {
            break;
        }
        
        // 检查节点限制
        if (params.nodes_limit > 0 && nodes_searched_ >= params.nodes_limit) {
            break;
        }
    }
    
    return result;
}

double Search::quiescence_search(Chessboard& board, double alpha, double beta) {
    // 增加节点计数
    nodes_searched_++;
    
    // 检查是否应该停止搜索
    if (should_stop()) {
        return 0.0;
    }
    
    // 置换表查找
    TTEntry* tt_entry = nullptr;
    uint64_t hash = board.get_hash();
    
    if (current_params_.use_transposition_table) {
        tt_entry = tt_.probe(hash);
        if (tt_entry) {
            if (tt_entry->type == TTEntryType::EXACT) {
                return tt_entry->value;
            } else if (tt_entry->type == TTEntryType::LOWER_BOUND) {
                alpha = std::max(alpha, tt_entry->value);
            } else if (tt_entry->type == TTEntryType::UPPER_BOUND) {
                beta = std::min(beta, tt_entry->value);
            }
            
            if (alpha >= beta) {
                return tt_entry->value;
            }
        }
    }
    
    // 进行静态评估
    double stand_pat = evaluator_->evaluate(board);
    
    // 处理置换表存储（如果启用）
    if (current_params_.use_transposition_table) {
        TTEntryType type = TTEntryType::EXACT;
        tt_.store(hash, Move(), stand_pat, 0, type);
    }
    
    // 直接返回静态评估值，不进行吃子搜索
    return stand_pat;
}

bool Search::null_move_pruning(Chessboard& board, int depth, double alpha, double beta) {
    // 确保有足够的深度进行空步裁剪
    if (depth < 3) {
        return false;
    }
    
    // 保存当前行棋方
    Color original_player = board.get_current_player();
    
    // 空步（切换行棋方，但不移动任何棋子）
    board.set_current_player(original_player == Color::RED ? Color::BLACK : Color::RED);
    
    // 进行深度为depth-3的搜索，使用单一回复窗口
    std::vector<Move> dummy_pv;
    double score = -alpha_beta(board, depth - 3, -beta, -beta + 1.0, true, dummy_pv);
    
    // 恢复原始行棋方
    board.set_current_player(original_player);
    
    // 如果搜索结果仍然超过beta，则可以剪枝
    return score >= beta;
}

void Search::order_moves(std::vector<Move>& moves, const Chessboard& board, int depth, TTEntry* tt_entry) {
    // 为每个着法计算优先级分数
    std::vector<std::pair<double, Move>> scored_moves;
    
    // 检查置换表中的最佳着法是否在当前着法列表中
    Move tt_best_move;
    bool has_tt_move = false;
    
    if (tt_entry && tt_entry->best_move.from_x != -1) {
        tt_best_move = tt_entry->best_move;
        has_tt_move = true;
    }
    
    for (const Move& move : moves) {
        double score = 0.0;
        
        // 检查是否是置换表中的最佳着法
        if (has_tt_move && 
            move.from_x == tt_best_move.from_x && 
            move.from_y == tt_best_move.from_y && 
            move.to_x == tt_best_move.to_x && 
            move.to_y == tt_best_move.to_y) {
            score += 2000.0; // 最高优先级
        }
        
        // 检查是否是吃子着法，使用MVV-LVA（Most Valuable Victim - Least Valuable Aggressor）原则
        if (move.is_capture) {
            // 简单的吃子价值评估（可以改进为完整的MVV-LVA）
            PieceType captured = board.get_piece(move.to_x, move.to_y);
            PieceType attacker = board.get_piece(move.from_x, move.from_y);
            
            // 根据棋子价值设置吃子优先级
            double attacker_value = 0.0;
            double captured_value = 0.0;
            
            switch (attacker) {
                case PieceType::RED_CHARIOT: case PieceType::BLACK_CHARIOT: attacker_value = 9.0; break;
                case PieceType::RED_HORSE: case PieceType::BLACK_HORSE: attacker_value = 4.5; break;
                case PieceType::RED_CANNON: case PieceType::BLACK_CANNON: attacker_value = 4.5; break;
                case PieceType::RED_ELEPHANT: case PieceType::BLACK_ELEPHANT: attacker_value = 2.0; break;
                case PieceType::RED_ADVISOR: case PieceType::BLACK_ADVISOR: attacker_value = 2.0; break;
                case PieceType::RED_PAWN: case PieceType::BLACK_PAWN: attacker_value = 1.0; break;
                default: attacker_value = 0.0; break;
            }
            
            switch (captured) {
                case PieceType::RED_CHARIOT: case PieceType::BLACK_CHARIOT: captured_value = 9.0; break;
                case PieceType::RED_HORSE: case PieceType::BLACK_HORSE: captured_value = 4.5; break;
                case PieceType::RED_CANNON: case PieceType::BLACK_CANNON: captured_value = 4.5; break;
                case PieceType::RED_ELEPHANT: case PieceType::BLACK_ELEPHANT: captured_value = 2.0; break;
                case PieceType::RED_ADVISOR: case PieceType::BLACK_ADVISOR: captured_value = 2.0; break;
                case PieceType::RED_PAWN: case PieceType::BLACK_PAWN: captured_value = 1.0; break;
                default: captured_value = 0.0; break;
            }
            
            // MVV-LVA: 高价值目标被低价值攻击者吃掉的着法优先级更高
            score += 1000.0 + (captured_value * 10.0 - attacker_value);
        }
        
        // 检查是否是杀手着法
        if (current_params_.use_killer_moves && depth < 100) {
            if (move.from_x == killer_moves_[depth][0].from_x && 
                move.from_y == killer_moves_[depth][0].from_y && 
                move.to_x == killer_moves_[depth][0].to_x && 
                move.to_y == killer_moves_[depth][0].to_y) {
                score += 500.0;
            } else if (move.from_x == killer_moves_[depth][1].from_x && 
                    move.from_y == killer_moves_[depth][1].from_y && 
                    move.to_x == killer_moves_[depth][1].to_x && 
                    move.to_y == killer_moves_[depth][1].to_y) {
                score += 400.0;
            }
        }
        
        // 检查历史启发式表
        if (current_params_.use_history_heuristic) {
            int from_index = move.from_y * 9 + move.from_x;
            int to_index = move.to_y * 9 + move.to_x;
            if (from_index < 90 && to_index < 90) {
                score += history_table_[from_index][to_index];
            }
        }
        
        scored_moves.emplace_back(score, move);
    }
    
    // 按照分数排序着法（降序）
    std::sort(scored_moves.begin(), scored_moves.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    
    // 将排序后的着法放回原始向量
    moves.clear();
    for (const auto& scored_move : scored_moves) {
        moves.push_back(scored_move.second);
    }
}

void Search::update_history_table(const Move& move, int depth, bool is_capture) {
    if (!current_params_.use_history_heuristic || is_capture) {
        return;
    }
    
    int from_index = move.from_y * 9 + move.from_x;
    int to_index = move.to_y * 9 + move.to_x;
    
    if (from_index < 90 && to_index < 90) {
        // 根据深度增加历史分数（深度越大，权重越高）
        history_table_[from_index][to_index] += (depth * depth);
    }
}

void Search::update_killer_moves(const Move& move, int depth) {
    if (!current_params_.use_killer_moves || depth >= 100) {
        return;
    }
    
    // 如果这个着法不是第一个杀手着法，将它提升为第一个杀手着法
    if (!(move.from_x == killer_moves_[depth][0].from_x && 
        move.from_y == killer_moves_[depth][0].from_y && 
        move.to_x == killer_moves_[depth][0].to_x && 
        move.to_y == killer_moves_[depth][0].to_y)) {
        
        // 将第二个杀手着法移到第二个位置
        killer_moves_[depth][1] = killer_moves_[depth][0];
        
        // 设置新的第一个杀手着法
        killer_moves_[depth][0] = move;
    }
}

bool Search::check_time_limit() const {
    if (current_params_.time_limit_ms <= 0) {
        return false;
    }
    
    auto current_time = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(current_time - start_time_);
    
    return elapsed.count() >= current_params_.time_limit_ms;
}

void Search::initialize_search(const SearchParameters& params) {
    stop_search_ = false;
    start_time_ = std::chrono::steady_clock::now();
    current_params_ = params;
    nodes_searched_ = 0;
    
    // 重置置换表
    if (params.use_transposition_table) {
        tt_.clear();
    }
    
    // 重置历史启发式表
    if (params.use_history_heuristic) {
        for (int i = 0; i < 90; i++) {
            for (int j = 0; j < 90; j++) {
                history_table_[i][j] = 0.0;
            }
        }
    }
    
    // 重置杀手着法表
    if (params.use_killer_moves) {
        for (int i = 0; i < 100; i++) {
            killer_moves_[i][0] = Move();
            killer_moves_[i][1] = Move();
        }
    }
}

bool Search::is_search_complete(int depth, int nodes_searched) const {
    return should_stop() || 
           (current_params_.depth > 0 && depth >= current_params_.depth) || 
           (current_params_.nodes_limit > 0 && nodes_searched >= current_params_.nodes_limit);
}

MoveGenerator::MoveGenerator() {
    initialize_zobrist_table();
}

std::vector<Move> MoveGenerator::generate_legal_moves(const Chessboard& board) {
    return board.generate_moves();
}

std::vector<Move> MoveGenerator::generate_capture_moves(const Chessboard& board) {
    std::vector<Move> capture_moves;
    
    // 遍历棋盘上所有可能的吃子位置
    for (int from_y = 0; from_y < 10; from_y++) {
        for (int from_x = 0; from_x < 9; from_x++) {
            // 检查起点是否有当前行棋方的棋子
            PieceType from_piece = board.get_piece(from_x, from_y);
            if (from_piece == PieceType::EMPTY || board.get_piece_color(from_piece) != board.get_current_player()) {
                continue;
            }
            
            // 检查所有可能的目标位置
            for (int to_y = 0; to_y < 10; to_y++) {
                for (int to_x = 0; to_x < 9; to_x++) {
                    // 如果目标位置为空，跳过（不是吃子）
                    PieceType to_piece = board.get_piece(to_x, to_y);
                    if (to_piece == PieceType::EMPTY) {
                        continue;
                    }
                    
                    // 如果目标位置是己方棋子，跳过
                    if (board.get_piece_color(to_piece) == board.get_current_player()) {
                        continue;
                    }
                    
                    // 检查移动是否合法
                    Move move(from_x, from_y, to_x, to_y);
                    if (board.is_move_valid(move)) {
                        move.is_capture = true;
                        move.captured_piece = to_piece;
                        capture_moves.push_back(move);
                    }
                }
            }
        }
    }
    
    return capture_moves;
}

double MoveGenerator::get_move_history_score(const Move& move, int depth) const {
    // 这个函数在MoveGenerator中是一个占位符，实际的历史分数计算在Search类中实现
    return 0.0;
}

void MoveGenerator::initialize_zobrist_table() {
    // 初始化Zobrist哈希表
    std::random_device rd;
    std::mt19937_64 gen(rd());
    std::uniform_int_distribution<uint64_t> dist;
    
    for (int i = 0; i < 90; i++) {
        for (int j = 0; j < 15; j++) {
            zobrist_table_[i][j] = dist(gen);
        }
    }
}

uint64_t MoveGenerator::calculate_hash(const Chessboard& board) const {
    uint64_t hash = 0;
    
    // 计算棋盘上每个位置的哈希值
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = board.get_piece(x, y);
            int position_index = y * 9 + x;
            int piece_index = static_cast<int>(piece);
            
            if (piece != PieceType::EMPTY) {
                hash ^= zobrist_table_[position_index][piece_index];
            }
        }
    }
    
    // 添加当前行棋方的哈希值
    if (board.get_current_player() == Color::RED) {
        hash ^= zobrist_table_[89][14]; // 使用最后一个位置和最后一个棋子类型作为行棋方的哈希值
    }
    
    return hash;
}