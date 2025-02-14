#include "negamax.h"

NegamaxPlayer::NegamaxPlayer(int depth, int breadth, int neighbour_radius, eval::Evaluator *evaluator, string logdir)
    : evaluator(evaluator), depth(depth), breadth(breadth), neighbour_radius(neighbour_radius)
{
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

NegamaxPlayer::~NegamaxPlayer() {}

eval::score_t NegamaxPlayer::negamax(game::Gomoku *game_instance, eval::score_t minimum, eval::score_t maximum, eval::Evaluator *evaluator, int depthLeft)
{
    if (depthLeft == 0)
    {
        logger->debug("Reached depth limit, returning evaluator score");
        return evaluator->evaluate(game_instance->getBoard(), game_instance->getTurn());
    }
    for (int i = 0; i < game_instance->getSize(); i++)
    {
        for (int j = 0; j < game_instance->getSize(); j++)
        {
            if (game_instance->get(Pos{i, j}) == game::GomokuState::EMPTY && hasNeighbour(game_instance, game::Pos{i, j}, neighbour_radius))
            {
                game_instance->move(game::Pos{i, j});
                logger->debug("Depth left: {}, Evaluating move ({},{})", depthLeft, i, j);
                logger->debug("Current board:\n{}", game_instance->getPrintBoardStr());
                if (game_instance->getWinner() == opponent(game_instance->getTurn()))
                {
                    logger->debug("Found winning move, value: INF");
                    return INF;
                }
                eval::score_t value = -negamax(game_instance, -maximum, -minimum, evaluator, depthLeft - 1);
                logger->debug("Value: {}", value);
                game_instance->undo();
                minimum = std::max(minimum, value);
                if (minimum >= maximum)
                {
                    return minimum;
                }
            }
        }
    }
    return minimum;
}

game::Pos NegamaxPlayer::getMove(const game::Board &board, const game::GomokuState &turn, const int &moveCount)
{
    if (moveCount == 0)
    {
        return game::Pos{(int)board.size() / 2, (int)board.size() / 2};
    }
    auto game_instance = new game::Gomoku(board, turn, moveCount);
    int bestX = -1, bestY = -1;
    eval::score_t bestValue = -INF;
    for (int i = 0; i < game_instance->getSize(); i++)
    {
        for (int j = 0; j < game_instance->getSize(); j++)
        {
            if (game_instance->get(Pos{i, j}) == game::GomokuState::EMPTY && hasNeighbour(game_instance, game::Pos{i, j}, neighbour_radius))
            {
                game_instance->move(game::Pos{i, j});
                logger->debug("Depth left: {}, Evaluating move ({},{})", this->depth, i, j);
                logger->debug("Current board:\n{}", game_instance->getPrintBoardStr());
                eval::score_t value;
                if (game_instance->getWinner() == opponent(game_instance->getTurn()))
                {
                    logger->debug("Found winning move.");
                    return game::Pos{i, j};
                }
                else
                {
                    value = -negamax(game_instance, -INF, INF, evaluator, depth);
                    logger->debug("Value: {}", value);
                }
                game_instance->undo();
                if (value > bestValue)
                {
                    bestValue = value;
                    bestX = i;
                    bestY = j;
                }
            }
        }
    }
    return game::Pos{bestX, bestY};
}

bool NegamaxPlayer::hasNeighbour(game::Gomoku* game_instance, game::Pos pos, int radius){
    for (int i = -radius; i <= radius; i++){
        auto new_x = pos.x + i;
        if (new_x < 0 || new_x >= game_instance->getSize()){
            continue;
        }
        for (int j = -radius; j <= radius; j++){
            auto new_y = pos.y + j;
            if (new_y < 0 || new_y >= game_instance->getSize()){
                continue;
            }
            if (game_instance->get(Pos{new_x, new_y}) != game::GomokuState::EMPTY) {
                return true;
            }
        }
    }
    return false;
}