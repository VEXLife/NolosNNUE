#include "gomoku.h"

Gomoku::Gomoku(int size) : size(size)
{
    board = vector<vector<GomokuState>>(size, vector<GomokuState>(size, GomokuState::EMPTY));
    reset();
}

Gomoku::Gomoku(const game::Board &board, const game::GomokuState &turn, const int &moveCount)
    : size((int)board.size()),
      board(board),
      turn(turn),
      moveCount(moveCount) {}

Gomoku::~Gomoku() {}

void Gomoku::reset()
{
    for (int i = 0; i < size; i++)
    {
        for (int j = 0; j < size; j++)
        {
            board[i][j] = GomokuState::EMPTY;
        }
    }
    turn = GomokuState::BLACK;
    moveCount = 0;
    winner = GomokuState::EMPTY;
    history.clear();
}

void Gomoku::move(Pos pos)
{
    if (board[pos.x][pos.y] != GomokuState::EMPTY)
        return;
    board[pos.x][pos.y] = turn;
    history.push_back(pos);
    moveCount++;
    if (check(pos))
    {
        winner = turn;
    }
    turn = opponent(turn);
}

string Gomoku::getPrintBoardStr()
{
    string res = "";
    auto last_move = getLastMove();
    for (int i = 0; i < size; i++)
    {
        for (int j = 0; j < size; j++)
        {
            if (board[i][j] == GomokuState::EMPTY)
            {
                res += ". ";
            }
            else if (board[i][j] == GomokuState::BLACK)
            {
                res += "X";
                if (last_move.x == i && last_move.y == j)
                {
                    res += "<";
                }
                else
                {
                    res += " ";
                }
            }
            else
            {
                res += "O";
                if (last_move.x == i && last_move.y == j)
                {
                    res += "<";
                }
                else
                {
                    res += " ";
                }
            }
        }
        res += "\n";
    }

    res += "Game code: ";
    for (auto &it : history)
    {
        res += it.str();
    }

    return res;
}

void Gomoku::undo()
{
    if (moveCount == 0)
        return;
    Pos pos = history.back();
    board[pos.x][pos.y] = GomokuState::EMPTY;
    history.pop_back();
    moveCount--;
    turn = opponent(turn);
    winner = GomokuState::EMPTY;
}

bool Gomoku::check(Pos pos)
{
    int dx[] = {1, 0, 1, 1};
    int dy[] = {0, 1, 1, -1};
    for (int k = 0; k < 4; k++)
    {
        int count = 1;
        for (int l = 1; l < 5; l++)
        {
            int x = pos.x + dx[k] * l;
            int y = pos.y + dy[k] * l;
            if (x < 0 || x >= size || y < 0 || y >= size)
                break;
            if (board[x][y] != board[pos.x][pos.y])
                break;
            count++;
        }

        for (int l = 1; l < 5; l++)
        {
            int x = pos.x - dx[k] * l;
            int y = pos.y - dy[k] * l;
            if (x < 0 || x >= size || y < 0 || y >= size)
                break;
            if (board[x][y] != board[pos.x][pos.y])
                break;
            count++;
        }
        if (count >= 5)
            return true;
    }
    return false;
}

bool Gomoku::isDone()
{
    return moveCount == size * size || winner != GomokuState::EMPTY;
}
