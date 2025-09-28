import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import chess
import chess.pgn
import os
import random
from concurrent.futures import ProcessPoolExecutor

# 中国象棋棋子类型映射
PIECE_TYPES = {
    0: 'empty',
    1: 'red_king',
    2: 'red_advisor',
    3: 'red_elephant',
    4: 'red_horse',
    5: 'red_chariot',
    6: 'red_cannon',
    7: 'red_pawn',
    8: 'black_king',
    9: 'black_advisor',
    10: 'black_elephant',
    11: 'black_horse',
    12: 'black_chariot',
    13: 'black_cannon',
    14: 'black_pawn'
}

# 反向映射
PIECE_CODES = {v: k for k, v in PIECE_TYPES.items()}

class NNUE(nn.Module):
    def __init__(self):
        super(NNUE, self).__init__()
        # 输入层：10x9棋盘，每个位置有14种可能的棋子类型
        self.input_size = 10 * 9 * 14  # 10行，9列，14种棋子类型（包括空）
        self.hidden_size1 = 128
        self.hidden_size2 = 64
        self.output_size = 1  # 输出一个评分
        
        # 权重层
        self.fc1 = nn.Linear(self.input_size, self.hidden_size1)
        self.fc2 = nn.Linear(self.hidden_size1, self.hidden_size2)
        self.fc3 = nn.Linear(self.hidden_size2, self.output_size)
        
        # 激活函数
        self.relu = nn.ReLU()
        
        # 初始化权重
        nn.init.kaiming_normal_(self.fc1.weight)
        nn.init.kaiming_normal_(self.fc2.weight)
        nn.init.kaiming_normal_(self.fc3.weight)
    
    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        x = self.fc3(x)
        return x

# 将棋盘状态转换为神经网络输入格式
def board_to_input(board):
    # 创建一个10x9x14的输入张量，初始化为0
    input_tensor = np.zeros((10, 9, 14), dtype=np.float32)
    
    for i in range(10):
        for j in range(9):
            piece = board[i][j]
            if piece > 0:
                # 将棋子位置设置为1
                input_tensor[i][j][piece] = 1.0
    
    # 展平为一维向量
    return input_tensor.flatten()

# 生成训练数据
def generate_training_data(num_samples=10000):
    training_data = []
    
    # 这里只是一个简单的示例，实际应用中应该从PGN文件或自对弈中生成高质量数据
    for _ in range(num_samples):
        # 创建一个随机的棋盘状态（简化版）
        board = np.zeros((10, 9), dtype=np.int32)
        
        # 随机放置一些棋子（简化版）
        for i in range(10):
            for j in range(9):
                if random.random() < 0.2:  # 20%的概率有棋子
                    piece_type = random.randint(1, 14)
                    board[i][j] = piece_type
        
        # 生成一个随机的评分（范围从-1000到1000）
        score = random.randint(-1000, 1000)
        
        # 转换为神经网络输入格式
        input_data = board_to_input(board)
        
        # 添加到训练数据
        training_data.append((input_data, score))
    
    return training_data

# 并行生成训练数据
def parallel_generate_training_data(num_samples=10000, num_workers=4):
    samples_per_worker = num_samples // num_workers
    training_data = []
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(generate_training_data, samples_per_worker) for _ in range(num_workers)]
        
        for future in futures:
            training_data.extend(future.result())
    
    return training_data

# 训练神经网络
def train_nnue(training_data, batch_size=64, epochs=50, learning_rate=0.001):
    # 创建模型
    model = NNUE()
    
    # 定义损失函数和优化器
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    
    # 准备数据
    inputs = torch.tensor([data[0] for data in training_data], dtype=torch.float32)
    targets = torch.tensor([data[1] for data in training_data], dtype=torch.float32).view(-1, 1)
    
    # 划分训练集和验证集
    train_size = int(0.8 * len(training_data))
    train_inputs, val_inputs = inputs[:train_size], inputs[train_size:]
    train_targets, val_targets = targets[:train_size], targets[train_size:]
    
    # 开始训练
    for epoch in range(epochs):
        # 打乱训练数据
        indices = torch.randperm(train_size)
        train_inputs = train_inputs[indices]
        train_targets = train_targets[indices]
        
        # 分批次训练
        running_loss = 0.0
        
        for i in range(0, train_size, batch_size):
            # 获取当前批次
            batch_inputs = train_inputs[i:i+batch_size]
            batch_targets = train_targets[i:i+batch_size]
            
            # 清零梯度
            optimizer.zero_grad()
            
            # 前向传播
            outputs = model(batch_inputs)
            loss = criterion(outputs, batch_targets)
            
            # 反向传播和优化
            loss.backward()
            optimizer.step()
            
            # 累计损失
            running_loss += loss.item()
        
        # 计算验证损失
        with torch.no_grad():
            val_outputs = model(val_inputs)
            val_loss = criterion(val_outputs, val_targets)
        
        # 打印训练进度
        print(f'Epoch {epoch+1}/{epochs}, Train Loss: {running_loss/train_size:.4f}, Val Loss: {val_loss.item():.4f}')
    
    return model

# 将模型转换为ONNX格式
def export_to_onnx(model, output_path='model.onnx'):
    # 创建一个示例输入
    dummy_input = torch.randn(1, model.input_size)
    
    # 导出模型
    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=11,
        do_constant_folding=True,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    
    print(f'Model exported to {output_path}')

# 主函数
if __name__ == '__main__':
    print("Generating training data...")
    training_data = parallel_generate_training_data(num_samples=50000, num_workers=4)
    print(f"Generated {len(training_data)} training samples")
    
    print("Training NNUE model...")
    model = train_nnue(training_data, batch_size=64, epochs=50, learning_rate=0.001)
    
    print("Exporting model to ONNX format...")
    export_to_onnx(model)
    
    print("Training completed!")