#include "onnx.h"

ONNXEvaluator::ONNXEvaluator(const ORTCHAR_T* model_path){
    // Load ONNX model
    auto env = Ort::Env(ORT_LOGGING_LEVEL_WARNING, "NolosNNUE");
    this->m_session = std::make_shared<Ort::Session>(env, model_path, Ort::SessionOptions());
}

ONNXEvaluator::~ONNXEvaluator(){
    // Release resources
    this->m_session.reset();
}

score_t ONNXEvaluator::evaluate(const Board& board, const GomokuState& turn){
    // Prepare input tensor
    auto n = 15;
    std::vector<float> input(n * n);
    for (size_t i = 0; i < n; i++) {
        for (size_t j = 0; j < n; j++) {
            input[i * n + j] = board[i][j] == turn? 1.0f : board[i][j] == GomokuState::EMPTY? 0.0f : -1.0f;
        }
    }
    auto input_tensor = Ort::Value::CreateTensor<float>(m_memory_info, input.data(), input.size(), m_input_shape.data(), m_input_shape.size());
    // Run inference
    std::vector<Ort::Value> output_tensors = this->m_session->Run(this->m_run_options, m_input_names, &input_tensor, 1, m_output_names, 2);
    auto value = output_tensors.at(1).GetTensorMutableData<float>()[0];
    return value;
}