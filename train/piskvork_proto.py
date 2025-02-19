# Implements the protocol for Piskvork.

import sys
import time
from nolos_player import NolosPlayer
from game import Gomoku

ABOUT_STRING="name=\"NolosNNUEPy\", version=\"0.1\", author=\"Midden Vexu\", country=\"China\""

game=Gomoku()
f=open(f"../logs/nolos_{time.time()}.log","w")

def log_to_file(_str:str):
    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S',time.localtime())}] {_str}\n")
    f.flush()

def log_board():
    log_to_file("Current board: "+str(game))
    log_to_file("Current player: "+('X' if game.player==2 else 'O'))
    log_to_file("Winner: "+('X' if game.winner==2 else 'O' if game.winner==1 else 'Draw' if game.winner==0 else 'None'))

def print_to_std(_str:str):
    log_to_file(f"NoloZero: {_str}")
    print(_str)
    sys.stdout.flush()

def debug(_str:str):
    print_to_std(f"DEBUG {_str}")

agent=NolosPlayer(debug_callback=debug)

def about():
    print_to_std(ABOUT_STRING)

def start(size:int):
    if size == 15:
        print_to_std("OK")
    else:
        print_to_std("ERROR unsupported board size!")

def turn(x:int, y:int):
    game.play(x,y)
    agent.update_with_move((x,y))

    ai_x,ai_y=agent.get_action(game)
    print_to_std(f"{ai_x},{ai_y}")
    game.play(ai_x,ai_y)
    agent.update_with_move((ai_x,ai_y))

    log_board()

def end():
    f.close()
    sys.exit(0)

def begin():
    ai_x,ai_y=agent.get_action(game)
    print_to_std(f"{ai_x},{ai_y}")
    game.play(ai_x,ai_y,False)
    agent.update_with_move((ai_x,ai_y))

    log_board()

def info(key:str,value:str):
    pass

def board():
    game.reset()
    line=input()
    while line!="DONE":
        x,y,_=map(int,line.split(','))
        game.play(x,y,False)
        line=input()
    
    ai_x,ai_y=agent.get_action(game)
    print_to_std(f"{ai_x},{ai_y}")
    game.play(ai_x,ai_y)
    agent.update_with_move((ai_x,ai_y))

    log_board()

def restart():
    game.reset()
    agent.reset()
    print_to_std("OK")

def takeback(x:int,y:int):
    game.takeback(x,y)
    agent.reset()
    print_to_std("OK")

def main():
    while True:
        line=input()
        log_to_file(f"Piskvork: {line}")
        commands=line.split(' ')
        command=commands[0].upper()
        if command=="ABOUT":
            about()
        elif command=="START":
            size=int(commands[1])
            start(size)
        elif command=="TURN":
            x,y=map(int,commands[1].split(','))
            turn(x,y)
        elif command=="TAKEBACK":
            x,y=map(int,commands[1].split(','))
            takeback(x,y)
        elif command=="END":
            end()
        elif command=="BEGIN":
            begin()
        elif command=="RESTART":
            restart()
        elif command=="BOARD":
            board()
        elif command=="INFO":
            key,value=commands[1],commands[2]
            info(key,value)
        else:
            print_to_std("UNKNOWN")

if __name__=="__main__":
    main()
