#include "data_collector.h"
#include "../eval/classic.h"
#include "../../cxxopts/include/cxxopts.hpp"

int main(
    int argc,
    char **argv)
{
    cxxopts::Options options("Selfplay Data Collector", "Collect selfplay data for training");
    options.add_options()
        ("s,size", "Board size", cxxopts::value<int>()->default_value("15"))
        ("n,num_games", "Number of games to play", cxxopts::value<int>()->default_value("1"))
        ("o,output_file", "Output file", cxxopts::value<string>()->default_value("output/selfplay_data.csv"))
        ("l,log_file", "Log file", cxxopts::value<string>()->default_value("logs/selfplay.log"))
        ("d,depth", "Depth", cxxopts::value<int>()->default_value("2"))
        ("b,breadth", "Breadth", cxxopts::value<int>()->default_value("3"))
        ("r,radius", "Neighbour radius", cxxopts::value<int>()->default_value("2"))
        ("tt", "Transposition table size", cxxopts::value<size_t>()->default_value("1000000"))
        ("t,temperature", "Temperature", cxxopts::value<float>()->default_value("0.1"))
        ("h,help", "Print usage");

    cxxopts::ParseResult result;
    try{
        result = options.parse(argc, argv);
    }catch(const cxxopts::exceptions::exception& e){
        std::cout << "Error parsing options: " 
        << e.what() 
        << std::endl
        << options.help();
        exit(1);
    }
    if (result.count("help"))
    {
      std::cout << options.help() << std::endl;
      exit(0);
    }
    auto game_instance = new game::Gomoku(result["size"].as<int>());
    auto evaluator = new eval::ClassicEvaluator();
    auto player_black = new selfplay::RandomNegamaxPlayer(
        result["depth"].as<int>(),
        result["breadth"].as<int>(),
        result["radius"].as<int>(),
        evaluator,
        result["temperature"].as<float>(),
        result["transposition_table_size"].as<size_t>(),
        "");
    auto player_white = new selfplay::RandomNegamaxPlayer(
        result["depth"].as<int>(),
        result["breadth"].as<int>(),
        result["radius"].as<int>(),
        evaluator,
        result["temperature"].as<float>(),
        result["transposition_table_size"].as<size_t>(),
        "");
    auto data_collector = new selfplay::DataCollector();
    data_collector->collectData(*game_instance, *player_black, *player_white, 
        result["num_games"].as<int>(), result["output_file"].as<string>(), result["log_file"].as<string>());
    return 0;
}