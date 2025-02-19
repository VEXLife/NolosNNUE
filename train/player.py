from abc import abstractmethod
from typing import Tuple
from game import Gomoku

class Player:
    def __init__(self) -> None:
        pass

    @abstractmethod
    def get_action(self, state: Gomoku) -> Tuple[int, int]:
        raise NotImplementedError()
    
    @abstractmethod
    def update_with_move(self, last_move: Tuple[int, int]):
        pass
    
    @abstractmethod
    def reset(self):
        pass