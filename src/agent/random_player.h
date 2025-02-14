#pragma once
#include "player.h"

namespace agent
{
    class RandomPlayer : public Player
    {
    public:
        RandomPlayer();
        ~RandomPlayer();
        game::Pos getMove(const game::Board& board, const game::GomokuState& turn, const int& moveCount);
    };
}

using namespace agent;