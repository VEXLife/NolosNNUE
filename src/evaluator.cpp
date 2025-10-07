#include "evaluator.h"
#include <iostream>
#include <cmath>

ManualEvaluator::ManualEvaluator() {
    initialize_piece_values();
    initialize_position_values();
}

double ManualEvaluator::evaluate(const Chessboard& board) {
    double score = 0.0;
    
    // 评估棋子价值
    // score += evaluate_material(board) * 20;
    
    // 评估位置价值
    score += evaluate_position(board);
    
    return board.get_current_player() == Color::RED ? score : -score;
}

void ManualEvaluator::initialize_piece_values() {
    // 初始化棋子价值表（基于中国象棋的传统价值体系）
    piece_values_[static_cast<int>(PieceType::EMPTY)] = 0.0;
    piece_values_[static_cast<int>(PieceType::RED_KING)] = 1000.0; // 将帅是最重要的，价值无限大
    piece_values_[static_cast<int>(PieceType::RED_ADVISOR)] = 2.0;
    piece_values_[static_cast<int>(PieceType::RED_ELEPHANT)] = 2.0;
    piece_values_[static_cast<int>(PieceType::RED_HORSE)] = 4.0;
    piece_values_[static_cast<int>(PieceType::RED_CHARIOT)] = 8.0;
    piece_values_[static_cast<int>(PieceType::RED_CANNON)] = 4.0;
    piece_values_[static_cast<int>(PieceType::RED_PAWN)] = 1.0;
    piece_values_[static_cast<int>(PieceType::BLACK_KING)] = -1000.0;
    piece_values_[static_cast<int>(PieceType::BLACK_ADVISOR)] = -2.0;
    piece_values_[static_cast<int>(PieceType::BLACK_ELEPHANT)] = -2.0;
    piece_values_[static_cast<int>(PieceType::BLACK_HORSE)] = -4.0;
    piece_values_[static_cast<int>(PieceType::BLACK_CHARIOT)] = -8.0;
    piece_values_[static_cast<int>(PieceType::BLACK_CANNON)] = -4.0;
    piece_values_[static_cast<int>(PieceType::BLACK_PAWN)] = -1.0;
}

