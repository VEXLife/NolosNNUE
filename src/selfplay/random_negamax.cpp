#include "random_negamax.h"

game::Pos RandomNegamaxPlayer::getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount)
{
    if (moveCount == 0)
    {
        return game::Pos{(int)board.size() / 2, (int)board.size() / 2};
    }
    auto game_instance = new game::Gomoku(board, turn, moveCount);

    // Initialize zobrist keys if board size has changed
    if (game_instance->getSize() != zobristInitializedBoardSize)
    {
        zobristInitializedBoardSize = game_instance->getSize();
        initZobristKeys(zobristInitializedBoardSize);
    }
    auto zobrist_key = generateZobristKey(board);

    // Prepare all possible moves
    vector<pair<game::Pos, eval::score_t>> move_scores;
    for (int i = 0; i < game_instance->getSize(); i++)
    {
        for (int j = 0; j < game_instance->getSize(); j++)
        {
            if (game_instance->get(Pos{i, j}) == game::GomokuState::EMPTY && hasNeighbour(game_instance, game::Pos{i, j}, neighbour_radius))
            {
                move_scores.push_back(make_pair(game::Pos{i, j}, 0.0f)); // 0 for placeholder
            }
        }
    }

    // Initialize statitics
    this->searchedNodesCount = 0;

    for (int current_depth = 0; current_depth <= depth; current_depth++)
    { // Iterative deepening
        eval::score_t bestValue = -INF;
        auto maximum = INF;
        auto minimum = -INF;
        bool is_first_move = true;
        for (auto &move_score : move_scores)
        {
            updateZobristKey(zobrist_key, move_score.first, GomokuState::EMPTY, game_instance->getTurn());
            game_instance->move(move_score.first);
            if (game_instance->getWinner() == opponent(game_instance->getTurn()))
            {
                game_instance->undo();
                updateZobristKey(zobrist_key, move_score.first, game_instance->getTurn(), GomokuState::EMPTY);
                return move_score.first;
            }

            vector<Pos> child_path = {move_score.first};
            eval::score_t value;
            if (is_first_move)
            {
                value = -negamax(
                    game_instance,
                    -maximum,
                    -minimum,
                    evaluator,
                    current_depth,
                    zobrist_key,
                    child_path);
                is_first_move = false;
            }
            else
            {
                value = -negamax(
                    game_instance,
                    -minimum - 1,
                    -minimum,
                    evaluator,
                    current_depth,
                    zobrist_key,
                    child_path);
                if (value > minimum && maximum - minimum > 1)
                { // Full re-search
                    child_path = {move_score.first};
                    value = -negamax(
                        game_instance,
                        -maximum,
                        -minimum,
                        evaluator,
                        current_depth,
                        zobrist_key,
                        child_path);
                }
            }
            move_score.second = value;
            game_instance->undo();
            updateZobristKey(zobrist_key, move_score.first, game_instance->getTurn(), GomokuState::EMPTY);
            if (value > bestValue)
            {
                bestValue = value;
                minimum = max(minimum, value);
            }
            if (value >= maximum)
            {
                break;
            }
        }

        if (bestValue == -INF || bestValue == INF)
        {
            break;
        }
        sort(move_scores.begin(), move_scores.end(), CompareMoveScoresGreater()); // Sort by score
    }

    // Do softmax
    if (move_scores[0].second == INF) {
        return move_scores[0].first;
    }
    std::random_device rd;
    std::mt19937 gen(rd());
    if (move_scores[0].second == -INF) {
        // Pick one randomly
        std::uniform_int_distribution<> d(0, (int)move_scores.size() - 1);
        return move_scores[d(gen)].first;
    }
    vector<eval::score_t> exp_move_probs;
    for (auto &move_score : move_scores)
    {
        exp_move_probs.push_back(exp((move_score.second - move_scores[0].second) / temperature));
    }
    auto sum = std::accumulate(exp_move_probs.begin(), exp_move_probs.end(), 0.0f);
    auto temperature = this->temperature; // Capture the member variable
    std::for_each(
        exp_move_probs.begin(),
        exp_move_probs.end(),
        [sum, temperature](eval::score_t &a)
        {
            a /= sum;
        });

    // Sample a move
    std::discrete_distribution<> d(exp_move_probs.begin(), exp_move_probs.end());
    return move_scores[d(gen)].first;
}