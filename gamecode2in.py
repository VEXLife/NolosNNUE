# Convert Piskvork game to BOARD command
import argparse

argparser = argparse.ArgumentParser()
argparser.add_argument("game_code", help="Piskvork game to convert")
argparser.add_argument("--output_file", help="Output file name", default="test.in")
args = argparser.parse_args()

game_code = args.game_code
board_command = []

board_command.append("START 15")
board_command.append("BOARD")
turn = 1
code = ""
is_first = True
for char in game_code:
    code += char
    if not char.isdigit() and not is_first:
        board_command.append(f"{ord(code[0]) - ord('a')},{int(code[1:-1]) - 1},{turn}")
        turn = 3 - turn
        code = code[-1]
    is_first = False
board_command.append(f"{ord(code[0]) - ord('a')},{int(code[1:]) - 1},{turn}")
board_command.append("DONE")
with open(args.output_file, "w") as f:
    f.write('\n'.join(board_command))
    f.write('\nEND\n')
