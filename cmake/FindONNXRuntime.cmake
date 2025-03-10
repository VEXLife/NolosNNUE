find_path(ONNXRUNTIME_INCLUDE_DIR onnxruntime_cxx_api.h ${CMAKE_SOURCE_DIR}/include /usr/local/include /usr/include)
find_library(ONNXRUNTIME_LIBRARY onnxruntime ${CMAKE_SOURCE_DIR}/lib /usr/local/lib /usr/lib)
if (NOT ONNXRUNTIME_INCLUDE_DIR OR NOT ONNXRUNTIME_LIBRARY)
    message(FATAL_ERROR "ONNXRuntime library not found")
endif()