import os
import csv
import re
import torch
from torch.utils.data import Dataset, DataLoader
import lightning as L
import itertools

BOARD_SIZE = 15
MOVE_PATTERN = re.compile(r"([a-o])(\d{1,2})", re.IGNORECASE)

def parse_moves(move_str):
    """Convert a1 to (0,0)"""
    moves = []
    for match in MOVE_PATTERN.finditer(move_str):
        col_letter, row_str = match.groups()
        col = ord(col_letter.lower()) - ord('a')
        row = int(row_str) - 1
        moves.append((row, col))
    return moves

def process_game(moves, result):
    """
    Process a game and return a list of samples with rotations and flips.
    """
    samples = []
    board = torch.zeros((BOARD_SIZE, BOARD_SIZE), dtype=torch.float)
    
    # 1 for black, -1 for white, 0 for draw
    if result.lower() == "black":
        winner = 1
    elif result.lower() == "white":
        winner = -1
    else:
        winner = 0

    for i, (row, col) in enumerate(moves):
        piece = 1 if i % 2 == 0 else -1
        next_board = board.clone()
        next_board[row, col] = piece
        if winner == 0 or i < len(moves) - 1:
            label = 0
        else:
            label = 1 if piece == winner else -1
        action = row * BOARD_SIZE + col
        samples.append((board.unsqueeze(0), next_board.unsqueeze(0), torch.FloatTensor([label]), torch.LongTensor([action])))
        board = next_board

    def rotate_coords(row, col, k, board_size):
        for _ in range(k):
            row, col = col, board_size - 1 - row
        return row, col

    def flip_coords(row, col, board_size):
        # flip horizontally
        return row, board_size - 1 - col

    # Augment samples with rotations and flips
    augmented_samples = []
    for board, next_board, label, action in samples:
        original_row = action.item() // BOARD_SIZE
        original_col = action.item() % BOARD_SIZE
        for k in range(4):
            new_row, new_col = rotate_coords(original_row, original_col, k, BOARD_SIZE)
            rotated_board = torch.rot90(board, k, [1, 2])
            rotated_next_board = torch.rot90(next_board, k, [1, 2])
            rotated_action_val = new_row * BOARD_SIZE + new_col
            rotated_action = torch.LongTensor([rotated_action_val])
            augmented_samples.append((rotated_board, rotated_next_board, label, rotated_action))
            
            flip_row, flip_col = flip_coords(new_row, new_col, BOARD_SIZE)
            flipped_board = torch.flip(rotated_board, [2])
            flipped_next_board = torch.flip(rotated_next_board, [2])
            flipped_action_val = flip_row * BOARD_SIZE + flip_col
            flipped_action = torch.LongTensor([flipped_action_val])
            augmented_samples.append((flipped_board, flipped_next_board, label, flipped_action))

    return augmented_samples

def load_dataset(csv_paths):
    data = []
    for csv_path in csv_paths:
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                move_str, result = row[0], row[1]
                moves = parse_moves(move_str)
                samples = process_game(moves, result)
                data.extend(samples)
    return data

class GomokuDataset(Dataset):
    def __init__(self, data):
        self.boards = [item[0] for item in data]
        self.next_boards = [item[1] for item in data]
        self.labels = [item[2] for item in data]
        self.actions = [item[3] for item in data]

    def __len__(self):
        return len(self.boards)

    def __getitem__(self, idx):
        return self.boards[idx], self.next_boards[idx], self.labels[idx], self.actions[idx]

class GomokuDataModule(L.LightningDataModule):
    def __init__(self, csv_paths, batch_size=128, num_workers=4, val_split=0.05):
        super().__init__()
        self.csv_paths = csv_paths
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.val_split = val_split

    def prepare_data(self):
        pass

    def setup(self, stage=None):
        data = load_dataset(self.csv_paths)
        dataset = GomokuDataset(data)
        val_size = int(len(dataset) * self.val_split)
        train_size = len(dataset) - val_size
        self.train_dataset, self.val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])

    def train_dataloader(self):
        return DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
        )

    def val_dataloader(self):
        return DataLoader(
            self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
        )