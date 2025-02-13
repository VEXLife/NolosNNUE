#pragma once
#include "player.h"

namespace agent
{
    class RandomPlayer : public Player
    {
    public:
        RandomPlayer();
        ~RandomPlayer();
        game::Pos getMove(game::Board board, game::GomokuState turn, int moveCount);
    };
}

using namespace agent;