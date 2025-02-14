#pragma once
#include "player.h"
#include "../eval/evaluator.h"
#include <limits>
#include <algorithm>
#include <vector>
#include <string>
#include <iostream>
#include "spdlog/sinks/basic_file_sink.h"
#define INF std::numeric_limits<eval::score_t>::infinity()

namespace agent
{
    class NegamaxPlayer : public Player
    {
    public:
        NegamaxPlayer(int depth, int breadth, int neighbour_radius, eval::Evaluator *evaluator, string logdir = "logs/");
        ~NegamaxPlayer();
        game::Pos getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount);

    private:
        int depth, breadth, neighbour_radius;
        eval::Evaluator *evaluator;
        shared_ptr<spdlog::logger> logger;
        eval::score_t negamax(game::Gomoku* game_instance, float minimum, float maximum, eval::Evaluator* evaluator, int depthLeft);
        bool hasNeighbour(game::Gomoku* game_instance, game::Pos pos, int radius);
    };
}

using namespace agent;