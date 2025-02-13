#pragma once
#include "../game/gomoku.h"
#include <string>

namespace agent
{
    class Player
    {
    public:
        Player() {};
        virtual ~Player() {};
        virtual game::Pos getMove(game::Board board, game::GomokuState turn, int moveCount) = 0;
        string getPlayerInfo()
        {
            return player_info;
        }

    protected:
        string player_info;
    };
}