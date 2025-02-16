#include "piskvork_proto.h"
#include "agent/random_player.h"
#include "agent/negamax.h"
#include "eval/classic.h"
#include "eval/onnx.h"

int main(int argc, char **argv)
{
// #ifdef _WIN32
//     auto evaluator = new eval::ONNXEvaluator(L"model.onnx");
// #else
//     auto evaluator = new eval::ONNXEvaluator("model.onnx");
// #endif
    auto evaluator = new eval::ClassicEvaluator();
    agent::Player *player = new agent::NegamaxPlayer(3, 5, 2, evaluator, 1'000'000);
    piskvorkProtoLoop(player);
    return 0;
}