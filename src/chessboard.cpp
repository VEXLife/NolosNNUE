#include "chessboard.h"
#include "ucci.h"
#include <iostream>
#include <sstream>
#include <cassert>
#include <random>

// 全局Zobrist哈希表
static uint64_t zobrist_table[90][15]; // 90个位置，15种棋子类型

// 初始化Zobrist哈希表
static void initialize_zobrist_table() {
    static bool initialized = false;
    if (!initialized) {
        std::random_device rd;
        std::mt19937_64 gen(rd());
        std::uniform_int_distribution<uint64_t> dist;
        
        for (int i = 0; i < 90; i++) {
            for (int j = 0; j < 15; j++) {
                zobrist_table[i][j] = dist(gen);
            }
        }
        initialized = true;
    }
}

Chessboard::Chessboard() : current_player_(Color::RED), hash_(0) {
    // 确保Zobrist哈希表被初始化
    initialize_zobrist_table();
    initialize();
}

void Chessboard::initialize() {
    clear();
    
    // 设置初始棋盘布局
    // 红方棋子
    board_[9][0] = PieceType::RED_CHARIOT;
    board_[9][1] = PieceType::RED_HORSE;
    board_[9][2] = PieceType::RED_ELEPHANT;
    board_[9][3] = PieceType::RED_ADVISOR;
    board_[9][4] = PieceType::RED_KING;
    board_[9][5] = PieceType::RED_ADVISOR;
    board_[9][6] = PieceType::RED_ELEPHANT;
    board_[9][7] = PieceType::RED_HORSE;
    board_[9][8] = PieceType::RED_CHARIOT;
    board_[7][1] = PieceType::RED_CANNON;
    board_[7][7] = PieceType::RED_CANNON;
    board_[6][0] = PieceType::RED_PAWN;
    board_[6][2] = PieceType::RED_PAWN;
    board_[6][4] = PieceType::RED_PAWN;
    board_[6][6] = PieceType::RED_PAWN;
    board_[6][8] = PieceType::RED_PAWN;
    
    // 黑方棋子
    board_[0][0] = PieceType::BLACK_CHARIOT;
    board_[0][1] = PieceType::BLACK_HORSE;
    board_[0][2] = PieceType::BLACK_ELEPHANT;
    board_[0][3] = PieceType::BLACK_ADVISOR;
    board_[0][4] = PieceType::BLACK_KING;
    board_[0][5] = PieceType::BLACK_ADVISOR;
    board_[0][6] = PieceType::BLACK_ELEPHANT;
    board_[0][7] = PieceType::BLACK_HORSE;
    board_[0][8] = PieceType::BLACK_CHARIOT;
    board_[2][1] = PieceType::BLACK_CANNON;
    board_[2][7] = PieceType::BLACK_CANNON;
    board_[3][0] = PieceType::BLACK_PAWN;
    board_[3][2] = PieceType::BLACK_PAWN;
    board_[3][4] = PieceType::BLACK_PAWN;
    board_[3][6] = PieceType::BLACK_PAWN;
    board_[3][8] = PieceType::BLACK_PAWN;
    
    // 设置初始行棋方为红方
    current_player_ = Color::RED;
    
    // 更新哈希值
    update_hash();
    
    // 清空历史记录
    history_.clear();
}

