# Implements a gomoku game

from typing import Tuple
import numpy as np


class Gomoku:
    def __init__(self):
        self.board = np.empty((15, 15), dtype=np.int8)
        self.available_moves = np.empty((15, 15), dtype=np.int8)
        self.reset()

    def reset(self):
        self.board[:] = 0
        self.player = 2  # 2 for black (move first), 1 for white
        self.winner = -1  # -1 for not finished, 0 for draw, 1 for white, 2 for black
        self.available_moves[:] = 0

    def get_valid_moves(self):
        threat_space, has_threat = self.get_threat_space()
        if has_threat:
            return threat_space
        if np.count_nonzero(self.board) == 0:
            self.available_moves+=1
        return np.logical_and(self.available_moves > 0, self.board == 0)

    def play(self, x, y, check_win=True):
        self.board[x, y] = self.player
        if np.count_nonzero(self.board) == 225:
            self.winner = 0
        if check_win and self.is_win(x, y):
            self.winner = self.player
        self.update_available_moves(x, y, 1)
        self.player = 1 if self.player == 2 else 2

    def is_win(self, x, y):
        directions = [[0, 1], [1, 0], [1, 1], [1, -1]]
        for direction in directions:
            connects = 0
            for i in range(0, 5):
                x1 = x+i*direction[0]
                y1 = y+i*direction[1]
                if x1 < 0 or x1 >= 15 or y1 < 0 or y1 >= 15:
                    break
                if self.board[x1, y1] == self.player:
                    connects += 1
                else:
                    break
            for i in range(1, 5):
                x1 = x-i*direction[0]
                y1 = y-i*direction[1]
                if x1 < 0 or x1 >= 15 or y1 < 0 or y1 >= 15:
                    break
                if self.board[x1, y1] == self.player:
                    connects += 1
                else:
                    break
            if connects >= 5:
                return True
        return False

    def takeback(self, x, y):
        self.board[x, y] = 0
        self.update_available_moves(x, y, -1)
        self.player = 1 if self.player == 2 else 2

    def update_available_moves(self, x, y, value):
        self.available_moves[
            max(0, x-2):min(15, x+3),
            max(0, y-2):min(15, y+3)
        ] += value

    def get_threat_space(self) -> Tuple[np.ndarray, bool]:
        threat_space = np.zeros((15, 15), dtype=np.int8)
        has_threat = False
        directions = [[1, 0], [0, 1], [1, 1], [1, -1]]
        for x in range(15):
            for y in range(15):
                if x > 11 and y > 11:
                    break
                if self.board[x, y] != 0:
                    for direction in directions:
                        pattern = ''
                        for i in range(5):
                            x1 = x+i*direction[0]
                            y1 = y+i*direction[1]
                            if x1 < 0 or x1 >= 15 or y1 < 0 or y1 >= 15:
                                pattern += '2'
                                break
                            if self.board[x1, y1] == 0:
                                if pattern[-1] == '0':
                                    break  # Break when find continuous 0s
                                pattern += '0'
                            elif self.board[x1, y1] != self.board[x, y]:
                                pattern += '2'  # 2 for opponent's stone
                                break
                            else:
                                pattern += '1'  # 1 for self's stone
                        prev1_x = x-direction[0]
                        prev1_y = y-direction[1]
                        if prev1_x < 0 or prev1_x >= 15 or prev1_y < 0 or prev1_y >= 15:
                            prev1_stone = None
                        else:
                            prev1_stone = self.board[prev1_x, prev1_y]
                        if pattern == '11112' and prev1_stone == 0:
                            has_threat = True
                            threat_space[prev1_x, prev1_y] = 1
                        elif pattern == '11110':
                            has_threat = True
                            threat_space[x+direction[0]
                                         * 4, y+direction[1]*4] = 1
                            if prev1_stone == 0:
                                threat_space[prev1_x, prev1_y] = 1
                        elif pattern == '10111':
                            has_threat = True
                            threat_space[x+direction[0], y+direction[1]] = 1
                        elif pattern == '11011':
                            has_threat = True
                            threat_space[x+direction[0]
                                         * 2, y+direction[1]*2] = 1
                        elif pattern == '11101':
                            has_threat = True
                            threat_space[x+direction[0]
                                         * 3, y+direction[1]*3] = 1
        if has_threat:
            return threat_space, has_threat
        for x in range(15):
            for y in range(15):
                if x > 11 and y > 11:
                    break
                if self.board[x, y] != 0:
                    for direction in directions:
                        pattern = ''
                        for i in range(5):
                            x1 = x+i*direction[0]
                            y1 = y+i*direction[1]
                            if x1 < 0 or x1 >= 15 or y1 < 0 or y1 >= 15:
                                pattern += '2'
                                break
                            if self.board[x1, y1] == 0:
                                pattern += '0'
                            elif self.board[x1, y1] != self.board[x, y]:
                                pattern += '2'  # 2 for opponent's stone
                                break
                            else:
                                pattern += '1'  # 1 for self's stone
                        prev1_x = x-direction[0]
                        prev1_y = y-direction[1]
                        if prev1_x < 0 or prev1_x >= 15 or prev1_y < 0 or prev1_y >= 15:
                            prev1_stone = None
                        else:
                            prev1_stone = self.board[prev1_x, prev1_y]
                        prev2_x = x-2*direction[0]
                        prev2_y = y-2*direction[1]
                        if prev2_x < 0 or prev2_x >= 15 or prev2_y < 0 or prev2_y >= 15:
                            prev2_stone = None
                        else:
                            prev2_stone = self.board[prev2_x, prev2_y]
                        if pattern == '11100':
                            if prev1_stone == 0:
                                has_threat = True
                                threat_space[prev1_x, prev1_y] = 1
                            else:
                                threat_space[x+direction[0]
                                            * 4, y+direction[1]*4] = 1
                            threat_space[x+direction[0]
                                         * 3, y+direction[1]*3] = 1
                        elif pattern == '1112':
                            if prev1_stone == 0:
                                threat_space[prev1_x, prev1_y] = 1
                                if prev2_stone == 0:
                                    threat_space[prev2_x, prev2_y] = 1
                        elif pattern == '11102' and prev1_stone == 0 and prev2_stone == 0:
                            has_threat = True
                            threat_space[prev1_x, prev1_y] = 1
                            threat_space[prev2_x, prev2_y] = 1
                            threat_space[x+direction[0]
                                         * 3, y+direction[1]*3] = 1
                        elif pattern == '11010':
                            if prev1_stone == 0:
                                has_threat = True
                                threat_space[prev1_x, prev1_y] = 1
                            threat_space[x+direction[0]
                                         * 2, y+direction[1]*2] = 1
                            threat_space[x+direction[0]
                                         * 4, y+direction[1]*4] = 1
                        elif pattern == '11001':
                            threat_space[x+direction[0]
                                         * 2, y+direction[1]*2] = 1
                            threat_space[x+direction[0]
                                         * 3, y+direction[1]*3] = 1
                        elif pattern == '10110':
                            if prev1_stone == 0:
                                has_threat = True
                                threat_space[prev1_x, prev1_y] = 1
                            threat_space[x+direction[0]
                                         * 1, y+direction[1]*1] = 1
                            threat_space[x+direction[0]
                                         * 4, y+direction[1]*4] = 1
                        elif pattern == '10112' and prev1_stone == 0:
                            threat_space[prev1_x, prev1_y] = 1
                            threat_space[x+direction[0]*1, y+direction[1]*1] = 1
                        elif pattern == '10101':
                            threat_space[x+direction[0]
                                         * 1, y+direction[1]*1] = 1
                            threat_space[x+direction[0]
                                         * 3, y+direction[1]*3] = 1
                        elif pattern == '10011':
                            threat_space[x+direction[0]
                                         * 1, y+direction[1]*1] = 1
                            threat_space[x+direction[0]
                                         * 2, y+direction[1]*2] = 1
        return threat_space, has_threat

    def __str__(self) -> str:
        return self.__repr__()
    
    def __repr__(self) -> str:
        board_str="\n  "
        threat_space, has_threat = self.get_threat_space()
        
        for i in range(1,16):
            board_str+='{:2} '.format(i)
        for i in range(15):
            board_str+="\n{:2} ".format(i+1)
            for j in range(15):
                # Because the board in Piskvork is transposed
                if self.board[j,i]==2:
                    board_str+='X'
                elif self.board[j,i]==1:
                    board_str+='O'
                elif threat_space[j,i]==1:
                    board_str+='*'
                elif not has_threat and self.available_moves[j,i]>0:
                    board_str+='.'
                else:
                    board_str+=' '
                board_str+='  '
        return board_str
