#ifndef EVALUATOR_H
#define EVALUATOR_H

#include "chessboard.h"
#include <memory>

#ifdef USE_ONNX
#include <onnxruntime_cxx_api.h>
#endif

// 评估器基类
class Evaluator {
public:
    virtual ~Evaluator() = default;
    
    // 评估当前棋盘局面，返回评估分数
    // 正数表示红方有利，负数表示黑方有利
    virtual double evaluate(const Chessboard& board) = 0;
};

// 手动评估器类
class ManualEvaluator : public Evaluator {
public:
    ManualEvaluator();
    ~ManualEvaluator() override = default;
    
    double evaluate(const Chessboard& board) override;
    
private:
    // 棋子价值表
    std::array<double, 15> piece_values_;
    
    // 三维位置价值表：[棋子类型][y坐标][x坐标]
    // 使用静态常量定义棋子类型数量和棋盘大小
    static constexpr int NUM_PIECE_TYPES = 15;
    static constexpr int BOARD_HEIGHT = 10;
    static constexpr int BOARD_WIDTH = 9;
    
    // 红方和黑方的位置价值表，按棋子类型区分
    std::array<std::array<std::array<double, BOARD_WIDTH>, BOARD_HEIGHT>, NUM_PIECE_TYPES> red_piece_position_values_;
    std::array<std::array<std::array<double, BOARD_WIDTH>, BOARD_HEIGHT>, NUM_PIECE_TYPES> black_piece_position_values_;
    
    // 初始化棋子价值
    void initialize_piece_values();
    
    // 初始化位置价值表
    void initialize_position_values();
    
    // 评估棋子价值
    double evaluate_material(const Chessboard& board) const;
    
    // 评估位置价值
    double evaluate_position(const Chessboard& board) const;
    
    // 评估机动性
    double evaluate_mobility(const Chessboard& board) const;
    
    // 评估威胁
    double evaluate_threats(const Chessboard& board) const;
};

#ifdef USE_ONNX
// NNUE评估器类
class NnueEvaluator : public Evaluator {
public:
    NnueEvaluator(const std::string& model_path = "model.onnx");
    ~NnueEvaluator() override;
    
    double evaluate(const Chessboard& board) override;
    
    // 检查模型是否成功加载
    bool is_model_loaded() const;
    
private:
    // ONNX Runtime环境
    Ort::Env env_;
    Ort::Session* session_;
    Ort::AllocatorWithDefaultOptions allocator_;
    
    // 模型输入输出名称
    std::vector<const char*> input_names_;
    std::vector<const char*> output_names_;
    
    // 输入张量形状
    std::vector<int64_t> input_shape_;
    
    // 棋盘转换为神经网络输入
    std::vector<float> board_to_input(const Chessboard& board) const;
    
    // 初始化ONNX Runtime
    void initialize_onnx_runtime(const std::string& model_path);
    
    // 释放资源
    void release_resources();
};
#endif // USE_ONNX

// 评估工厂类，用于创建评估器实例
class EvaluatorFactory {
public:
    enum class EvaluatorType {
        MANUAL,
        NNUE
    };
    
    // 创建评估器实例
    static std::unique_ptr<Evaluator> create_evaluator(EvaluatorType type, const std::string& model_path = "");
};

#endif // EVALUATOR_H