void ManualEvaluator::initialize_position_values() {    
    // 初始化红方车(RED_CHARIOT)的位置价值
    int chariot_type = static_cast<int>(PieceType::RED_CHARIOT);
    red_piece_position_values_[chariot_type] = {
        8.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 8.0, 
        10.0, 10.0, 10.0, 11.0, 10.0, 11.0, 10.0, 10.0, 10.0, 
        10.0, 10.0, 10.0, 11.0, 10.0, 11.0, 10.0, 10.0, 10.0, 
        10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 10.0, 10.0, 10.0, 
        10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 10.0, 10.0, 10.0, 
        10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 10.0, 10.0, 10.0, 
        10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 10.0, 10.0, 10.0, 
        12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0,  
        12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0,  
        12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0,  
    };
    
    // 初始化红方炮(RED_CANNON)的位置价值
    int cannon_type = static_cast<int>(PieceType::RED_CANNON);
    red_piece_position_values_[cannon_type] = {
        4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        4.0, 4.0, 4.0, 4.0, 8.0, 4.0, 4.0, 4.0, 4.0, 
        8.0, 8.0, 8.0, 6.0, 8.0, 6.0, 8.0, 8.0, 8.0, 
    };
    
    // 初始化红方马(RED_HORSE)的位置价值
    int horse_type = static_cast<int>(PieceType::RED_HORSE);
    red_piece_position_values_[horse_type] = {
        3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 
        3.0, 4.0, 4.0, 6.0, 4.0, 6.0, 4.0, 4.0, 3.0, 
        3.0, 4.0, 6.0, 6.0, 6.0, 6.0, 6.0, 4.0, 3.0, 
        3.0, 4.0, 6.0, 6.0, 6.0, 6.0, 6.0, 4.0, 3.0, 
        3.0, 4.0, 6.0, 6.0, 6.0, 6.0, 6.0, 4.0, 3.0, 
        6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 
        6.0, 6.0, 6.0, 8.0, 8.0, 8.0, 6.0, 6.0, 6.0, 
        6.0, 6.0, 8.0, 8.0, 8.0, 8.0, 8.0, 6.0, 6.0, 
        6.0, 6.0, 8.0, 8.0, 8.0, 8.0, 8.0, 6.0, 6.0, 
        6.0, 6.0, 8.0, 8.0, 8.0, 8.0, 8.0, 6.0, 6.0, 
    };
    
    // 初始化红方兵(RED_PAWN)的位置价值
    int pawn_type = static_cast<int>(PieceType::RED_PAWN);
    red_piece_position_values_[pawn_type] = {
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        1.0, 0.0, 2.0, 0.0, 3.0, 0.0, 2.0, 0.0, 1.0,
        2.0, 0.0, 4.0, 0.0, 4.0, 0.0, 4.0, 0.0, 2.0,
        3.0, 3.0, 4.0, 4.0, 5.0, 4.0, 4.0, 3.0, 3.0,
        4.0, 4.0, 5.0, 6.0, 6.0, 6.0, 5.0, 4.0, 4.0,
        4.0, 5.0, 6.0, 6.0, 6.0, 6.0, 6.0, 5.0, 4.0,
        4.0, 5.0, 6.0, 6.0, 8.0, 6.0, 6.0, 5.0, 4.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    };
    
    // 初始化红方士(RED_ADVISOR)的位置价值
    int advisor_type = static_cast<int>(PieceType::RED_ADVISOR);
    red_piece_position_values_[advisor_type] = {
        0.0, 0.0, 0.0, 2.0, 0.0, 2.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    };
    
    // 初始化红方象(RED_ELEPHANT)的位置价值
    int elephant_type = static_cast<int>(PieceType::RED_ELEPHANT);
    red_piece_position_values_[elephant_type] = {
        0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 2.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    };
    
    // 初始化红方帅(RED_KING)的位置价值
    int king_type = static_cast<int>(PieceType::RED_KING);
    red_piece_position_values_[king_type] = {
        0.0, 0.0, 0.0, 1000.0, 1000.0, 1000.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 997.0, 997.0, 997.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 997.0, 997.0, 997.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    };
    
    // 初始化黑方棋子的位置价值（红方的镜像）
    for (int p = 1; p <= 7; p++) { // 红方棋子类型1-7
        int black_piece = p + 7;   // 对应的黑方棋子类型8-14
        for (int y = 0; y < BOARD_HEIGHT; y++) {
            for (int x = 0; x < BOARD_WIDTH; x++) {
                black_piece_position_values_[black_piece][y][x] = -red_piece_position_values_[p][9 - y][x];
            }
        }
    }
}

double ManualEvaluator::evaluate_material(const Chessboard& board) const {
    double material_score = 0.0;
    
    // 计算所有棋子的价值总和
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = board.get_piece(x, y);
            material_score += piece_values_[static_cast<int>(piece)];
        }
    }
    
    return material_score;
}

double ManualEvaluator::evaluate_position(const Chessboard& board) const {
    double position_score = 0.0;
    
    // 计算所有棋子的位置价值总和
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            PieceType piece = board.get_piece(x, y);
            if (piece != PieceType::EMPTY) {
                int piece_index = static_cast<int>(piece);
                position_score += (piece_index <= 7) ? 
                    red_piece_position_values_[piece_index][y][x] : 
                    black_piece_position_values_[piece_index][y][x];
            }
        }
    }
    
    return position_score;
}

#ifdef USE_ONNX
NnueEvaluator::NnueEvaluator(const std::string& model_path) : session_(nullptr) {
    initialize_onnx_runtime(model_path);
}

NnueEvaluator::~NnueEvaluator() {
    release_resources();
}