bool Chessboard::load_from_fen(const std::string& fen) {
    clear();
    
    std::istringstream iss(fen);
    std::string board_part, turn_part, castle_part, enpassant_part, halfmove_clock_part, fullmove_number_part;
    
    // 解析FEN字符串的各个部分
    if (!(iss >> board_part >> turn_part)) {
        return false;
    }
    
    // 加载棋盘布局
    int y = 9; // 从棋盘底部（红方）开始
    int current_x = 0;
    size_t pos = 0;
    
    while (y >= 0 && pos < board_part.length()) {
        if (board_part[pos] == '/') {
            y--;
            current_x = 0;
            pos++;
        } else if (isdigit(board_part[pos])) {
            // 跳过空格
            int empty_squares = board_part[pos] - '0';
            for (int x = 0; x < empty_squares; x++) {
                board_[y][current_x + x] = PieceType::EMPTY;
            }
            current_x += empty_squares;
            pos++;
        } else {
            // 设置棋子
            char piece_char = board_part[pos];
            PieceType piece = PieceType::EMPTY;
            
            switch (piece_char) {
                case 'K': piece = PieceType::RED_KING; break;
                case 'A': piece = PieceType::RED_ADVISOR; break;
                case 'B': piece = PieceType::RED_ELEPHANT; break;
                case 'N': piece = PieceType::RED_HORSE; break;
                case 'R': piece = PieceType::RED_CHARIOT; break;
                case 'C': piece = PieceType::RED_CANNON; break;
                case 'P': piece = PieceType::RED_PAWN; break;
                case 'k': piece = PieceType::BLACK_KING; break;
                case 'a': piece = PieceType::BLACK_ADVISOR; break;
                case 'b': piece = PieceType::BLACK_ELEPHANT; break;
                case 'n': piece = PieceType::BLACK_HORSE; break;
                case 'r': piece = PieceType::BLACK_CHARIOT; break;
                case 'c': piece = PieceType::BLACK_CANNON; break;
                case 'p': piece = PieceType::BLACK_PAWN; break;
                default: return false;
            }
            
            board_[y][current_x] = piece;
            current_x++;
            pos++;
        }
    }
    
    // 设置当前行棋方
    if (turn_part == "w") {
        current_player_ = Color::RED;
    } else if (turn_part == "b") {
        current_player_ = Color::BLACK;
    } else {
        return false;
    }
    
    // 更新哈希值
    update_hash();
    
    // 清空历史记录
    history_.clear();
    
    return true;
}

std::string Chessboard::to_fen() const {
    std::ostringstream oss;
    
    // 生成棋盘布局部分
    for (int y = 9; y >= 0; y--) {
        int empty_count = 0;
        
        for (int x = 0; x < 9; x++) {
            PieceType piece = board_[y][x];
            
            if (piece == PieceType::EMPTY) {
                empty_count++;
            } else {
                if (empty_count > 0) {
                    oss << empty_count;
                    empty_count = 0;
                }
                
                switch (piece) {
                    case PieceType::RED_KING: oss << 'K'; break;
                    case PieceType::RED_ADVISOR: oss << 'A'; break;
                    case PieceType::RED_ELEPHANT: oss << 'E'; break;
                    case PieceType::RED_HORSE: oss << 'H'; break;
                    case PieceType::RED_CHARIOT: oss << 'R'; break;
                    case PieceType::RED_CANNON: oss << 'C'; break;
                    case PieceType::RED_PAWN: oss << 'P'; break;
                    case PieceType::BLACK_KING: oss << 'k'; break;
                    case PieceType::BLACK_ADVISOR: oss << 'a'; break;
                    case PieceType::BLACK_ELEPHANT: oss << 'e'; break;
                    case PieceType::BLACK_HORSE: oss << 'h'; break;
                    case PieceType::BLACK_CHARIOT: oss << 'r'; break;
                    case PieceType::BLACK_CANNON: oss << 'c'; break;
                    case PieceType::BLACK_PAWN: oss << 'p'; break;
                    default: break;
                }
            }
        }
        
        if (empty_count > 0) {
            oss << empty_count;
        }
        
        if (y > 0) {
            oss << '/';
        }
    }
    
    // 添加当前行棋方
    oss << ' ' << (current_player_ == Color::RED ? 'w' : 'b');
    
    // 添加其他FEN部分（暂时设为默认值）
    oss << " - - 0 1";
    
    return oss.str();
}

PieceType Chessboard::get_piece(int x, int y) const {
    if (is_in_bounds(x, y)) {
        return board_[y][x];
    }
    return PieceType::EMPTY;
}

void Chessboard::set_piece(int x, int y, PieceType piece) {
    if (is_in_bounds(x, y)) {
        board_[y][x] = piece;
    }
}

Color Chessboard::get_current_player() const {
    return current_player_;
}

void Chessboard::set_current_player(Color color) {
    current_player_ = color;
}

