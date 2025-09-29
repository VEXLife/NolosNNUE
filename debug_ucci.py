import subprocess
import sys
import os
import time
import threading
import queue


def read_output(process, output_queue):
    """
    在单独的线程中读取进程的输出
    """
    try:
        while True:
            # 读取一行输出
            line = process.stdout.readline()
            if not line:
                break  # 进程已关闭输出流
            
            # 将输出放入队列
            output_queue.put(line)
    except Exception as e:
        # 忽略读取错误
        pass
    finally:
        # 标记输出结束
        output_queue.put(None)


def main():
    """
    UCCI引擎调试工具
    运行方式: python debug_ucci.py <输入文件路径>
    功能: 读取包含UCCI命令的文件，将命令传递给NolosNNUE.exe引擎，并显示输出
    """
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python debug_ucci.py <输入文件路径>")
        return 1
    
    input_file_path = sys.argv[1]
    
    # 检查输入文件是否存在
    if not os.path.exists(input_file_path):
        print(f"错误: 找不到输入文件 '{input_file_path}'")
        return 1
    
    # 查找NolosNNUE.exe文件
    exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NolosNNUE.exe")
    if not os.path.exists(exe_path):
        print(f"错误: 找不到可执行文件 '{exe_path}'")
        return 1
    
    try:
        # 启动NolosNNUE.exe进程
        process = subprocess.Popen(
            [exe_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        print(f"已启动引擎: {exe_path}")
        print(f"正在读取输入文件: {input_file_path}")
        
        # 创建输出队列和读取线程
        output_queue = queue.Queue()
        read_thread = threading.Thread(target=read_output, args=(process, output_queue))
        read_thread.daemon = True  # 设置为守护线程，主线程结束时自动终止
        read_thread.start()
        
        # 读取输入文件中的命令
        with open(input_file_path, 'r', encoding='utf-8') as f:
            commands = f.readlines()
        
        # 向引擎发送命令并显示响应
        for command_idx, command in enumerate(commands):
            # 去除行首尾的空白字符
            cmd = command.strip()
            if not cmd or cmd.startswith('#'):
                continue  # 跳过空行和注释行
            
            print(f"\n发送命令: {cmd}")
            
            # 发送命令到引擎
            process.stdin.write(cmd + '\n')
            process.stdin.flush()
            
            # 读取并显示引擎的响应
            response_received = False
            command_processed = False
            start_time = time.time()
            
            # 设置超时时间（秒）
            timeout = 10 if cmd.lower().startswith('go') else 5
            
            while time.time() - start_time < timeout and not command_processed:
                try:
                    # 尝试从队列中获取输出，设置超时
                    try:
                        line = output_queue.get(timeout=0.1)  # 100ms超时
                        
                        if line is None:
                            # 输出结束标记
                            print("警告: 引擎输出流已关闭")
                            break
                        
                        # 处理输出行
                        print(f"引擎响应: {line.strip()}")
                        response_received = True
                        
                        # 根据不同命令设置不同的结束条件
                        if cmd.lower() == 'ucci' and line.strip() == 'ucciok':
                            command_processed = True
                        elif cmd.lower() == 'isready' and line.strip() == 'readyok':
                            command_processed = True
                        elif line.strip().startswith('bestmove'):
                            command_processed = True
                        elif line.strip().startswith('nobestmove'):
                            command_processed = True
                        elif cmd.lower() == 'quit' and line.strip() == 'bye':
                            command_processed = True
                    except queue.Empty:
                        # 队列为空，继续等待
                        pass
                    
                    # 检查进程是否已终止
                    if process.poll() is not None:
                        print(f"警告: 引擎进程已终止，退出代码: {process.returncode}")
                        break
                except KeyboardInterrupt:
                    # 用户中断，退出循环
                    print("用户中断")
                    break
                except Exception as e:
                    # 忽略其他错误
                    print(f"处理输出时出错: {str(e)}")
                    break
            
            # 对于position命令，不显示未收到响应和处理超时的警告，因为这是UCCI协议的正常行为
            if not response_received and not cmd.lower().startswith('position'):
                print(f"警告: 未收到引擎对命令 '{cmd}' 的响应")
            
            # 对于quit和position命令，不显示处理超时的警告
            elif not command_processed and not cmd.lower() == 'quit' and not cmd.lower().startswith('position'):
                print(f"警告: 命令 '{cmd}' 处理超时")
        
        # 关闭进程
        try:
            process.stdin.close()
        except:
            pass
        
        # 等待进程结束，但最多等待2秒
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # 进程仍在运行，强制终止
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
        
        # 检查是否有错误输出
        error_output = process.stderr.read()
        if error_output:
            print(f"\n错误输出:\n{error_output}")
            
        return 0
        
    except KeyboardInterrupt:
        print("程序被用户中断")
        # 清理资源
        if 'process' in locals():
            try:
                process.terminate()
                process.wait(timeout=1)
            except:
                try:
                    process.kill()
                except:
                    pass
        return 1
    except Exception as e:
        print(f"发生错误: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())