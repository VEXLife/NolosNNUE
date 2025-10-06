#ifndef CHESSBOARD_H
#define CHESSBOARD_H

#include <string>
#include <vector>
#include <array>
#include <memory>

// 棋子类型定义
enum class PieceType {
    EMPTY = 0,
    RED_KING = 1,
    RED_ADVISOR = 2,
    RED_ELEPHANT = 3,
    RED_HORSE = 4,
    RED_CHARIOT = 5,
    RED_CANNON = 6,
    RED_PAWN = 7,
    BLACK_KING = 8,
    BLACK_ADVISOR = 9,
    BLACK_ELEPHANT = 10,
    BLACK_HORSE = 11,
    BLACK_CHARIOT = 12,
    BLACK_CANNON = 13,
    BLACK_PAWN = 14
};

// 颜色定义
enum class Color {
    NONE = 0,
    RED = 1,
    BLACK = 2
};

// 移动定义
struct Move {
    int from_x, from_y;
    int to_x, to_y;
    PieceType captured_piece;
    bool is_capture;
    bool is_check;
    bool is_checkmate;

    Move() : from_x(-1), from_y(-1), to_x(-1), to_y(-1),
             captured_piece(PieceType::EMPTY), is_capture(false),
             is_check(false), is_checkmate(false) {}
    
    Move(int fx, int fy, int tx, int ty) : from_x(fx), from_y(fy), to_x(tx), to_y(ty),
                                         captured_piece(PieceType::EMPTY), is_capture(false),
                                         is_check(false), is_checkmate(false) {}
};

// 棋盘类
class Chessboard {
public:
    Chessboard();
    ~Chessboard() = default;
    
    // 初始化棋盘到初始状态
    void initialize();
    
    // 从FEN字符串加载棋盘状态
    bool load_from_fen(const std::string& fen);
    
    // 生成当前局面的FEN字符串
    std::string to_fen() const;
    
    // 获取指定位置的棋子类型
    PieceType get_piece(int x, int y) const;
    
    // 设置指定位置的棋子类型
    void set_piece(int x, int y, PieceType piece);
    
    // 获取当前轮到哪方行棋
    Color get_current_player() const;
    
    // 设置当前轮到哪方行棋
    void set_current_player(Color color);
    
    // 检查移动是否合法
    bool is_move_valid(const Move& move) const;
    
    // 执行移动
    bool make_move(const Move& move);
    
    // 撤销移动
    void undo_move(const Move& move);
    
    // 生成所有合法移动
    std::vector<Move> generate_moves() const;
    
    // 检查当前局面是否将军
    bool is_in_check(Color color) const;
    
    // 检查当前局面是否将死
    bool is_checkmate(Color color) const;
    
    // 检查当前局面是否和棋
    bool is_stalemate(Color color) const;
    
    // 获取棋子颜色
    Color get_piece_color(PieceType piece) const;
    
    // 获取棋子中文名称
    std::string get_piece_name(PieceType piece) const;
    
    // 获取棋盘哈希值（用于重复局面检测）
    uint64_t get_hash() const;
    
    // 清空棋盘
    void clear();
    
    // 打印棋盘（调试用）
    void print() const;

private:
    // 10x9的棋盘，中国象棋标准棋盘大小
    std::array<std::array<PieceType, 9>, 10> board_;
    
    // 当前行棋方
    Color current_player_;
    
    // 记录棋盘历史，用于撤销移动
    struct BoardHistory {
        std::array<std::array<PieceType, 9>, 10> board;
        Color current_player;
        uint64_t hash;
        Move move; // 保存到达此状态的着法
    };
    
    // 历史记录栈
    std::vector<BoardHistory> history_;
    
    // 棋盘哈希值
    uint64_t hash_;
    
    // 生成特定棋子的所有合法移动
    std::vector<Move> generate_piece_moves(int x, int y) const;
    
    // 检查位置是否在棋盘范围内
    bool is_in_bounds(int x, int y) const;
    
    // 检查位置是否在九宫格范围内（将帅、士的活动范围）
    bool is_in_palace(int x, int y, Color color) const;
    
    // 更新棋盘哈希值
    void update_hash();
    
    // 棋子移动规则检查函数
    bool is_king_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_advisor_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_elephant_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_horse_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_chariot_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_cannon_move_valid(int from_x, int from_y, int to_x, int to_y) const;
    bool is_pawn_move_valid(int from_x, int from_y, int to_x, int to_y) const;
};

#endif // CHESSBOARD_H