bool Chessboard::is_move_valid(const Move& move) const {
    // 检查坐标是否在棋盘范围内
    if (!is_in_bounds(move.from_x, move.from_y) || !is_in_bounds(move.to_x, move.to_y)) {
        return false;
    }
    
    // 检查起点是否有己方棋子
    PieceType from_piece = get_piece(move.from_x, move.from_y);
    if (from_piece == PieceType::EMPTY || get_piece_color(from_piece) != current_player_) {
        return false;
    }
    
    // 检查终点是否有己方棋子
    PieceType to_piece = get_piece(move.to_x, move.to_y);
    if (to_piece != PieceType::EMPTY && get_piece_color(to_piece) == current_player_) {
        return false;
    }
    
    // 根据棋子类型检查移动是否合法
    switch (from_piece) {
        case PieceType::RED_KING:
        case PieceType::BLACK_KING:
            return is_king_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_ADVISOR:
        case PieceType::BLACK_ADVISOR:
            return is_advisor_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_ELEPHANT:
        case PieceType::BLACK_ELEPHANT:
            return is_elephant_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_HORSE:
        case PieceType::BLACK_HORSE:
            return is_horse_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_CHARIOT:
        case PieceType::BLACK_CHARIOT:
            return is_chariot_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_CANNON:
        case PieceType::BLACK_CANNON:
            return is_cannon_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        case PieceType::RED_PAWN:
        case PieceType::BLACK_PAWN:
            return is_pawn_move_valid(move.from_x, move.from_y, move.to_x, move.to_y);
        default:
            return false;
    }
}

inline int get_pos_index(int x, int y) {
    return y * 9 + x;
}

bool Chessboard::make_move(const Move& move) {
    // 保存当前状态到历史记录
    BoardHistory history;
    history.board = board_;
    history.current_player = current_player_;
    history.hash = hash_;
    history.move = move; // 保存着法信息
    history_.push_back(history);
    
    // 执行移动
    PieceType captured_piece = get_piece(move.to_x, move.to_y);
    PieceType moved_piece = get_piece(move.from_x, move.from_y);
    set_piece(move.to_x, move.to_y, moved_piece);
    set_piece(move.from_x, move.from_y, PieceType::EMPTY);
    
    // 切换行棋方
    current_player_ = (current_player_ == Color::RED) ? Color::BLACK : Color::RED;
    
    // 更新哈希值
    auto from_pos_index = get_pos_index(move.from_x, move.from_y);
    auto to_pos_index = get_pos_index(move.to_x, move.to_y);
    hash_ ^= zobrist_table[from_pos_index][static_cast<int>(moved_piece)];
    hash_ ^= zobrist_table[from_pos_index][static_cast<int>(PieceType::EMPTY)];
    hash_ ^= zobrist_table[to_pos_index][static_cast<int>(captured_piece)];
    
    return captured_piece == PieceType::RED_KING || captured_piece == PieceType::BLACK_KING;
}

void Chessboard::undo_move(const Move& move) {
    if (history_.empty()) {
        return;
    }
    
    // 恢复上一个状态
    BoardHistory last_history = history_.back();
    board_ = last_history.board;
    current_player_ = last_history.current_player;
    hash_ = last_history.hash;
    
    // 移除最后一个历史记录
    history_.pop_back();
}

// 辅助方法：检查两个移动是否相同
bool is_move_same(const Move& move1, const Move& move2) {
    return move1.from_x == move2.from_x && 
           move1.from_y == move2.from_y && 
           move1.to_x == move2.to_x && 
           move1.to_y == move2.to_y;
}

