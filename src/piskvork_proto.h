#pragma once

#include <iostream>
#include <string>
#include "agent/player.h"
#include "spdlog/sinks/basic_file_sink.h"
#include "spdlog/spdlog.h"

using namespace std;

void piskvorkProtoLoop(agent::Player *player, string logdir = "logs/");