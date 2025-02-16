#include "negamax.h"

struct CompareMoveScoresGreater
{
    bool operator()(const pair<game::Pos, eval::score_t> &a, const pair<game::Pos, eval::score_t> &b)
    {
        return a.second > b.second;
    }
};

struct CompareMoveScoresLess
{
    bool operator()(const pair<game::Pos, eval::score_t> &a, const pair<game::Pos, eval::score_t> &b)
    {
        return a.second < b.second;
    }
};

NegamaxPlayer::NegamaxPlayer(
    int depth,
    int breadth,
    int neighbour_radius,
    eval::Evaluator *evaluator,
    size_t transposition_table_size,
    string logdir)
    : evaluator(evaluator), depth(depth), breadth(breadth), neighbour_radius(neighbour_radius)
{
    this->transpositionTable = new TranspositionTable(transposition_table_size);
    try
    {
        this->logger = spdlog::basic_logger_mt("NegamaxPlayer", logdir + "negamax.log");
        this->logger->flush_on(spdlog::level::debug);
        this->logger->set_level(spdlog::level::debug);
    }
    catch (spdlog::spdlog_ex &e)
    {
        cout << "ERROR Log file error: " << e.what() << endl;
    }
}

NegamaxPlayer::~NegamaxPlayer()
{
    delete this->transpositionTable;
}

eval::score_t NegamaxPlayer::negamax(
    game::Gomoku *game_instance,
    eval::score_t minimum,
    eval::score_t maximum,
    eval::Evaluator *evaluator,
    int depth_left,
    ZobristKey &zobrist_key,
    vector<Pos> &path)
{
    // Zobrist Table based cutoff
    auto ttEntry = this->transpositionTable->get(zobrist_key);
    if (ttEntry.key == zobrist_key)
    {
        if (ttEntry.depth >= depth_left)
        {
            // logger->debug("TT hit");
            if (ttEntry.flag == EXACT)
            {
                return ttEntry.score;
            }
            else if (ttEntry.flag == LOWERBOUND)
            {
                minimum = max(minimum, ttEntry.score);
            }
            else if (ttEntry.flag == UPPERBOUND)
            {
                maximum = min(maximum, ttEntry.score);
            }
            if (minimum >= maximum)
            {
                return ttEntry.score;
            }
        }
    }

    if (depth_left == 0)
    {
        this->searchedNodesCount++;

        auto value = evaluator->evaluate(game_instance->getBoard(), game_instance->getTurn());

        ttEntry.score = value;
        ttEntry.flag = TTFlag::EXACT;
        ttEntry.depth = depth_left;
        ttEntry.key = zobrist_key;
        this->transpositionTable->set(zobrist_key, ttEntry);

        return value;
    }

    priority_queue<pair<game::Pos, eval::score_t>, vector<pair<game::Pos, eval::score_t>>, CompareMoveScoresLess> move_scores;
    for (int i = 0; i < game_instance->getSize(); i++)
    {
        for (int j = 0; j < game_instance->getSize(); j++)
        {
            if (game_instance->get(Pos{i, j}) == game::GomokuState::EMPTY && hasNeighbour(game_instance, game::Pos{i, j}, neighbour_radius))
            {
                updateZobristKey(zobrist_key, game::Pos{i, j}, GomokuState::EMPTY, game_instance->getTurn());
                game_instance->move(game::Pos{i, j});
                if (game_instance->getWinner() == opponent(game_instance->getTurn()))
                {
                    game_instance->undo();
                    path.push_back(game::Pos{i, j});
                    return INF;
                }
                vector<Pos> child_path;
                auto value = -negamax(
                    game_instance,
                    -maximum,
                    -minimum,
                    evaluator,
                    0,
                    zobrist_key,
                    child_path);
                game_instance->undo();
                updateZobristKey(zobrist_key, game::Pos{i, j}, game_instance->getTurn(), GomokuState::EMPTY);
                move_scores.push(make_pair(game::Pos{i, j}, value));
            }
        }
    }

    auto best_value = -INF;
    auto best_child_path = vector<Pos>();
    while (!move_scores.empty())
    {
        auto move_score = move_scores.top();
        move_scores.pop();
        updateZobristKey(zobrist_key, move_score.first, GomokuState::EMPTY, game_instance->getTurn());
        game_instance->move(move_score.first);
        vector<Pos> child_path = {move_score.first};
        eval::score_t value = -negamax(
            game_instance,
            -maximum,
            -minimum,
            evaluator,
            depth_left - 1,
            zobrist_key,
            child_path);
        game_instance->undo();
        updateZobristKey(zobrist_key, move_score.first, game_instance->getTurn(), GomokuState::EMPTY);
        if (value > best_value)
        {
            best_value = value;
            best_child_path = child_path;
            minimum = max(minimum, value);
        }
        if (value >= maximum)
        {
            // logger->debug("Pruning at depth {} with value {}", depth_left, value);
            break;
        }
    }

    if (depth_left >= ttEntry.depth)
    {
        ttEntry.score = best_value;
        ttEntry.flag = best_value < minimum   ? TTFlag::UPPERBOUND
                       : best_value > maximum ? TTFlag::LOWERBOUND
                                              : TTFlag::EXACT;
        ttEntry.depth = depth_left;
        ttEntry.key = zobrist_key;
        this->transpositionTable->set(zobrist_key, ttEntry);
    }

    path.insert(path.end(), best_child_path.begin(), best_child_path.end());

    return best_value;
}