std::vector<Move> Chessboard::generate_moves() const {
    std::vector<Move> moves;
    
    // 遍历棋盘上的所有位置
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = get_piece(x, y);
            
            // 如果是当前行棋方的棋子，生成所有合法移动
            if (piece != PieceType::EMPTY && get_piece_color(piece) == current_player_) {
                std::vector<Move> piece_moves = generate_piece_moves(x, y);
                moves.insert(moves.end(), piece_moves.begin(), piece_moves.end());
            }
        }
    }
    
    // 检查是否有重复的历史着法需要避开
    // 用户提供的思路：比较历史着法最近的-4步是否与-8~-5步一样
    // 如果一样说明出现了重复，此时下一步不能走-4步那个着法就能避开循环
    // 只在我方没有被将杀时才需要检查重复着法
    if (!is_in_check(current_player_) && history_.size() >= 8) {
        // 比较最近的-4步和-8~-5步的局面序列是否相同
        bool is_pattern_repeated = true;
        for (int i = 0; i < 4; i++) {
            if (!is_move_same(history_[history_.size() - 4 + i].move, history_[history_.size() - 8 + i].move)) {
                is_pattern_repeated = false;
                break;
            }
        }
        
        if (is_pattern_repeated) {
            // 模式重复，现在可以直接从历史记录中获取-4步的着法
            Move avoid_move = history_[history_.size() - 4].move;
            std::cout << "Avoid duplicate move: " << UcciUtils::move_to_ucci(avoid_move) << std::endl;
            
            // 过滤掉与avoid_move相同的着法
            std::vector<Move> filtered_moves;
            for (const Move& move : moves) {
                // 检查是否与要避开的着法相同
                bool is_same_move = (move.from_x == avoid_move.from_x &&
                                     move.from_y == avoid_move.from_y &&
                                     move.to_x == avoid_move.to_x &&
                                     move.to_y == avoid_move.to_y);
                
                // 如果不是要避开的着法，就保留
                if (!is_same_move) {
                    filtered_moves.push_back(move);
                }
            }
            
            // 如果过滤后还有着法，就返回过滤后的列表
            if (!filtered_moves.empty()) {
                moves = filtered_moves;
            }
        }
    }
    
    return moves;
}

bool Chessboard::is_in_check(Color color) const {
    // 找到将帅的位置
    int king_x = -1, king_y = -1;
    PieceType king_type = (color == Color::RED) ? PieceType::RED_KING : PieceType::BLACK_KING;
    
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            if (get_piece(x, y) == king_type) {
                king_x = x;
                king_y = y;
                break;
            }
        }
    }
    
    if (king_x == -1) {
        return false; // 没有找到将帅，不可能
    }
    
    // 检查对方的所有棋子是否能攻击到将帅
    Color opponent_color = (color == Color::RED) ? Color::BLACK : Color::RED;
    
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = get_piece(x, y);
            
            if (piece != PieceType::EMPTY && get_piece_color(piece) == opponent_color) {
                Move move(x, y, king_x, king_y);
                Chessboard temp_board = *this;
                
                // 临时切换行棋方以便检查移动是否合法
                temp_board.set_current_player(opponent_color);
                
                if (temp_board.is_move_valid(move)) {
                    return true;
                }
            }
        }
    }
    
    return false;
}

Color Chessboard::get_piece_color(PieceType piece) const {
    if (piece == PieceType::EMPTY) {
        return Color::NONE;
    } else if (piece >= PieceType::RED_KING && piece <= PieceType::RED_PAWN) {
        return Color::RED;
    } else {
        return Color::BLACK;
    }
}

std::string Chessboard::get_piece_name(PieceType piece) const {
    switch (piece) {
        case PieceType::EMPTY: return ".";
        case PieceType::RED_KING: return "K";
        case PieceType::RED_ADVISOR: return "A";
        case PieceType::RED_ELEPHANT: return "B";
        case PieceType::RED_HORSE: return "N";
        case PieceType::RED_CHARIOT: return "R";
        case PieceType::RED_CANNON: return "C";
        case PieceType::RED_PAWN: return "P";
        case PieceType::BLACK_KING: return "k";
        case PieceType::BLACK_ADVISOR: return "a";
        case PieceType::BLACK_ELEPHANT: return "b";
        case PieceType::BLACK_HORSE: return "n";
        case PieceType::BLACK_CHARIOT: return "r";
        case PieceType::BLACK_CANNON: return "c";
        case PieceType::BLACK_PAWN: return "p";
        default: return "?";
    }
}

uint64_t Chessboard::get_hash() const {
    return hash_;
}

void Chessboard::clear() {
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            board_[y][x] = PieceType::EMPTY;
        }
    }
}

