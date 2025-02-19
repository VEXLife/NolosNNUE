@echo off
cd %~dp0/train
set hhmmss=%time:~0,2%-%time:~3,2%-%time:~6,2%
if "%hhmmss:~0,1%"==" " set hhmmss=%hhmmss:~1%
..\.venv\Scripts\python.exe piskvork_proto.py 2>../logs/err_%hhmmss%.log