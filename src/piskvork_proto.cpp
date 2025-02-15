#include "piskvork_proto.h"

void piskvorkProtoLoop(agent::Player *player, string logdir)
{
    game::Gomoku *game = nullptr;
    string command;
    std::shared_ptr<spdlog::logger> logger;
    try
    {
        logger = spdlog::basic_logger_mt("basic_logger", logdir + "/piskvork_proto.log");
        logger->flush_on(spdlog::level::info);
    }
    catch (spdlog::spdlog_ex &e)
    {
        cout << "ERROR Log file error: " << e.what() << endl;
        return;
    }

    try
    {
        while (true)
        {
            cin >> command;

            if (command == "START")
            {
                // START [size]
                int size;
                cin >> size;
                logger->info("Got START {}", size);
                if (size < 5)
                {
                    throw std::runtime_error("Invalid size");
                }
                game = new game::Gomoku(size);
                cout << "OK" << endl;
                logger->info("Sent OK");
            }
            else if (command == "TURN")
            {
                // TURN [X],[Y]
                int x, y;
                scanf("%d,%d", &x, &y);
                game::Pos pos = {x, y};
                if (x < 0 || x >= game->getSize() || y < 0 || y >= game->getSize())
                {
                    throw std::runtime_error("Invalid position");
                }
                if (game->get(pos) != game::GomokuState::EMPTY)
                {
                    throw std::runtime_error("Position not empty");
                }
                if (game->getWinner() != game::GomokuState::EMPTY)
                {
                    throw std::runtime_error("Game already has a winner");
                }
                game->move(pos);
                logger->info("Got TURN {},{}", x, y);
                game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
                game->move(agent_move);
                cout << agent_move.x << "," << agent_move.y << endl;
                logger->info("Sent {},{}", agent_move.x, agent_move.y);
                logger->info("CurrentBoard:\n{}", game->getPrintBoardStr());
            }
            else if (command == "BEGIN")
            {
                // BEGIN
                logger->info("Got BEGIN");
                game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
                game->move(agent_move);
                cout << agent_move.x << "," << agent_move.y << endl;
                logger->info("Sent {},{}", agent_move.x, agent_move.y);
                logger->info("CurrentBoard:\n{}", game->getPrintBoardStr());
            }
            else if (command == "BOARD")
            {
                // BOARD
                logger->info("Got BOARD");
                while (true)
                {
                    cin >> command;
                    if (command == "DONE")
                    {
                        break;
                    }
                    int x, y, turn;
                    sscanf(command.c_str(), "%d,%d,%d", &x, &y, &turn);
                    logger->info("Got {},{},{}", x, y, turn);
                    game::Pos pos = {x, y};
                    if (x < 0 || x >= game->getSize() || y < 0 || y >= game->getSize())
                    {
                        throw std::runtime_error("Invalid position");
                    }
                    if (game->get(pos) != game::GomokuState::EMPTY)
                    {
                        throw std::runtime_error("Position not empty");
                    }
                    if (game->getWinner() != game::GomokuState::EMPTY)
                    {
                        throw std::runtime_error("Game already has a winner");
                    }
                    game->move(pos);
                }
                game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
                game->move(agent_move);
                cout << agent_move.x << "," << agent_move.y << endl;
                logger->info("Sent {},{}", agent_move.x, agent_move.y);
                logger->info("CurrentBoard:\n{}", game->getPrintBoardStr());
            }
            else if (command == "RESTART")
            {
                // RESTART
                logger->info("Got RESTART");
                game->reset();
                cout << "OK" << endl;
                logger->info("Sent OK");
            }
            else if (command == "INFO")
            {
                // timeout_turn  - time limit for each move (milliseconds, 0=play as fast as possible)
                // timeout_match - time limit of a whole match (milliseconds, 0=no limit)
                // max_memory    - memory limit (bytes, 0=no limit)
                // time_left     - remaining time limit of a whole match (milliseconds)
                // game_type     - 0=opponent is human, 1=opponent is brain, 2=tournament, 3=network tournament
                // rule          - bitmask or sum of 1=exactly five in a row win, 2=continuous game, 4=renju
                // evaluate      - coordinates X,Y representing current position of the mouse cursor
                // folder        - folder for persistent files
                string key, value;
                cin >> key >> value;
                logger->info("Got INFO {} {}", key, value);
            }
            else if (command == "END")
            {
                // END
                logger->info("Got END");
                logger->info("Quitting...");
                break;
            }
            else if (command == "TAKEBACK")
            {
                // TAKEBACK
                Pos pos;
                scanf("%d,%d", &pos.x, &pos.y);
                logger->info("Got TAKEBACK {},{}", pos.x, pos.y);
                if (game->getMoveCount() == 0)
                {
                    throw std::runtime_error("No moves to take back");
                }
                if (pos == game->getLastMove())
                {
                    game->undo();
                    cout << "OK" << endl;
                    logger->info("Sent OK");
                }
                else
                {
                    logger->warn("The takeback position is not the last move. Fallback to restart.");
                    cout << "UNKNOWN" << endl;
                    logger->info("Sent UNKNOWN");
                }
            }
            else if (command == "ABOUT")
            {
                // ABOUT
                logger->info("Got ABOUT");
                auto player_info = player->getPlayerInfo();
                cout << player_info << endl;
                logger->info("Sent %s", player_info);
            }
            else
            {
                // Unknown command
                logger->warn("Unknown command: {}", command);
                cout << "UNKNOWN" << endl;
                logger->info("Sent UNKNOWN");
            }
        }
    }
    catch (exception &e)
    {
        logger->error("Exception: {}", e.what());
    }
    if (game != nullptr)
    {
        delete game;
        logger->info("Game deleted");
    }
    spdlog::drop_all();
    logger->info("Logger dropped");
}