void Chessboard::print() const {
    std::cout << "  a b c d e f g h i" << std::endl;

    for (int y = 0; y < 10; y++) {
        std::cout << (y) << "|";
        
        for (int x = 0; x < 9; x++) {
            PieceType piece = get_piece(x, y);
            std::cout << get_piece_name(piece) << "|";
        }
        
        std::cout << (y) << std::endl;
    }
    
    std::cout << "  a b c d e f g h i" << std::endl;
    
    std::cout << "Current player: " << (current_player_ == Color::RED ? "Red" : "Black") << std::endl;
}

std::vector<Move> Chessboard::generate_piece_moves(int x, int y) const {
    std::vector<Move> moves;
    PieceType piece = get_piece(x, y);
    
    // 根据棋子类型生成所有可能的移动
    switch (piece) {
        case PieceType::RED_KING:
        case PieceType::BLACK_KING: {
            // 帅/将可以上下左右移动一格，但不能出九宫
            int king_directions[4][2] = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}}; // 左右上下
            Color king_color = get_piece_color(piece);
            
            for (const auto& dir : king_directions) {
                int new_x = x + dir[0];
                int new_y = y + dir[1];
                
                if (is_in_palace(new_x, new_y, king_color) && get_piece_color(get_piece(new_x, new_y)) != king_color) {
                    Move move(x, y, new_x, new_y);
                    moves.push_back(move);
                }
            }
            
            // 检查将帅是否可以直接对面（将帅照面）
            int opponent_king_y = -1;
            PieceType opponent_king_type = (king_color == Color::RED) ? PieceType::BLACK_KING : PieceType::RED_KING;
            
            // 查找对方将帅在同一列上的位置
            bool is_clear_path = true;
            int step = (king_color == Color::RED) ? 1 : -1;
            for (int check_y = y + step; 
                 check_y >= 0 && check_y < 10; 
                 check_y += step) {
                if (get_piece(x, check_y) == opponent_king_type) {
                    opponent_king_y = check_y;
                    break;
                } else if (get_piece(x, check_y) != PieceType::EMPTY) {
                    is_clear_path = false;
                    break;
                }
            }
            
            if (is_clear_path && opponent_king_y != -1) {
                Move move(x, y, x, opponent_king_y);
                moves.push_back(move);
            }
            break;
        }
        case PieceType::RED_ADVISOR:
        case PieceType::BLACK_ADVISOR: {
            // 仕/士可以斜着走一格，但不能出九宫
            int advisor_directions[4][2] = {{-1, -1}, {-1, 1}, {1, -1}, {1, 1}}; // 左上、左下、右上、右下
            Color advisor_color = get_piece_color(piece);
            
            for (const auto& dir : advisor_directions) {
                int new_x = x + dir[0];
                int new_y = y + dir[1];
                
                if (is_in_palace(new_x, new_y, advisor_color) && get_piece_color(get_piece(new_x, new_y)) != advisor_color) {
                    Move move(x, y, new_x, new_y);
                    moves.push_back(move);
                }
            }
            break;
        }
        case PieceType::RED_ELEPHANT:
        case PieceType::BLACK_ELEPHANT: {
            // 相/象可以走"田"字，但不能过河，且"田"字中心不能有棋子
            int elephant_directions[4][2] = {{-2, -2}, {-2, 2}, {2, -2}, {2, 2}}; // 左上、左下、右上、右下
            int elephant_check[4][2] = {{-1, -1}, {-1, 1}, {1, -1}, {1, 1}}; // 检查"田"字中心
            Color elephant_color = get_piece_color(piece);
            
            for (int i = 0; i < 4; i++) {
                int new_x = x + elephant_directions[i][0];
                int new_y = y + elephant_directions[i][1];
                int check_x = x + elephant_check[i][0];
                int check_y = y + elephant_check[i][1];
                
                // 检查是否过河（红方象不能过河，黑方象也不能过河）
                bool is_river_crossed = (elephant_color == Color::RED && new_y >= 5) || 
                                      (elephant_color == Color::BLACK && new_y <= 4);
                
                if (is_in_bounds(new_x, new_y) && !is_river_crossed && 
                    get_piece(check_x, check_y) == PieceType::EMPTY &&
                    get_piece_color(get_piece(new_x, new_y)) != elephant_color) {
                    Move move(x, y, new_x, new_y);
                    moves.push_back(move);
                }
            }
            break;
        }
        case PieceType::RED_HORSE:
        case PieceType::BLACK_HORSE: {
            // 马走"日"字，但马腿不能有棋子
            int horse_directions[8][2] = {{-2, -1}, {-2, 1}, {-1, -2}, {-1, 2}, 
                                         {1, -2}, {1, 2}, {2, -1}, {2, 1}}; // 八个可能的日字位置
            int horse_check[8][2] = {{-1, 0}, {-1, 0}, {0, -1}, {0, 1}, 
                                   {0, -1}, {0, 1}, {1, 0}, {1, 0}}; // 检查马腿
            
            for (int i = 0; i < 8; i++) {
                int new_x = x + horse_directions[i][0];
                int new_y = y + horse_directions[i][1];
                int check_x = x + horse_check[i][0];
                int check_y = y + horse_check[i][1];
                
                if (is_in_bounds(new_x, new_y) && get_piece(check_x, check_y) == PieceType::EMPTY &&
                    get_piece_color(get_piece(new_x, new_y)) != get_piece_color(piece)) {
                    Move move(x, y, new_x, new_y);
                    moves.push_back(move);
                }
            }
            break;
        }
        case PieceType::RED_CHARIOT:
        case PieceType::BLACK_CHARIOT: {
            // 车可以横、竖方向走任意格数，但不能越过棋子
            int chariot_directions[4][2] = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}}; // 左右上下
            
            for (const auto& dir : chariot_directions) {
                int new_x = x + dir[0];
                int new_y = y + dir[1];
                
                while (is_in_bounds(new_x, new_y)) {
                    PieceType target_piece = get_piece(new_x, new_y);
                    
                    if (target_piece == PieceType::EMPTY) {
                        // 空格，合法移动
                        Move move(x, y, new_x, new_y);
                        moves.push_back(move);
                    } else {
                        // 有棋子，检查是否是对方棋子
                        if (get_piece_color(target_piece) != get_piece_color(piece)) {
                            // 对方棋子，可以吃
                            Move move(x, y, new_x, new_y);
                            moves.push_back(move);
                        }
                        // 无论是己方还是对方棋子，都不能继续前进
                        break;
                    }
                    
                    // 继续向同一方向移动
                    new_x += dir[0];
                    new_y += dir[1];
                }
            }
            break;
        }
        case PieceType::RED_CANNON:
        case PieceType::BLACK_CANNON: {
            // 炮的移动方式与车类似，但吃子需要跳过一个棋子
            int cannon_directions[4][2] = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}}; // 左右上下
            
            for (const auto& dir : cannon_directions) {
                int new_x = x + dir[0];
                int new_y = y + dir[1];
                int jump_count = 0;
                
                while (is_in_bounds(new_x, new_y)) {
                    PieceType target_piece = get_piece(new_x, new_y);
                    
                    if (target_piece == PieceType::EMPTY) {
                        // 空格，且还没有跳过棋子，合法移动
                        if (jump_count == 0) {
                            Move move(x, y, new_x, new_y);
                            moves.push_back(move);
                        }
                    } else {
                        if (jump_count == 0) {
                            // 第一次遇到棋子，作为炮架
                            jump_count++;
                        } else if (jump_count == 1) {
                            // 第二次遇到棋子，检查是否是对方棋子
                            if (get_piece_color(target_piece) != get_piece_color(piece)) {
                                // 对方棋子，可以吃
                                Move move(x, y, new_x, new_y);
                                moves.push_back(move);
                            }
                            // 无论如何，不能继续前进
                            break;
                        }
                    }
                    
                    // 继续向同一方向移动
                    new_x += dir[0];
                    new_y += dir[1];
                }
            }
            break;
        }
        case PieceType::RED_PAWN:
        case PieceType::BLACK_PAWN: {
            // 兵/卒未过河时只能前进，过河后可以左右移动
            Color pawn_color = get_piece_color(piece);
            int forward_direction = (pawn_color == Color::RED) ? 1 : -1; // 红兵向上，黑卒向下
            
            // 前进一格
            int new_x = x;
            int new_y = y + forward_direction;
            if (is_in_bounds(new_x, new_y) && get_piece_color(get_piece(new_x, new_y)) != pawn_color) {
                Move move(x, y, new_x, new_y);
                moves.push_back(move);
            }
            
            // 检查是否过河
            bool is_crossed_river = (pawn_color == Color::RED && y >= 5) || 
                                   (pawn_color == Color::BLACK && y <= 4);
            
            if (is_crossed_river) {
                // 过河后可以左右移动
                int left_x = x - 1;
                int right_x = x + 1;
                int current_y = y;
                
                if (is_in_bounds(left_x, current_y) && get_piece_color(get_piece(left_x, current_y)) != pawn_color) {
                    Move move(x, y, left_x, current_y);
                    moves.push_back(move);
                }
                
                if (is_in_bounds(right_x, current_y) && get_piece_color(get_piece(right_x, current_y)) != pawn_color) {
                    Move move(x, y, right_x, current_y);
                    moves.push_back(move);
                }
            }
            break;
        }
        default:
            break;
    }
    
    return moves;
}

