from player import Player
from game import Gomoku
from model.td3bc import LitTD3BC
import torch
import torch.nn.functional as F
from einops import rearrange


class NolosPlayer(Player):
    def __init__(self,*args,**kwargs) -> None:
        super().__init__(*args)
        lit_model = LitTD3BC.load_from_checkpoint("../logs/run/lit_convnet/version_0/checkpoints/epoch=6-step=13013.ckpt")
        self.model=lit_model.actor
        self.model.eval()

    def get_action(self,state: Gomoku):
        board = torch.zeros(1, 1, 15, 15)
        for i in range(15):
            for j in range(15):
                board[0, 0, i, j] = 1 if state.board[i][j] == state.player else 0 if state.board[i][j] == 0 else -1
        valid_moves = state.get_valid_moves()
        # values = torch.zeros(15,15)

        # for i in range(15):
        #     for j in range(15):
        #         if valid_moves[i][j]:
        #             values[i, j] = self.model(board, F.one_hot(torch.LongTensor([i * 15 + j]), num_classes=225)).item()
        #         else:
        #             values[i, j] = -float('inf')

        # best_move = torch.argmax(values)
        # return best_move//15,best_move%15

        with torch.no_grad():
            action = self.model(board)
            action[rearrange(valid_moves, "m n -> 1 (m n)")==0]=-float('inf')
            action = torch.argmax(action)
        return action//15,action%15
    