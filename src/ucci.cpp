#include "ucci.h"
#include <iostream>
#include <thread>
#include <sstream>
#include <algorithm>
#include <cctype>

UcciHandler::UcciHandler(std::unique_ptr<Search> search_engine) : 
    search_engine_(std::move(search_engine)), 
    is_running_(true), 
    is_searching_(false) {
    initialize_command_handlers();
    initialize_options();
    reset_board();
}

void UcciHandler::start() {
    std::string command;
    
    // 主循环：读取命令并处理
    while (is_running_ && std::getline(std::cin, command)) {
        process_command(command);
    }
}

void UcciHandler::process_command(const std::string& command) {
    // 解析命令
    std::vector<std::string> args = parse_command(command);
    
    if (args.empty()) {
        return;
    }
    
    // 获取命令名称
    std::string cmd_name = args[0];
    std::transform(cmd_name.begin(), cmd_name.end(), cmd_name.begin(), ::tolower);
    
    // 查找命令处理器
    auto it = command_handlers_.find(cmd_name);
    if (it != command_handlers_.end()) {
        // 执行命令处理函数
        it->second(args);
    } else {
        // 未知命令
        std::cerr << "Unknown command: " << cmd_name << std::endl;
    }
}

void UcciHandler::send_response(const std::string& response) const {
    std::cout << response << std::endl;
    std::cout.flush();
}

void UcciHandler::quit() {
    is_running_ = false;
    
    // 如果正在搜索，停止搜索
    if (is_searching_) {
        search_engine_->stop();
    }
    
    // 发送退出确认
    send_response("bye");
}

void UcciHandler::initialize_command_handlers() {
    // 注册命令处理函数
    command_handlers_["ucci"] = std::bind(&UcciHandler::handle_ucci, this, std::placeholders::_1);
    command_handlers_["isready"] = std::bind(&UcciHandler::handle_isready, this, std::placeholders::_1);
    command_handlers_["setoption"] = std::bind(&UcciHandler::handle_setoption, this, std::placeholders::_1);
    command_handlers_["ucinewgame"] = std::bind(&UcciHandler::handle_ucinewgame, this, std::placeholders::_1);
    command_handlers_["position"] = std::bind(&UcciHandler::handle_position, this, std::placeholders::_1);
    command_handlers_["go"] = std::bind(&UcciHandler::handle_go, this, std::placeholders::_1);
    command_handlers_["stop"] = std::bind(&UcciHandler::handle_stop, this, std::placeholders::_1);
    command_handlers_["quit"] = std::bind(&UcciHandler::handle_quit, this, std::placeholders::_1);
    command_handlers_["ponderhit"] = std::bind(&UcciHandler::handle_ponderhit, this, std::placeholders::_1);
}

void UcciHandler::initialize_options() {
    // 设置默认引擎选项
    options_["Skill Level"] = "10";
    options_["MultiPV"] = "1";
    options_["UCI_Chess960"] = "false";
    options_["Threads"] = "1";
    options_["Hash"] = "16";
    options_["Clear Hash"] = "false";
    options_["UCI_LimitStrength"] = "false";
    options_["UCI_Elo"] = "1800";
    options_["Randomness"] = "0";
}

std::vector<std::string> UcciHandler::parse_command(const std::string& command) const {
    std::vector<std::string> args;
    std::istringstream iss(command);
    std::string arg;
    
    while (iss >> arg) {
        args.push_back(arg);
    }
    
    return args;
}

void UcciHandler::handle_ucci(const std::vector<std::string>& args) {
    // 显示引擎信息
    show_engine_info();
    
    // 显示引擎选项
    show_options();
    
    // 发送初始化完成响应
    send_response("ucciok");
}

void UcciHandler::handle_isready(const std::vector<std::string>& args) {
    // 检查引擎是否准备就绪
    if (is_ready()) {
        send_response("readyok");
    }
}

