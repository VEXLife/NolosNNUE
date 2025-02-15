#pragma once
#include "player.h"
#include "../eval/evaluator.h"
#include "spdlog/sinks/basic_file_sink.h"
#include <unordered_map>
#include <limits>
#include <algorithm>
#include <vector>
#include <queue>
#include <string>
#include <iostream>
#include <random>
#define INF std::numeric_limits<eval::score_t>::infinity()

namespace agent
{
    enum TTFlag
    {
        EXACT,
        LOWERBOUND,
        UPPERBOUND,
    };

    using ZobristKey = uint64_t;
    struct TTEntry
    {
        eval::score_t score;
        TTFlag flag;
        int depth;
        ZobristKey key;
        TTEntry() : score(0), flag(EXACT), depth(0), key(0) {}
    };

    class TranspositionTable
    {
    public:
        TranspositionTable(const size_t &size) : size(size)
        {
            this->m_table = new TTEntry[size];
        }
        ~TranspositionTable()
        {
            delete[] this->m_table;
        }

        TTEntry get(ZobristKey &key)
        {
            return this->m_table[key % this->size];
        }

        void set(ZobristKey &key, const TTEntry &entry)
        {
            this->m_table[key % this->size] = entry;
        }

    private:
        size_t size;
        TTEntry *m_table;
    };

    class NegamaxPlayer : public Player
    {
    public:
        NegamaxPlayer(
            int depth,
            int breadth,
            int neighbour_radius,
            eval::Evaluator *evaluator,
            size_t transposition_table_size = 1000000,
            string logdir = "logs/");
        ~NegamaxPlayer();
        game::Pos getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount);

    private:
        int depth, breadth, neighbour_radius;
        eval::Evaluator *evaluator;
        shared_ptr<spdlog::logger> logger;
        eval::score_t negamax(
            game::Gomoku *game_instance,
            float minimum, float maximum,
            eval::Evaluator *evaluator,
            int depth_left,
            ZobristKey &zobristKey,
            vector<Pos> &path
        );
        bool hasNeighbour(game::Gomoku *game_instance, game::Pos pos, int radius);

        TranspositionTable *transpositionTable;
        vector<vector<vector<ZobristKey>>> zobristTable;
        int zobristInitializedBoardSize = 0;
        void initZobristKeys(const int &);
        ZobristKey generateZobristKey(const game::Board &board);
        void updateZobristKey(
            ZobristKey &key,
            const game::Pos &pos,
            const game::GomokuState &prev_state,
            const game::GomokuState &new_state);

        uint64_t searchedNodesCount = 0;
    };
}

using namespace agent;