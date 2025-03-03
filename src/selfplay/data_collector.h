#pragma once

#include "random_negamax.h"
#include "../agent/random_player.h"
#include "../agent/player.h"
#include <fstream>

namespace selfplay
{
    class DataCollector
    {
    public:
        DataCollector() {}
        ~DataCollector() {}
        void collectData(
            game::Gomoku &game_instance,
            RandomNegamaxPlayer &player_black,
            RandomNegamaxPlayer &player_white,
            int num_games = 1,
            string output_file = "output/selfplay_data.csv", 
            string log_file = "logs/selfplay.log");
    };
}

using namespace selfplay;