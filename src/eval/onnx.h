#pragma once

#include "evaluator.h"
#include <onnxruntime_cxx_api.h>

using namespace game;

namespace eval
{
    class ONNXEvaluator : public Evaluator
    {
    public:
        ONNXEvaluator(const ORTCHAR_T* model_path);
        ~ONNXEvaluator();

        score_t evaluate(const Board &board, const GomokuState &turn);

    private:
        int64_t initializedBoardSize = 0;
        Ort::Session session {nullptr};
        Ort::RunOptions runOptions;
        Ort::MemoryInfo memoryInfo = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeCPU);
        const char* inputNames[1] = {"inputs"};
        const char* outputNames[1] = {"value_head"};
        std::vector<float> input;
        std::vector<float> output = {0.0f};
        std::vector<int64_t> inputShape;
        std::vector<int64_t> outputShape = {1, 1};
        std::vector<Ort::Value> inputTensors;
        std::vector<Ort::Value> outputTensors;
    };
}

using namespace eval;