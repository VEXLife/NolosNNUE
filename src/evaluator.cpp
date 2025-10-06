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
    score += evaluate_material(board) * 10;
    
    // 评估位置价值
    score += evaluate_position(board);
    
    // // 评估机动性
    // score += evaluate_mobility(board);
    
    // // 评估威胁
    // score += evaluate_threats(board);
    
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
    // 初始化所有位置价值为0
    for (int p = 0; p < NUM_PIECE_TYPES; p++) {
        for (int y = 0; y < BOARD_HEIGHT; y++) {
            for (int x = 0; x < BOARD_WIDTH; x++) {
                red_piece_position_values_[p][y][x] = 0.0;
                black_piece_position_values_[p][y][x] = 0.0;
            }
        }
    }
    
    // 初始化红方车(RED_CHARIOT)的位置价值
    int chariot_type = static_cast<int>(PieceType::RED_CHARIOT);
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            // 车在九宫附近和河道附近价值更高
            if ((x >= 1 && x <= 7) || (y >= 4 && y <= 5)) {
                red_piece_position_values_[chariot_type][y][x] += 5.0;
            }
            
            // 车靠近对方将帅位置价值大幅提升（黑方九宫区域）
            if (y < 3 && x >= 3 && x <= 5) {
                red_piece_position_values_[chariot_type][y][x] += 8.0;
                // 特别靠近黑方将帅位置(4,9)的镜像位置(4,0)附近价值更高
                double distance_to_king = std::sqrt(std::pow(x - 4, 2) + std::pow(y - 0, 2));
                if (distance_to_king < 2.0) {
                    red_piece_position_values_[chariot_type][y][x] += 6.0;
                }
            }
        }
    }
    
    // 初始化红方马(RED_HORSE)的位置价值
    int horse_type = static_cast<int>(PieceType::RED_HORSE);
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            // 马在河口和九宫附近价值更高
            if ((y == 3 || y == 6) && (x >= 2 && x <= 6)) {
                red_piece_position_values_[horse_type][y][x] += 3.0;
            }
            
            // 马靠近对方将帅位置价值提升（黑方九宫区域）
            if (y < 4 && x >= 2 && x <= 6) {
                red_piece_position_values_[horse_type][y][x] += 4.0;
                // 特别靠近黑方将帅位置附近价值更高
                double distance_to_king = std::sqrt(std::pow(x - 4, 2) + std::pow(y - 0, 2));
                if (distance_to_king < 3.0) {
                    red_piece_position_values_[horse_type][y][x] += 3.0;
                }
            }
        }
    }
    
    // 初始化红方炮(RED_CANNON)的位置价值
    int cannon_type = static_cast<int>(PieceType::RED_CANNON);
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            // 炮在有炮架的位置价值更高
            if ((x == 1 || x == 7) && (y == 2 || y == 7)) {
                red_piece_position_values_[cannon_type][y][x] += 4.0;
            }
            
            // 炮在可以攻击对方将帅的位置价值提升
            // 特别在对方九宫区域（x >= 3 && x <= 5, y < 3）
            if (y < 3 && x >= 3 && x <= 5) {
                red_piece_position_values_[cannon_type][y][x] += 6.0;
                // 在可以直线攻击将帅的位置价值更高
                if (x == 4) {
                    red_piece_position_values_[cannon_type][y][x] += 4.0;
                }
            }
        }
    }
    
    // 初始化红方兵(RED_PAWN)的位置价值
    int pawn_type = static_cast<int>(PieceType::RED_PAWN);
    for (int y = 0; y < BOARD_HEIGHT; y++) {
        for (int x = 0; x < BOARD_WIDTH; x++) {
            // 兵过河价值增加，越靠近九宫价值越高
            if (y < 5) {
                red_piece_position_values_[pawn_type][y][x] += 5.0 + (4 - y) * 2.0;
            }
        }
    }
    
    // 为其他红方棋子设置基础位置价值
    int king_type = static_cast<int>(PieceType::RED_KING);
    int advisor_type = static_cast<int>(PieceType::RED_ADVISOR);
    int elephant_type = static_cast<int>(PieceType::RED_ELEPHANT);
    
    // 红方将/帅在九宫中心附近价值更高
    for (int y = 7; y <= 9; y++) {
        for (int x = 3; x <= 5; x++) {
            double distance_to_center = std::sqrt(std::pow(x - 4, 2) + std::pow(y - 8, 2));
            red_piece_position_values_[king_type][y][x] = 10.0 - distance_to_center * 2.0;
        }
    }
    
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

double ManualEvaluator::evaluate_mobility(const Chessboard& board) const {
    double mobility_score = 0.0;
    
    // 为当前行棋方的机动性加分
    Color current_player = board.get_current_player();
    
    // 临时棋盘，用于生成移动
    Chessboard temp_board = board;
    std::vector<Move> moves = temp_board.generate_moves();
    
    // 当前行棋方每有一个合法移动，获得一定的分数
    if (current_player == Color::RED) {
        mobility_score += moves.size() * 5.0;
    } else {
        mobility_score -= moves.size() * 5.0;
    }
    
    // 切换行棋方，评估对方的机动性
    temp_board.set_current_player(current_player == Color::RED ? Color::BLACK : Color::RED);
    std::vector<Move> opponent_moves = temp_board.generate_moves();
    
    // 对方每有一个合法移动，扣除一定的分数
    if (current_player == Color::RED) {
        mobility_score -= opponent_moves.size() * 5.0;
    } else {
        mobility_score += opponent_moves.size() * 5.0;
    }
    
    return mobility_score;
}

double ManualEvaluator::evaluate_threats(const Chessboard& board) const {
    double threat_score = 0.0;
    
    // 检查将军情况
    if (board.is_in_check(Color::BLACK)) {
        // 红方将军，加分
        threat_score += 100.0;
    }
    
    if (board.is_in_check(Color::RED)) {
        // 黑方将军，减分
        threat_score -= 100.0;
    }
    
    // 检查将死情况
    if (board.is_checkmate(Color::BLACK)) {
        // 红方将死黑方，大幅加分
        threat_score += 10000.0;
    }
    
    if (board.is_checkmate(Color::RED)) {
        // 黑方将死红方，大幅减分
        threat_score -= 10000.0;
    }
    
    // 检查困毙情况
    if (board.is_stalemate(Color::BLACK)) {
        // 黑方困毙，加分
        threat_score += 500.0;
    }
    
    if (board.is_stalemate(Color::RED)) {
        // 红方困毙，减分
        threat_score -= 500.0;
    }
    
    return threat_score;
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