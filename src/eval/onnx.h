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
        std::shared_ptr<Ort::Session> m_session;
        Ort::RunOptions m_run_options;
        Ort::MemoryInfo m_memory_info = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeCPU);
        vector<int64_t> m_input_shape = {1, 1, 15, 15};
        vector<int64_t> m_policy_shape = {1, 15, 15};
        vector<int64_t> m_value_shape = {1, 1};
        const char* m_input_names[1] = {"inputs"};
        const char* m_output_names[2] = {"softmax_0.tmp_0", "tanh_0.tmp_0"};
    };
}

using namespace eval;