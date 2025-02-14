#pragma once

#include "../game/gomoku.h"
#include "evaluator.h"

using namespace game;

namespace eval
{
    class ClassicEvaluator : public Evaluator
    {
    public:
        ClassicEvaluator() = default;
        ~ClassicEvaluator() = default;

        double evaluate(const Board &board, const GomokuState &turn);

    private:
        int countConsecutiveStones(const Board &board, const Pos &pos, int dx, int dy, const GomokuState &turn) const;
        double evaluateLine(const Board &board, const Pos &pos, int dx, int dy, const GomokuState &turn) const;
    };
}

using namespace eval;