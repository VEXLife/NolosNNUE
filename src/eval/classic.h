#pragma once

#include "../game/gomoku.h"
#include "evaluator.h"

using namespace game;

namespace eval
{
    // Define some constants to represent the scores of different chess patterns
    const int ME_FOUR_STRAIGHT = 1000000; // Live four
    const int ME_FOUR_SLEEP = 100000;     // Sleeping four
    const int ME_THREE_STRAIGHT = 10000;  // Live three
    const int ME_THREE_JUMP = 1000;     // Jump three
    const int ME_THREE_SLEEP = 100;      // Sleeping three
    const int ME_TWO_STRAIGHT = 5;     // Live two
    const int ME_TWO_JUMP = 1;          // Jump two

    const int OPPO_FOUR_STRAIGHT = -100000; // Live four
    const int OPPO_FOUR_SLEEP = -10000;     // Sleeping four
    const int OPPO_THREE_STRAIGHT = -1000;  // Live three
    const int OPPO_THREE_JUMP = -100;     // Jump three
    const int OPPO_THREE_SLEEP = -10;      // Sleeping three
    const int OPPO_TWO_STRAIGHT = -5;     // Live two
    const int OPPO_TWO_JUMP = -1;          // Jump two

    class ClassicEvaluator : public Evaluator
    {
    public:
        ClassicEvaluator() = default;
        ~ClassicEvaluator() = default;

        score_t evaluate(const Board &board, const GomokuState &turn);

    private:
        int checkDirection(const Board &board, int x, int y, int dx, int dy, const GomokuState &turn);
    };
}

using namespace eval;