#include "ucci.h"
#include <iostream>
#include <memory>

int main(int argc, char* argv[]) {
    try {
        // 创建评估器（默认使用手动评估器）
        auto evaluator = EvaluatorFactory::create_evaluator(EvaluatorFactory::EvaluatorType::MANUAL);
        
        // 创建搜索引擎
        auto search_engine = std::make_unique<Search>(std::move(evaluator));
        
        // 创建UCCI处理器
        UcciHandler ucci_handler(std::move(search_engine));
        
        // 启动UCCI协议处理
        ucci_handler.start();
        
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "Unknown error occurred" << std::endl;
        return 2;
    }
}