bool Chessboard::is_in_bounds(int x, int y) const {
    return x >= 0 && x < 9 && y >= 0 && y < 10;
}

bool Chessboard::is_in_palace(int x, int y, Color color) const {
    if (!is_in_bounds(x, y)) {
        return false;
    }
    
    if (color == Color::BLACK) {
        return x >= 3 && x <= 5 && y >= 7 && y <= 9;
    } else {
        return x >= 3 && x <= 5 && y >= 0 && y <= 2;
    }
}

void Chessboard::update_hash() {
    // 使用Zobrist哈希计算棋盘哈希值
    hash_ = 0;
    
    // 计算棋盘上每个位置的哈希值
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = get_piece(x, y);
            int position_index = get_pos_index(x, y);
            int piece_index = static_cast<int>(piece);
            
            if (piece != PieceType::EMPTY) {
                hash_ ^= zobrist_table[position_index][piece_index];
            }
        }
    }
    
    // 添加当前行棋方的哈希值
    if (current_player_ == Color::RED) {
        hash_ ^= zobrist_table[89][14]; // 使用最后一个位置和最后一个棋子类型作为行棋方的哈希值
    }
}

bool Chessboard::is_king_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否在九宫格内
    PieceType king = get_piece(from_x, from_y);
    Color king_color = get_piece_color(king);
    
    if (!is_in_palace(to_x, to_y, king_color)) {
        // 检查是否是将帅照面
        if (from_x == to_x) {
            // 同一列
            bool is_clear_path = true;
            int step = (from_y < to_y) ? 1 : -1;
            
            for (int y = from_y + step; y != to_y; y += step) {
                if (get_piece(from_x, y) != PieceType::EMPTY) {
                    is_clear_path = false;
                    break;
                }
            }
            
            if (is_clear_path) {
                // 检查目标位置是否是对方将帅
                PieceType target_piece = get_piece(to_x, to_y);
                PieceType opponent_king = (king_color == Color::RED) ? PieceType::BLACK_KING : PieceType::RED_KING;
                
                return target_piece == opponent_king;
            }
        }
        
        return false;
    }
    
    // 检查是否移动一格
    int dx = abs(to_x - from_x);
    int dy = abs(to_y - from_y);
    
    return (dx == 1 && dy == 0) || (dx == 0 && dy == 1);
}

