# Convert Piskvork game to BOARD command
import argparse

argparser = argparse.ArgumentParser()
argparser.add_argument("game", help="Piskvork game to convert")
args = argparser.parse_args()

game = args.game
board_command = []

print(f"Converting Piskvork game {game} to BOARD command")
with open(game, "r") as f:
    info = f.readline() # Piskvorky 15x15, 11:0, 1, convert to START 15
    board_command.append("START " + info.split(",")[0].split()[1].split("x")[0])
    board_command.append("BOARD")
    turn = 1
    while "-1" != (line := f.readline().strip()):
        board_command.append(','.join(line.split(',')[0:2] + [str(turn)]))
        turn = 3 - turn
    board_command.append("DONE")
with open(game.split(".")[0] + ".in", "w") as f:
    f.write('\n'.join(board_command))
    f.write('\n')
