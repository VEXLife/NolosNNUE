#pragma once
#include "../game/gomoku.h"
#include <string>

namespace agent
{
    class Player
    {
    public:
        virtual game::Pos getMove(const game::Board& board, const game::GomokuState& turn, const int& moveCount) = 0;
        string getPlayerInfo()
        {
            return player_info;
        }

    protected:
        string player_info;
    };
}