bool Chessboard::is_advisor_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否在九宫格内
    PieceType advisor = get_piece(from_x, from_y);
    Color advisor_color = get_piece_color(advisor);
    
    if (!is_in_palace(to_x, to_y, advisor_color)) {
        return false;
    }
    
    // 检查是否斜着移动一格
    int dx = abs(to_x - from_x);
    int dy = abs(to_y - from_y);
    
    return dx == 1 && dy == 1;
}

bool Chessboard::is_elephant_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否过河
    PieceType elephant = get_piece(from_x, from_y);
    Color elephant_color = get_piece_color(elephant);
    
    bool is_river_crossed = (elephant_color == Color::RED && to_y >= 5) || 
                          (elephant_color == Color::BLACK && to_y <= 4);
    
    if (is_river_crossed) {
        return false;
    }
    
    // 检查是否走田字
    int dx = abs(to_x - from_x);
    int dy = abs(to_y - from_y);
    
    if (dx != 2 || dy != 2) {
        return false;
    }
    
    // 检查田字中心是否有棋子
    int center_x = (from_x + to_x) / 2;
    int center_y = (from_y + to_y) / 2;
    
    return get_piece(center_x, center_y) == PieceType::EMPTY;
}

bool Chessboard::is_horse_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否走日字
    int dx = abs(to_x - from_x);
    int dy = abs(to_y - from_y);
    
    if (!((dx == 1 && dy == 2) || (dx == 2 && dy == 1))) {
        return false;
    }
    
    // 检查马腿是否有棋子
    int leg_x = from_x;
    int leg_y = from_y;
    
    if (dx == 2) {
        // 横向移动两格，检查纵向马腿
        leg_x = from_x + (to_x > from_x ? 1 : -1);
    } else {
        // 纵向移动两格，检查横向马腿
        leg_y = from_y + (to_y > from_y ? 1 : -1);
    }
    
    return get_piece(leg_x, leg_y) == PieceType::EMPTY;
}

