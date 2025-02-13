#include "piskvork_proto.h"

void piskvorkProtoLoop(agent::Player *player)
{
    game::Gomoku *game;
    string command;

    while (true)
    {
        cin >> command;

        if (command == "START")
        {
            // START [size]
            int size;
            cin >> size;
            game = new game::Gomoku(size);
            cout << "OK" << endl;
        }
        else if (command == "TURN")
        {
            // TURN [X],[Y]
            int x, y;
            scanf("%d,%d", &x, &y);
            game::Pos pos = {x, y};
            game->move(pos);
            game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
            game->move(agent_move);
            cout << agent_move.x << "," << agent_move.y << endl;
        }
        else if (command == "BEGIN")
        {
            game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
            game->move(agent_move);
            cout << agent_move.x << "," << agent_move.y << endl;
        }
        else if (command == "BOARD")
        {
            // BOARD
            while (command != "DONE")
            {
                int x, y, turn;
                scanf("%d,%d,%d", &x, &y, &turn);
                game::Pos pos = {x, y};
                game->move(pos);
            }
            game::Pos agent_move = player->getMove(game->getBoard(), game->getTurn(), game->getMoveCount());
            game->move(agent_move);
            cout << agent_move.x << "," << agent_move.y << endl;
        }
        else if (command == "RESTART")
        {
            // RESTART
            game->reset();
            cout << "OK" << endl;
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
        }
        else if (command == "END")
        {
            // END
            break;
        }
        else if (command == "ABOUT")
        {
            // ABOUT
            cout << player->getPlayerInfo() << endl;
        }
        else
        {
            // Unknown command
            cout << command << endl;
            cout << "UNKNOWN" << endl;
        }
    }
}