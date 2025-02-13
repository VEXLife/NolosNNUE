#include "random_player.h"

RandomPlayer::RandomPlayer()
{
    this->player_info = "name=\"Random Player\", version=\"1.0\", author=\"Midden Vexu\", country=\"China\"";
};

RandomPlayer::~RandomPlayer() {}

game::Pos RandomPlayer::getMove(game::Board board, game::GomokuState turn, int moveCount)
{
    game::Pos pos;
    while (true)
    {
        pos.x = rand() % board.size();
        pos.y = rand() % board.size();
        if (board[pos.x][pos.y] == game::GomokuState::EMPTY)
            break;
    }
    return pos;
}