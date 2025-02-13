cmake_minimum_required(VERSION 3.10)

project(my_onnxruntime_project)

set(CMAKE_CXX_STANDARD 14)

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/cmake")
find_package(ONNXRuntime REQUIRED)

add_executable(NolosNNUE
    src/main.cpp
    src/game/gomoku.h
    src/game/gomoku.cpp
    src/agent/player.h
    src/agent/random_player.h
    src/agent/random_player.cpp
    src/piskvork_proto.cpp
    src/piskvork_proto.h
    )

include_directories(${ONNXRUNTIME_INCLUDE_DIR})
target_link_libraries(NolosNNUE PRIVATE ${ONNXRUNTIME_LIBRARY})

# Copy dlls to the output directory if is Windows
if(WIN32)
    add_custom_command(TARGET NolosNNUE POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
        "${ONNXRUNTIME_LIBRARY}/../onnxruntime.dll"
        $<TARGET_FILE_DIR:NolosNNUE>)
endif()

# Copy model file
# add_custom_command(TARGET NolosNNUE POST_BUILD
#    COMMAND ${CMAKE_COMMAND} -E copy
#    "${CMAKE_SOURCE_DIR}/model.onnx"
#    $<TARGET_FILE_DIR:NolosNNUE>)

set_target_properties(NolosNNUE PROPERTIES OUTPUT_NAME "pbrain-NolosNNUE")