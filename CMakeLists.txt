cmake_minimum_required(VERSION 3.10)

project(NolosNNUE)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/cmake")

add_executable(NolosNNUE
    src/main.cpp
    src/game/gomoku.h
    src/game/gomoku.cpp
    src/agent/player.h
    src/agent/random_player.h
    src/agent/random_player.cpp
    src/agent/negamax.h
    src/agent/negamax.cpp
    src/piskvork_proto.cpp
    src/piskvork_proto.h
    src/eval/evaluator.h
    src/eval/classic.h
    src/eval/classic.cpp
    src/eval/onnx.h
    src/eval/onnx.cpp
    )

add_executable(
    data_collector
    src/selfplay/data_collector.h
    src/selfplay/data_collector.cpp
    src/selfplay/run.cpp
    src/selfplay/random_negamax.h
    src/selfplay/random_negamax.cpp
    src/eval/evaluator.h
    src/eval/classic.h
    src/eval/classic.cpp
    src/eval/onnx.h
    src/eval/onnx.cpp
    src/game/gomoku.h
    src/game/gomoku.cpp
    src/agent/player.h
    src/agent/random_player.h
    src/agent/random_player.cpp
    src/agent/negamax.h
    src/agent/negamax.cpp
)

# ONNXRuntime
find_package(ONNXRuntime REQUIRED)
include_directories(${ONNXRUNTIME_INCLUDE_DIR})
target_link_libraries(NolosNNUE PRIVATE ${ONNXRUNTIME_LIBRARY})
target_link_libraries(data_collector PRIVATE ${ONNXRUNTIME_LIBRARY})

# SPDLOG
add_subdirectory(spdlog)
include_directories(spdlog/include)
# Add /utf-8
target_compile_options(NolosNNUE PRIVATE "/utf-8")
target_compile_options(data_collector PRIVATE "/utf-8")

# Copy dlls to the output directory if is Windows
if(WIN32)
    add_custom_command(TARGET NolosNNUE POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "${ONNXRUNTIME_LIBRARY}/../onnxruntime.dll"
        $<TARGET_FILE_DIR:NolosNNUE>)
    add_custom_command(TARGET data_collector POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "${ONNXRUNTIME_LIBRARY}/../onnxruntime.dll"
        $<TARGET_FILE_DIR:data_collector>)
endif()

# Copy model file
add_custom_command(TARGET NolosNNUE POST_BUILD
   COMMAND ${CMAKE_COMMAND} -E copy
   "${CMAKE_SOURCE_DIR}/model.onnx"
   $<TARGET_FILE_DIR:NolosNNUE>)
add_custom_command(TARGET data_collector POST_BUILD
   COMMAND ${CMAKE_COMMAND} -E copy
   "${CMAKE_SOURCE_DIR}/model.onnx"
   $<TARGET_FILE_DIR:data_collector>)

   # if model.onnx.data is also present, copy it
add_custom_command(TARGET NolosNNUE POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy
    "${CMAKE_SOURCE_DIR}/model.onnx.data"
    $<TARGET_FILE_DIR:NolosNNUE>)
add_custom_command(TARGET data_collector POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy
    "${CMAKE_SOURCE_DIR}/model.onnx.data"
    $<TARGET_FILE_DIR:data_collector>)

set_target_properties(NolosNNUE PROPERTIES OUTPUT_NAME "pbrain-NolosNNUE")

# _CRT_SECURE_NO_WARNINGS
target_compile_definitions(NolosNNUE PRIVATE _CRT_SECURE_NO_WARNINGS)
target_compile_definitions(data_collector PRIVATE _CRT_SECURE_NO_WARNINGS)