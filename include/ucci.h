#ifndef UCCI_H
#define UCCI_H

#include "chessboard.h"
#include "search.h"
#include <string>
#include <vector>
#include <map>
#include <functional>

// UCCI协议处理器类
class UcciHandler {
public:
    UcciHandler(std::unique_ptr<Search> search_engine);
    ~UcciHandler() = default;
    
    // 启动UCCI协议处理
    void start();
    
    // 处理UCCI命令
    void process_command(const std::string& command);
    
    // 向界面发送响应
    void send_response(const std::string& response) const;
    
    // 退出引擎
    void quit();
    
private:
    std::unique_ptr<Search> search_engine_;
    Chessboard current_board_;
    SearchParameters search_params_;
    bool is_running_;
    bool is_searching_;
    
    // 引擎选项
    std::map<std::string, std::string> options_;
    
    // 命令处理函数映射
    std::map<std::string, std::function<void(const std::vector<std::string>&)>> command_handlers_;
    
    // 初始化命令处理器
    void initialize_command_handlers();
    
    // 初始化引擎选项
    void initialize_options();
    
    // 解析命令行参数
    std::vector<std::string> parse_command(const std::string& command) const;
    
    // UCCI命令处理函数
    void handle_ucci(const std::vector<std::string>& args);
    void handle_isready(const std::vector<std::string>& args);
    void handle_setoption(const std::vector<std::string>& args);
    void handle_ucinewgame(const std::vector<std::string>& args);
    void handle_position(const std::vector<std::string>& args);
    void handle_go(const std::vector<std::string>& args);
    void handle_stop(const std::vector<std::string>& args);
    void handle_quit(const std::vector<std::string>& args);
    void handle_ponderhit(const std::vector<std::string>& args);
    
    // 处理位置命令（FEN字符串或走子序列）
    void process_position_command(const std::vector<std::string>& args);
    
    // 处理走棋命令（设置搜索参数）
    void process_go_command(const std::vector<std::string>& args);
    
    // 异步搜索线程函数
    void search_thread_func();
    
    // 显示引擎信息
    void show_engine_info() const;
    
    // 显示引擎选项
    void show_options() const;
    
    // 检查引擎是否准备就绪
    bool is_ready() const;
    
    // 重置棋盘状态
    void reset_board();
};

// UCCI协议助手函数
namespace UcciUtils {
    // 将着法转换为UCCI格式字符串
    std::string move_to_ucci(const Move& move);
    
    // 从UCCI格式字符串解析着法
    Move move_from_ucci(const std::string& ucci_move);
    
    // 验证UCCI命令格式
    bool is_valid_ucci_command(const std::string& command);
    
    // 格式化搜索信息响应
    std::string format_search_info(const SearchResult& result, int depth, double score);
    
    // 格式化最佳着法响应
    std::string format_best_move(const Move& best_move, const Move& ponder_move = Move());
    
    // 分割字符串
    std::vector<std::string> split_string(const std::string& str, char delimiter);
    
    // 去除字符串首尾空格
    std::string trim_string(const std::string& str);
}

#endif // UCCI_H