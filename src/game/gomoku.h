#pragma once
#include <vector>
#include <string>

using namespace std;

namespace game
{
    enum class GomokuState
    {
        EMPTY,
        BLACK,
        WHITE
    };

    constexpr GomokuState opponent(GomokuState state)
    {
        return state == GomokuState::BLACK ? GomokuState::WHITE : GomokuState::BLACK;
    }

    struct Pos
    {
        int x;
        int y;

        bool operator==(const Pos &other) const
        {
            return x == other.x && y == other.y;
        }
    };

    typedef vector<vector<GomokuState>> Board;

    class Gomoku
    {
    public:
        Gomoku(int size);
        ~Gomoku();
        void reset();
        void move(Pos);
        void undo();
        bool check();
        bool isDone();
        string Gomoku::getPrintBoardStr();

        GomokuState Gomoku::get(Pos pos) {
            return board[pos.x][pos.y];
        }
        
        GomokuState Gomoku::getTurn() {
            return turn;
        }
        
        int Gomoku::getMoveCount() {
            return moveCount;
        }
        
        GomokuState Gomoku::getWinner() {
            return winner;
        }
        
        vector<vector<GomokuState>> Gomoku::getBoard() {
            return board;
        }

        int getSize() {
            return size;
        }

        Pos getLastMove() {
            return history.back();
        }

    private:
        Board board;
        int size;
        GomokuState turn;
        int moveCount;
        GomokuState winner;
        vector<Pos> history;
    };
}

using namespace game;