# NolosNNUE

NolosNNUE是一个完整的中国象棋AI引擎实现，支持MiniMax搜索、Alpha-Beta剪枝、空步裁剪、手动评估和NNUE评估等功能，并遵循UCCI协议与棋类界面通信。

## 项目结构

- **include/**: 头文件目录
  - `chessboard.h`: 定义棋盘类和基本操作
  - `evaluator.h`: 定义评估器基类和具体实现
  - `search.h`: 定义搜索算法
  - `ucci.h`: 定义UCCI协议处理

- **src/**: 源代码目录
  - `chessboard.cpp`: 棋盘类实现
  - `evaluator.cpp`: 评估器实现
  - `search.cpp`: 搜索算法实现
  - `ucci.cpp`: UCCI协议处理实现
  - `main.cpp`: 引擎入口点

- **python/**: Python脚本目录
  - `train_nnue.py`: NNUE网络训练脚本

## 功能特性

1. **棋盘表示与操作**
   - 10x9的中国象棋棋盘表示
   - FEN串解析与生成
   - 棋子移动规则验证
   - 将军、将死检测

2. **搜索算法**
   - MiniMax搜索
   - Alpha-Beta剪枝
   - 空步裁剪
   - 迭代加深
   - 静态搜索

3. **评估函数**
   - 手动评估（基于棋子价值和位置价值）
   - NNUE评估（基于神经网络）

4. **UCCI协议支持**
   - 完整实现UCCI协议命令
   - 支持与标准中国象棋界面通信

## 构建指南

### 前提条件
- CMake 3.15+ 
- C++23兼容的编译器
- ONNX Runtime库
- Python 3.8+（用于训练NNUE）

### 构建步骤

1. 克隆仓库
2. 配置CMake
   ```
   mkdir build
   cd build
   cmake ..
   ```
3. 编译项目
   ```
   cmake --build .
   ```

## 使用方法

### 作为棋类引擎
1. 编译完成后，将生成的可执行文件与`onnxruntime.dll`和`model.onnx`放在同一目录下
2. 在支持UCCI协议的中国象棋界面中加载引擎

### 使用调试工具
项目提供了一个Python调试工具，可以从输入文件中读取UCCI命令并传递给引擎：

1. 准备包含UCCI命令的输入文件（示例文件：`example_ucci_commands.txt`）
2. 运行调试工具
   ```
   python debug_ucci.py <输入文件路径>
   ```

示例：
```
python debug_ucci.py example_ucci_commands.txt
```

### 训练NNUE网络
1. 安装所需Python依赖
   ```
   pip install torch numpy
   ```
2. 运行训练脚本
   ```
   python python/train_nnue.py
   ```
3. 训练完成后会生成`model.onnx`文件，将其复制到引擎目录

## 注意事项
- NNUE模型需要先训练才能使用
- 引擎支持通过UCCI命令设置搜索深度、时间限制等参数
- 可通过修改代码调整评估函数权重和搜索参数以获得更好的性能