bool Chessboard::is_chariot_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否是直线移动
    if (from_x != to_x && from_y != to_y) {
        return false;
    }
    
    // 检查路径上是否有棋子阻挡
    int step_x = (from_x == to_x) ? 0 : (to_x > from_x ? 1 : -1);
    int step_y = (from_y == to_y) ? 0 : (to_y > from_y ? 1 : -1);
    
    int x = from_x + step_x;
    int y = from_y + step_y;
    
    while (x != to_x || y != to_y) {
        if (get_piece(x, y) != PieceType::EMPTY) {
            return false;
        }
        
        x += step_x;
        y += step_y;
    }
    
    return true;
}

bool Chessboard::is_cannon_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查是否是直线移动
    if (from_x != to_x && from_y != to_y) {
        return false;
    }
    
    // 计算路径上的棋子数量
    int step_x = (from_x == to_x) ? 0 : (to_x > from_x ? 1 : -1);
    int step_y = (from_y == to_y) ? 0 : (to_y > from_y ? 1 : -1);
    
    int x = from_x + step_x;
    int y = from_y + step_y;
    int piece_count = 0;
    
    while (x != to_x || y != to_y) {
        if (get_piece(x, y) != PieceType::EMPTY) {
            piece_count++;
        }
        
        x += step_x;
        y += step_y;
    }
    
    // 炮移动时路径上不能有棋子，吃子时路径上必须有且只有一个棋子
    PieceType target_piece = get_piece(to_x, to_y);
    
    if (target_piece == PieceType::EMPTY) {
        // 移动，路径上不能有棋子
        return piece_count == 0;
    } else {
        // 吃子，路径上必须有且只有一个棋子
        return piece_count == 1;
    }
}

bool Chessboard::is_pawn_move_valid(int from_x, int from_y, int to_x, int to_y) const {
    // 检查兵卒的移动方向
    PieceType pawn = get_piece(from_x, from_y);
    Color pawn_color = get_piece_color(pawn);
    
    int forward_direction = (pawn_color == Color::RED) ? 1 : -1; // 红兵向上，黑卒向下
    
    // 检查是否过河
    bool is_crossed_river = (pawn_color == Color::RED && from_y >= 5) || 
                           (pawn_color == Color::BLACK && from_y <= 4);
    
    // 计算移动距离
    int dx = abs(to_x - from_x);
    int dy = to_y - from_y;
    
    // 未过河时只能前进
    if (!is_crossed_river) {
        return dx == 0 && dy == forward_direction;
    } else {
        // 过河后可以前进或左右移动，但只能移动一格
        return ((dx == 0 && dy == forward_direction) || 
                (dy == 0 && abs(dx) == 1));
    }
}