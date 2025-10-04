#ifndef SEARCH_H
#define SEARCH_H

#include "chessboard.h"
#include "evaluator.h"
#include <atomic>
#include <chrono>
#include <memory>
#include <unordered_map>

// 置换表条目类型枚举
enum class TTEntryType {
    EXACT,    // 精确值
    LOWER_BOUND, // 下界（alpha被提升）
    UPPER_BOUND  // 上界（beta被剪枝）
};

// 置换表条目结构体
struct TTEntry {
    uint64_t hash;          // 局面的哈希值
    Move best_move;         // 最佳着法
    double value;           // 评估值
    int depth;              // 搜索深度
    TTEntryType type;       // 条目类型
};

// 置换表类
class TranspositionTable {
public:
    TranspositionTable(size_t size_mb = 64); // 默认64MB
    ~TranspositionTable() = default;
    
    // 存储条目
    void store(uint64_t hash, const Move& best_move, double value, int depth, TTEntryType type);
    
    // 查找条目
    TTEntry* probe(uint64_t hash);
    
    // 清空表
    void clear();
    
    // 设置表大小
    void resize(size_t size_mb);
    
private:
    std::vector<TTEntry> table_;
    size_t mask_; // 用于计算索引的掩码
};

// 着法生成器类（扩展功能，例如 zobrist哈希、重复局面检测等）
class MoveGenerator {
public:
    MoveGenerator();
    ~MoveGenerator() = default;
    
    // 生成所有合法着法
    std::vector<Move> generate_legal_moves(const Chessboard& board);
    
    // 生成吃子着法（用于静态评估搜索）
    std::vector<Move> generate_capture_moves(const Chessboard& board);
    
    // 计算着法的历史分数
    double get_move_history_score(const Move& move, int depth) const;
    
private:
    // Zobrist哈希表
    std::array<std::array<uint64_t, 15>, 90> zobrist_table_; // 位置 * 棋子类型
    
    // 初始化Zobrist哈希表
    void initialize_zobrist_table();
    
    // 计算局面的Zobrist哈希值
    uint64_t calculate_hash(const Chessboard& board) const;
};

// 搜索参数结构体
struct SearchParameters {
    int depth;              // 搜索深度
    int time_limit_ms;      // 时间限制（毫秒）
    int nodes_limit;        // 节点限制
    bool use_null_move_pruning; // 是否使用空步裁剪
    bool use_history_heuristic; // 是否使用历史启发式
    bool use_killer_moves;      // 是否使用杀手着法
    bool use_transposition_table; // 是否使用置换表
    int contempt_factor;        // 轻视因子
};

// 搜索结果结构体
struct SearchResult {
    Move best_move;
    double best_score;
    int depth_reached;
    int nodes_searched;
    int time_used_ms;
    std::vector<Move> pv; // 主要变例
};

// 搜索算法类
class Search {
public:
    Search(std::unique_ptr<Evaluator> evaluator);
    ~Search() = default;
    
    // 执行搜索，返回最佳着法和评分
    SearchResult find_best_move(const Chessboard& board, const SearchParameters& params);
    
    // 停止搜索
    void stop();
    
    // 检查是否应该停止搜索
    bool should_stop() const;
    
private:
    std::unique_ptr<Evaluator> evaluator_;
    std::atomic<bool> stop_search_;
    std::chrono::steady_clock::time_point start_time_;
    SearchParameters current_params_;
    
    // 节点计数
    std::atomic<uint64_t> nodes_searched_;
    
    // 历史启发式表
    std::array<std::array<double, 90>, 90> history_table_; // 90个位置（10x9）
    
    // 杀手着法表
    std::array<std::array<Move, 2>, 100> killer_moves_; // 每个深度最多2个杀手着法
    
    // 置换表
    TranspositionTable tt_;
    
    // 着法生成器
    MoveGenerator move_generator_;
    
    // 主搜索函数（带Alpha-Beta剪枝和PV跟踪）
    double alpha_beta(Chessboard& board, int depth, double alpha, double beta, bool is_null_move, std::vector<Move>& pv);
    
    // 迭代加深搜索
    SearchResult iterative_deepening(Chessboard& board, const SearchParameters& params);
    
    // 静态评估函数
    double quiescence_search(Chessboard& board, double alpha, double beta);
    
    // 空步裁剪
    bool null_move_pruning(Chessboard& board, int depth, double alpha, double beta);
    
    // 着法排序
    void order_moves(std::vector<Move>& moves, const Chessboard& board, int depth, TTEntry* tt_entry);
    
    // 更新历史启发式表
    void update_history_table(const Move& move, int depth, bool is_capture);
    
    // 更新杀手着法表
    void update_killer_moves(const Move& move, int depth);
    
    // 检查时间限制是否达到
    bool check_time_limit() const;
    
    // 初始化搜索参数
    void initialize_search(const SearchParameters& params);
    
    // 检查搜索是否完成
    bool is_search_complete(int depth, int nodes_searched) const;
};

#endif // SEARCH_H