game::Pos NegamaxPlayer::getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount)
{
    if (moveCount == 0)
    {
        return game::Pos{(int)board.size() / 2, (int)board.size() / 2};
    }
    auto game_instance = new game::Gomoku(board, turn, moveCount);

    // Initialize zobrist keys if board size has changed
    if (game_instance->getSize() != zobristInitializedBoardSize)
    {
        logger->debug("Board size changed, reinitializing zobrist keys");
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
    chrono::high_resolution_clock::time_point start_time = chrono::high_resolution_clock::now();

    Pos bestPos;
    for (int current_depth = 0; current_depth <= depth; current_depth++)
    { // Iterative deepening
        eval::score_t bestValue = -INF;
        auto maximum = INF;
        auto minimum = -INF;
        Pos new_bestPos;
        auto best_child_path = vector<Pos>();
        for (auto &move_score : move_scores)
        {
            updateZobristKey(zobrist_key, move_score.first, GomokuState::EMPTY, game_instance->getTurn());
            game_instance->move(move_score.first);
            logger->debug("Depth: {}, Evaluating move {}", current_depth, move_score.first.str());
            logger->debug("Current board:\n{}", game_instance->getPrintBoardStr(false));
            if (game_instance->getWinner() == opponent(game_instance->getTurn()))
            {
                game_instance->undo();
                logger->debug("Found winning move {}, returning. Not showing time taken.", move_score.first.str());
                return move_score.first;
            }
            vector<Pos> child_path = {move_score.first};
            eval::score_t value = -negamax(
                game_instance,
                -maximum,
                -minimum,
                evaluator,
                current_depth,
                zobrist_key,
                child_path);
            move_score.second = value;
            string pvMoves;
            for (auto &move : child_path)
            {
                pvMoves += move.str();
            }
            logger->debug("Value: {}, PV: {}", value, pvMoves);
            game_instance->undo();
            updateZobristKey(zobrist_key, move_score.first, game_instance->getTurn(), GomokuState::EMPTY);
            if (value > bestValue)
            {
                bestValue = value;
                new_bestPos = move_score.first;
                best_child_path = child_path;
                minimum = max(minimum, value);
            }
            if (value >= maximum)
            {
                break;
            }
        }
        string pvMoves;
        for (auto &move : best_child_path)
        {
            pvMoves += move.str();
        }
        logger->debug("PV: {}", pvMoves);

        if (bestValue == -INF)
        {
            logger->debug("The opponent is bound to win!");
            break;
        }
        bestPos = new_bestPos;
        if (bestValue == INF)
        {
            logger->debug("I am bound to win!");
            break;
        }
        sort(move_scores.begin(), move_scores.end(), CompareMoveScoresGreater()); // Sort by score
    }

    // Show statistics
    chrono::high_resolution_clock::time_point end_time = chrono::high_resolution_clock::now();
    auto duration = chrono::duration_cast<chrono::milliseconds>(end_time - start_time).count();
    logger->debug("Time taken: {} s, searched nodes: {}", 1.0f * duration / 1000, this->searchedNodesCount);
    return bestPos;
}

bool NegamaxPlayer::hasNeighbour(game::Gomoku *game_instance, game::Pos pos, int radius)
{
    for (int i = -radius; i <= radius; i++)
    {
        auto new_x = pos.x + i;
        if (new_x < 0 || new_x >= game_instance->getSize())
        {
            continue;
        }
        for (int j = -radius; j <= radius; j++)
        {
            auto new_y = pos.y + j;
            if (new_y < 0 || new_y >= game_instance->getSize())
            {
                continue;
            }
            if (game_instance->get(Pos{new_x, new_y}) != game::GomokuState::EMPTY)
            {
                return true;
            }
        }
    }
    return false;
}

void NegamaxPlayer::initZobristKeys(const int &board_size)
{
    std::mt19937 gen(0); // 0 is seed for reproducibility
    std::uniform_int_distribution<uint64_t> dis(0, std::numeric_limits<uint64_t>::max());

    zobristTable = vector<vector<vector<uint64_t>>>(
        board_size,
        vector<vector<uint64_t>>(
            board_size,
            vector<uint64_t>(3)));
    for (int i = 0; i < board_size; i++)
    {
        for (int j = 0; j < board_size; j++)
        {
            for (int k = 0; k < 3; k++)
            {
                zobristTable[i][j][k] = dis(gen);
            }
        }
    }
}

void NegamaxPlayer::updateZobristKey(ZobristKey &key, const game::Pos &pos, const game::GomokuState &prev_state, const game::GomokuState &new_state)
{
    key ^= zobristTable[pos.x][pos.y][(size_t)prev_state];
    key ^= zobristTable[pos.x][pos.y][(size_t)new_state];
}

ZobristKey NegamaxPlayer::generateZobristKey(const game::Board &board)
{
    ZobristKey key = 0;
    for (int i = 0; i < board.size(); i++)
    {
        for (int j = 0; j < board.size(); j++)
        {
            key ^= zobristTable[i][j][(size_t)board[i][j]];
        }
    }
    return key;
}
