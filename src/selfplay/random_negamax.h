#pragma once

#include "../agent/negamax.h"
#include <numeric>

using namespace agent;

namespace selfplay
{
    class RandomNegamaxPlayer : public NegamaxPlayer
    {
    public:
        RandomNegamaxPlayer(
            int depth,
            int breadth,
            int neighbour_radius,
            eval::Evaluator *evaluator,
            float temperature = 0.0f,
            size_t transposition_table_size = 1000000,
            string logdir = "logs/")
            : NegamaxPlayer(
                  depth,
                  breadth,
                  neighbour_radius,
                  evaluator,
                  transposition_table_size,
                  logdir)
        {
            this->temperature = temperature;
        }
        ~RandomNegamaxPlayer() {}
        game::Pos getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount);

    private:
        float temperature;
    };
}

using namespace selfplay;