#include "piskvork_proto.h"
#include "agent/player.h"
#include "agent/random_player.h"

int main(int argc, char **argv) {
    agent::Player *player = new agent::RandomPlayer();
    piskvorkProtoLoop(player);
    return 0;
}