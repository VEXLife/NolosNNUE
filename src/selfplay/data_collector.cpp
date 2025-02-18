#include "data_collector.h"

void DataCollector::collectData(
    game::Gomoku &game_instance,
    Player &player_black,
    Player &player_white,
    int num_games,
    string output_file,
    string log_file)
{
    std::shared_ptr<spdlog::logger> logger;
    try
    {
        logger = spdlog::basic_logger_mt("basic_logger", log_file);
        logger->flush_on(spdlog::level::info);
    }
    catch (spdlog::spdlog_ex &e)
    {
        cout << "ERROR Log file error: " << e.what() << endl;
        return;
    }

    // Write CSV header
    std::ofstream file(output_file);
    file << "game_code, result" << std::endl;

    for (int i = 0; i < num_games; i++)
    {
        // Reset game
        game_instance.reset();
        
        while (game_instance.isDone() == false)
        {
            auto player = game_instance.getTurn() == game::GomokuState::BLACK ? &player_black : &player_white;
            auto move = player->getMove(game_instance.getBoard(), game_instance.getTurn(), game_instance.getMoveCount());
            game_instance.move(move);
            logger->info("Game {}, Current board:\n{}", i, game_instance.getPrintBoardStr(true));
        }

        // Write game result to CSV
        file << game_instance.getGameCode()
             << ","
             << (game_instance.getWinner() == game::GomokuState::BLACK   ? "black"
                 : game_instance.getWinner() == game::GomokuState::WHITE ? "white"
                                                                         : "draw")
             << std::endl;

        if (i % 100 == 0)
        {
            file.flush();
        }
    }

    file.close();
}