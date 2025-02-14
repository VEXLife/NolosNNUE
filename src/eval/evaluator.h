#pragma once

#include "../game/gomoku.h"

using namespace game;

namespace eval
{
    class Evaluator
    {
    public:
        virtual double evaluate(const Board& board, const GomokuState& turn) = 0;
    };
}