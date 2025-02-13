#pragma once
#include <vector>

using namespace std;

namespace game {    
    enum class GomokuState {
        EMPTY,
        BLACK,
        WHITE
    };
    
    constexpr GomokuState opponent(GomokuState state) {
        return state == GomokuState::BLACK ? GomokuState::WHITE : GomokuState::BLACK;
    }
    
    struct Pos {
        int x;
        int y;
    };
    
    typedef vector<vector<GomokuState>> Board;

    class Gomoku {
    public:
        Gomoku(int size);
        ~Gomoku();
        void reset();
        void move(Pos);
        void print();
        void undo();
        bool check();
        bool isDone();
        GomokuState get(Pos);
        GomokuState getTurn();
        int getMoveCount();
        GomokuState getWinner();
        Board getBoard();
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