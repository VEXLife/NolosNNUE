#pragma once

#include "../game/gomoku.h"

using namespace game;

namespace eval
{
    typedef float score_t;

    class Evaluator
    {
    public:
        virtual score_t evaluate(const Board& board, const GomokuState& turn) = 0;
    };
}