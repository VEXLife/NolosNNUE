#include "onnx.h"

ONNXEvaluator::ONNXEvaluator(const ORTCHAR_T* model_path){
    // Load ONNX model
    auto env = Ort::Env(ORT_LOGGING_LEVEL_WARNING, "NolosNNUE");
    this->session = Ort::Session(env, model_path, Ort::SessionOptions());
    this->memoryInfo = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
}

ONNXEvaluator::~ONNXEvaluator(){
}

score_t ONNXEvaluator::evaluate(const Board& board, const GomokuState& turn){
    auto n = board.size();
    if (n != this->initializedBoardSize){
        // Resize input tensor
        this->input.resize(n * n);
        this->inputShape = {1, 1, static_cast<int64_t>(n), static_cast<int64_t>(n)};
        this->inputTensors.push_back(
            Ort::Value::CreateTensor<float>(
                this->memoryInfo, 
                this->input.data(), 
                this->input.size(), 
                this->inputShape.data(), 
                this->inputShape.size()
            )
        );
        this->outputTensors.push_back(
            Ort::Value::CreateTensor<float>(
                this->memoryInfo, 
                this->output.data(), 
                this->output.size(), 
                this->outputShape.data(), 
                this->outputShape.size()
            )
        );
        this->initializedBoardSize = static_cast<int64_t>(n);
    }

    for (int i = 0; i < n; i++){
        for (int j = 0; j < n; j++){
            this->input[i * n + j] = board[i][j] == turn ? 1.0f : board[i][j] == GomokuState::EMPTY ? 0.0f : -1.0f;
        }
    }

    // Run inference
    this->session.Run(Ort::RunOptions{nullptr}, this->inputNames, this->inputTensors.data(), 1, this->outputNames, this->outputTensors.data(), 1);
    return this->output[0];
}