double NnueEvaluator::evaluate(const Chessboard& board) {
    if (!is_model_loaded()) {
        // 如果模型没有加载成功，返回0分
        return 0.0;
    }
    
    try {
        // 将棋盘转换为神经网络输入
        std::vector<float> input_tensor_values = board_to_input(board);
        
        // 创建输入张量
        Ort::MemoryInfo memory_info = Ort::MemoryInfo::CreateCpu(OrtAllocatorType::OrtArenaAllocator, OrtMemType::OrtMemTypeDefault);
        Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
            memory_info,
            input_tensor_values.data(),
            input_tensor_values.size(),
            input_shape_.data(),
            input_shape_.size()
        );
        
        // 运行推理
        Ort::Value output_tensor = session_->Run(
            Ort::RunOptions{nullptr},
            input_names_.data(),
            &input_tensor,
            1,
            output_names_.data(),
            1
        )[0];
        
        // 获取输出结果
        float* output_data = output_tensor.GetTensorMutableData<float>();
        double score = static_cast<double>(output_data[0]);
        
        return score;
    } catch (const Ort::Exception& e) {
        std::cerr << "ONNX Runtime exception: " << e.what() << std::endl;
        return 0.0;
    }
}

bool NnueEvaluator::is_model_loaded() const {
    return session_ != nullptr;
}

std::vector<float> NnueEvaluator::board_to_input(const Chessboard& board) const {
    // 将棋盘状态转换为神经网络输入
    // 这里假设神经网络输入是一个10x9x14的张量，表示棋盘上每个位置的14种棋子类型
    std::vector<float> input(10 * 9 * 14, 0.0f);
    
    for (int y = 0; y < 10; y++) {
        for (int x = 0; x < 9; x++) {
            PieceType piece = board.get_piece(x, y);
            if (piece != PieceType::EMPTY) {
                int piece_index = static_cast<int>(piece) - 1; // 棋子类型索引（从0开始）
                int position_index = y * 9 * 14 + x * 14 + piece_index;
                input[position_index] = 1.0f;
            }
        }
    }
    
    // 添加当前行棋方信息
    if (board.get_current_player() == Color::RED) {
        // 红方行棋，在最后一个位置设置为1
        input.back() = 1.0f;
    }
    
    return input;
}

void NnueEvaluator::initialize_onnx_runtime(const std::string& model_path) {
    try {
        // 初始化ONNX Runtime环境
        env_ = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "NolosNNUE");
        
        // 创建会话选项
        Ort::SessionOptions session_options;
        session_options.SetIntraOpNumThreads(1);
        session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        
        // 创建会话
        session_ = new Ort::Session(env_, model_path.c_str(), session_options);
        
        // 获取输入名称和形状
        size_t num_input_nodes = session_->GetInputCount();
        size_t num_output_nodes = session_->GetOutputCount();
        
        // 假设只有一个输入和一个输出
        if (num_input_nodes >= 1 && num_output_nodes >= 1) {
            // 获取输入名称
            char* input_name = allocator_.AllocString(session_->GetInputName(0, allocator_));
            input_names_.push_back(input_name);
            
            // 获取输出名称
            char* output_name = allocator_.AllocString(session_->GetOutputName(0, allocator_));
            output_names_.push_back(output_name);
            
            // 获取输入形状
            Ort::TypeInfo input_type_info = session_->GetInputTypeInfo(0);
            auto tensor_info = input_type_info.GetTensorTypeAndShapeInfo();
            input_shape_ = tensor_info.GetShape();
        }
        
        std::cout << "NNUE model loaded successfully from " << model_path << std::endl;
    } catch (const Ort::Exception& e) {
        std::cerr << "Failed to load ONNX model: " << e.what() << std::endl;
        session_ = nullptr;
    }
}

void NnueEvaluator::release_resources() {
    if (session_) {
        // 释放输入输出名称
        for (auto& name : input_names_) {
            allocator_.Free(name);
        }
        for (auto& name : output_names_) {
            allocator_.Free(name);
        }
        
        // 释放会话
        delete session_;
        session_ = nullptr;
    }
}
#endif // USE_ONNX

std::unique_ptr<Evaluator> EvaluatorFactory::create_evaluator(EvaluatorType type, const std::string& model_path) {
    switch (type) {
        case EvaluatorType::MANUAL:
            return std::make_unique<ManualEvaluator>();
        case EvaluatorType::NNUE:
#ifdef USE_ONNX
            return std::make_unique<NnueEvaluator>(model_path);
#else
            std::cerr << "Warning: NNUE evaluator is not available. Using manual evaluator instead." << std::endl;
            return std::make_unique<ManualEvaluator>();
#endif
        default:
            return std::make_unique<ManualEvaluator>();
    }
}