void UcciHandler::handle_setoption(const std::vector<std::string>& args) {
    // 解析setoption命令
    if (args.size() >= 4 && args[1] == "name") {
        std::string option_name = args[2];
        
        // 查找value参数
        size_t value_index = 3;
        while (value_index < args.size() && args[value_index] != "value") {
            option_name += " " + args[value_index];
            value_index++;
        }
        
        // 解析选项值
        std::string option_value = "";
        if (value_index + 1 < args.size()) {
            for (size_t i = value_index + 1; i < args.size(); i++) {
                if (i > value_index + 1) {
                    option_value += " ";
                }
                option_value += args[i];
            }
        }
        
        // 设置选项
        options_[option_name] = option_value;
        
        // 处理特殊选项
        if (option_name == "Clear Hash") {
            // 清除哈希表（如果有）
        }
        else if (option_name == "Threads") {
            // 设置线程数
        }
        else if (option_name == "Hash") {
            // 设置哈希表大小
        }
    }
}

void UcciHandler::handle_ucinewgame(const std::vector<std::string>& args) {
    // 开始新游戏，重置棋盘状态
    reset_board();
    
    // 清除历史记录、哈希表等
}

void UcciHandler::handle_position(const std::vector<std::string>& args) {
    process_position_command(args);
}

void UcciHandler::handle_go(const std::vector<std::string>& args) {
    process_go_command(args);
    
    // 启动异步搜索线程
    if (!is_searching_) {
        is_searching_ = true;
        std::thread search_thread(&UcciHandler::search_thread_func, this);
        search_thread.detach(); // 分离线程，让它在后台运行
    }
}

void UcciHandler::handle_stop(const std::vector<std::string>& args) {
    // 停止搜索
    if (is_searching_) {
        search_engine_->stop();
    }
}

void UcciHandler::handle_quit(const std::vector<std::string>& args) {
    // 退出引擎
    quit();
}

void UcciHandler::handle_ponderhit(const std::vector<std::string>& args) {
    // 处理ponderhit命令（当对手下出引擎预期的着法时）
    // 这里简单实现，实际应用中需要更复杂的处理
    if (is_searching_) {
        search_engine_->stop();
    }
}

void UcciHandler::process_position_command(const std::vector<std::string>& args) {
    if (args.size() < 2) {
        return;
    }
    
    if (args[1] == "startpos") {
        // 设置为初始局面
        current_board_.initialize();
        
        // 检查是否有后续的着法
        size_t moves_index = 2;
        while (moves_index < args.size() && args[moves_index] != "moves") {
            moves_index++;
        }
        
        // 应用后续的着法
        if (moves_index + 1 < args.size()) {
            for (size_t i = moves_index + 1; i < args.size(); i++) {
                Move move = UcciUtils::move_from_ucci(args[i]);
                if (current_board_.is_move_valid(move)) {
                    current_board_.make_move(move);
                }
            }
        }
    } else if (args[1] == "fen") {
        // 从FEN字符串设置局面
        std::string fen;
        size_t moves_index = 2;
        
        // 收集FEN部分
        while (moves_index < args.size() && args[moves_index] != "moves") {
            if (moves_index > 2) {
                fen += " ";
            }
            fen += args[moves_index];
            moves_index++;
        }
        
        // 加载FEN局面
        current_board_.load_from_fen(fen);
        
        // 应用后续的着法
        if (moves_index + 1 < args.size()) {
            for (size_t i = moves_index + 1; i < args.size(); i++) {
                Move move = UcciUtils::move_from_ucci(args[i]);
                if (current_board_.is_move_valid(move)) {
                    current_board_.make_move(move);
                }
            }
        }
    }
}

void UcciHandler::process_go_command(const std::vector<std::string>& args) {
    // 初始化搜索参数
    search_params_.depth = 6; // 默认搜索深度
    search_params_.time_limit_ms = 0; // 默认无时间限制
    search_params_.nodes_limit = 0; // 默认无节点限制
    search_params_.use_null_move_pruning = true;
    search_params_.use_history_heuristic = true;
    search_params_.use_killer_moves = true;
    search_params_.contempt_factor = 0;
    
    // 解析go命令参数
    for (size_t i = 1; i < args.size(); i++) {
        if (args[i] == "depth" && i + 1 < args.size()) {
            search_params_.depth = std::stoi(args[i + 1]);
            i++;
        } else if (args[i] == "movetime" && i + 1 < args.size()) {
            search_params_.time_limit_ms = std::stoi(args[i + 1]);
            i++;
        } else if (args[i] == "nodes" && i + 1 < args.size()) {
            search_params_.nodes_limit = std::stoi(args[i + 1]);
            i++;
        } else if (args[i] == "wtime" && i + 1 < args.size() && current_board_.get_current_player() == Color::RED) {
            // 红方剩余时间
            search_params_.time_limit_ms = std::stoi(args[i + 1]) / 20; // 简单的时间管理
            i++;
        } else if (args[i] == "btime" && i + 1 < args.size() && current_board_.get_current_player() == Color::BLACK) {
            // 黑方剩余时间
            search_params_.time_limit_ms = std::stoi(args[i + 1]) / 20; // 简单的时间管理
            i++;
        }
    }
}

