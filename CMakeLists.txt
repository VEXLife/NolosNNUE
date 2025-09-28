cmake_minimum_required(VERSION 3.15)

# 设置使用MinGW的GCC和G++
set(CMAKE_C_COMPILER "gcc")
set(CMAKE_CXX_COMPILER "g++")
message(STATUS "使用MinGW编译器")

project(NolosNNUE)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/cmake")

# 添加USE_ONNX选项，默认为OFF
option(USE_ONNX "使用ONNX Runtime库" OFF)

# 条件性地查找ONNX Runtime库
if(USE_ONNX)
    find_package(ONNXRuntime REQUIRED)
    add_definitions(-DUSE_ONNX)
    message(STATUS "使用ONNX Runtime库")
else()
    message(STATUS "不使用ONNX Runtime库，仅使用手动评估函数")
endif()

# 添加所有源文件
add_executable(NolosNNUE 
    src/main.cpp
    src/chessboard.cpp
    src/evaluator.cpp
    src/search.cpp
    src/ucci.cpp
)

# 添加头文件搜索路径
include_directories(
    ${CMAKE_SOURCE_DIR}/include
)

# 条件性地添加ONNX Runtime头文件搜索路径
if(USE_ONNX)
    include_directories(${ONNXRUNTIME_INCLUDE_DIR})
endif()
# 条件性地链接ONNX Runtime库
if(USE_ONNX)
    target_link_libraries(NolosNNUE PRIVATE ${ONNXRUNTIME_LIBRARY})
    
    # Copy dlls to the output directory if is Windows
    if(WIN32)
        add_custom_command(TARGET NolosNNUE POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy
            "${ONNXRUNTIME_LIBRARY}/../onnxruntime.dll"
            $<TARGET_FILE_DIR:NolosNNUE>)
    endif()
    
    # Copy model file
    add_custom_command(TARGET NolosNNUE POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_SOURCE_DIR}/model.onnx"
        $<TARGET_FILE_DIR:NolosNNUE>)
endif()