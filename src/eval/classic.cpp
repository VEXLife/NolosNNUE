#include "classic.h"

double ClassicEvaluator::evaluate(const Board &board, const GomokuState &turn)
{
    double score = 0;
    for (int i = 0; i < board.size(); i++)
    {
        for (int j = 0; j < board.size(); j++)
        {
            if (board[i][j] == GomokuState::EMPTY)
                continue;
            auto pos = Pos{i, j};
            score += evaluateLine(board, pos, 1, 0, turn);
            score += evaluateLine(board, pos, 0, 1, turn);
            score += evaluateLine(board, pos, 1, 1, turn);
            score += evaluateLine(board, pos, 1, -1, turn);
        }
    }
    return score;
}

int ClassicEvaluator::countConsecutiveStones(const Board &board, const Pos &pos, int dx, int dy, const GomokuState &turn) const
{
    int count = 0;
    Pos p = pos;
    while (p.x >= 0 && p.x < board.size() && p.y >= 0 && p.y < board.size() && board[p.x][p.y] == turn)
    {
        count++;
        p.x += dx;
        p.y += dy;
    }
    return count;
}

double ClassicEvaluator::evaluateLine(const Board &board, const Pos &pos, int dx, int dy, const GomokuState &turn) const
{
    double score = 0;
    int count = 0;
    Pos p = pos;
    while (p.x >= 0 && p.x < board.size() && p.y >= 0 && p.y < board.size() && board[p.x][p.y] == turn)
    {
        count++;
        p.x += dx;
        p.y += dy;
    }
    if (count >= 5)
        return 1000000;
    if (count == 4)
        return 10000;
    if (count == 3)
        return 1000;
    if (count == 2)
        return 100;
    if (count == 1)
        return 10;
    return 0;
}