void UcciHandler::search_thread_func() {
    // 执行搜索
    SearchResult result = search_engine_->find_best_move(current_board_, search_params_);
    
    // 发送最佳着法
    if (result.best_move.from_x >= 0) {
        std::string best_move_str = UcciUtils::move_to_ucci(result.best_move);
        send_response("bestmove " + best_move_str);
    } else {
        // 没有找到合法着法
        send_response("nobestmove");
    }
    
    // 搜索完成
    is_searching_ = false;
}

void UcciHandler::show_engine_info() const {
    send_response("id name NolosNNUE");
    send_response("id author Trae AI");
}

void UcciHandler::show_options() const {
    // 显示所有引擎选项
    for (const auto& option : options_) {
        send_response("option name " + option.first + " type string default " + option.second);
    }
}

bool UcciHandler::is_ready() const {
    // 检查引擎是否准备就绪
    // 在这个简单实现中，总是返回true
    return true;
}

void UcciHandler::reset_board() {
    current_board_.initialize();
}

// UcciUtils命名空间实现

std::string UcciUtils::move_to_ucci(const Move& move) {
    // 将着法转换为UCCI格式（例如：e9e8）
    std::ostringstream oss;
    oss << static_cast<char>('a' + move.from_x) << (9 - move.from_y + 1)
        << static_cast<char>('a' + move.to_x) << (9 - move.to_y + 1);
    return oss.str();
}

Move UcciUtils::move_from_ucci(const std::string& ucci_move) {
    // 从UCCI格式字符串解析着法
    Move move;
    
    if (ucci_move.length() >= 4) {
        move.from_x = toupper(ucci_move[0]) - 'A';
        move.from_y = 9 - (ucci_move[1] - '0') + 1;
        move.to_x = toupper(ucci_move[2]) - 'A';
        move.to_y = 9 - (ucci_move[3] - '0') + 1;
    }
    
    return move;
}

bool UcciUtils::is_valid_ucci_command(const std::string& command) {
    // 简单的UCCI命令验证
    std::vector<std::string> valid_commands = {
        "ucci", "isready", "setoption", "ucinewgame", 
        "position", "go", "stop", "quit", "ponderhit"
    };
    
    std::vector<std::string> parts = split_string(command, ' ');
    if (parts.empty()) {
        return false;
    }
    std::string cmd_name = parts[0];
    std::transform(cmd_name.begin(), cmd_name.end(), cmd_name.begin(), ::tolower);
    
    return std::find(valid_commands.begin(), valid_commands.end(), cmd_name) != valid_commands.end();
}

std::string UcciUtils::format_search_info(const SearchResult& result, int depth, double score) {
    std::ostringstream oss;
    oss << "info depth " << depth << " score cp " << static_cast<int>(score * 100)
        << " nodes " << result.nodes_searched << " time " << result.time_used_ms;
    return oss.str();
}

std::string UcciUtils::format_best_move(const Move& best_move, const Move& ponder_move) {
    std::string best_move_str = move_to_ucci(best_move);
    
    if (ponder_move.from_x >= 0) {
        std::string ponder_move_str = move_to_ucci(ponder_move);
        return "bestmove " + best_move_str + " ponder " + ponder_move_str;
    }
    
    return "bestmove " + best_move_str;
}

std::vector<std::string> UcciUtils::split_string(const std::string& str, char delimiter) {
    std::vector<std::string> tokens;
    std::string token;
    std::istringstream token_stream(str);
    
    while (std::getline(token_stream, token, delimiter)) {
        tokens.push_back(token);
    }
    
    return tokens;
}

std::string UcciUtils::trim_string(const std::string& str) {
    size_t first = str.find_first_not_of(" \t");
    if (first == std::string::npos) {
        return "";
    }
    
    size_t last = str.find_last_not_of(" \t");
    return str.substr(first, last - first + 1);
}