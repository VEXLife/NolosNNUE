#include <vector>
#include <cmath>
#include "classic.h"

// Define an auxiliary function to detect chess patterns in a given direction
int ClassicEvaluator::checkDirection(const Board &board, int x, int y, int dx, int dy, const GomokuState &turn)
{
    int count = 1;
    int empty_count = 0;
    int jump_count = 0;
    int i;

    // Detect chess patterns in the current direction
    for (i = 1; i < 5; i++)
    {
        int nx = x + dx * i;
        int ny = y + dy * i;

        if (nx < 0 || nx >= board.size() || ny < 0 || ny >= board[0].size())
        {
            // Out of bounds
            break;
        }

        if (board[nx][ny] == board[x][y])
        {
            count++;
            jump_count += empty_count;
            empty_count = 0;
        }
        else if (board[nx][ny] == GomokuState::EMPTY)
        {
            empty_count++;
            if (empty_count >= 2)
            {
                break;
            }
        }
        else
        {
            // Encounter the opponent's chess piece
            break;
        }
    }
    auto oppo_empty_count = 0;
    for (int j = 1; j <= 6 - i; j++)
    {
        int nx = x - dx * j;
        int ny = y - dy * j;
        if (nx < 0 || nx >= board.size() || ny < 0 || ny >= board[0].size())
        {
            // Out of bounds
            break;
        }
        if (board[nx][ny] == board[x][y])
        {
            // A replicate
            return 0;
        }
        else if (board[nx][ny] == GomokuState::EMPTY)
        {
            oppo_empty_count++;
            if (oppo_empty_count >= 2)
            {
                break;
            }
        }
        else
        {
            // Encounter the opponent's chess piece
            break;
        }
    }
    empty_count += oppo_empty_count;

    // Check the pattern and return the corresponding score
    auto is_my_turn = (board[x][y] == turn);
    if (count == 4 && empty_count == 2)
        return is_my_turn ? ME_FOUR_STRAIGHT : OPPO_FOUR_STRAIGHT;
    else if (count == 4 && empty_count + jump_count >= 1)
        return is_my_turn ? ME_FOUR_SLEEP : OPPO_FOUR_SLEEP;
    else if (count == 3 && jump_count == 0 && empty_count >= 3)
        return is_my_turn ? ME_THREE_STRAIGHT : OPPO_THREE_STRAIGHT;
    else if (count == 3 && jump_count >= 1 && empty_count >= 2)
        return is_my_turn ? ME_THREE_JUMP : OPPO_THREE_JUMP;
    else if (count == 3 && empty_count + jump_count >= 2)
        return is_my_turn ? ME_THREE_SLEEP : OPPO_THREE_SLEEP;
    else if (count == 2 && jump_count == 0 && empty_count >= 4)
        return is_my_turn ? ME_TWO_STRAIGHT : OPPO_TWO_STRAIGHT;
    else if (count == 2 && jump_count >= 1 && empty_count + jump_count >= 3)
        return is_my_turn ? ME_TWO_JUMP : OPPO_TWO_JUMP;
    else
        return 0;
}

// Define a function to evaluate the entire board
score_t ClassicEvaluator::evaluate(const Board &board, const GomokuState &turn)
{
    int score = 0;
    int n = (int)board.size();
    auto opponent = game::opponent(turn);

    // Traverse every position on the board
    for (int i = 0; i < n; i++)
    {
        for (int j = 0; j < n; j++)
        {
            if (board[i][j] != GomokuState::EMPTY)
            {
                // Detect all possible directions
                score += checkDirection(board, i, j, 1, 0, turn);  // Horizontal direction
                score += checkDirection(board, i, j, 0, 1, turn);  // Vertical direction
                score += checkDirection(board, i, j, 1, 1, turn);  // Diagonal direction (bottom right)
                score += checkDirection(board, i, j, 1, -1, turn); // Diagonal direction (top right)
            }
        }
    }

    return (score_t)score;
}
