#ifndef SEARCH_H
#define SEARCH_H

#include "chessboard.h"
#include "evaluator.h"
#include <atomic>
#include <chrono>
#include <memory>

// 搜索参数结构体
struct SearchParameters {
    int depth;              // 搜索深度
    int time_limit_ms;      // 时间限制（毫秒）
    int nodes_limit;        // 节点限制
    bool use_null_move_pruning; // 是否使用空步裁剪
    bool use_history_heuristic; // 是否使用历史启发式
    bool use_killer_moves;      // 是否使用杀手着法
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
    std::atomic<int> nodes_searched_;
    
    // 历史启发式表
    std::array<std::array<double, 90>, 90> history_table_; // 90个位置（10x9）
    
    // 杀手着法表
    std::array<std::array<Move, 2>, 100> killer_moves_; // 每个深度最多2个杀手着法
    
    // 主搜索函数（带Alpha-Beta剪枝和PV跟踪）
    double alpha_beta(Chessboard& board, int depth, double alpha, double beta, bool is_null_move, std::vector<Move>& pv);
    
    // 迭代加深搜索
    SearchResult iterative_deepening(Chessboard& board, const SearchParameters& params);
    
    // 静态评估函数
    double quiescence_search(Chessboard& board, double alpha, double beta);
    
    // 空步裁剪
    bool null_move_pruning(Chessboard& board, int depth, double alpha, double beta);
    
    // 着法排序
    void order_moves(std::vector<Move>& moves, const Chessboard& board, int depth);
    
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

// 着法生成器类（扩展功能，例如 zobrist哈希、重复局面检测等）
class MoveGenerator {
public:
    MoveGenerator();
    ~MoveGenerator() = default;
    
    // 生成所有合法着法
    std::vector<Move> generate_legal_moves(const Chessboard& board);
    
    // 生成吃子着法（用于静态评估搜索）
    std::vector<Move> generate_capture_moves(const Chessboard& board);
    
    // 检查着法是否合法
    bool is_move_legal(const Chessboard& board, const Move& move);
    
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

#endif // SEARCH_H