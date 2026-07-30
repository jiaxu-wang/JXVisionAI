cmake_minimum_required(VERSION 3.16)
project(visionai_inferd LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Threads REQUIRED)
find_package(Protobuf REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GRPC REQUIRED IMPORTED_TARGET grpc++)

find_program(GRPC_CPP_PLUGIN grpc_cpp_plugin REQUIRED)
if(NOT Protobuf_PROTOC_EXECUTABLE)
  find_program(Protobuf_PROTOC_EXECUTABLE protoc REQUIRED)
endif()

set(ORT_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime)
if(NOT EXISTS ${ORT_ROOT}/include/onnxruntime_cxx_api.h)
  message(FATAL_ERROR "ONNX Runtime missing. Run: ./scripts/setup_ort.sh (as root for apt-get download)")
endif()

set(PROTO_FILE ${CMAKE_CURRENT_SOURCE_DIR}/proto/visionai/infer/v1/infer.proto)
set(PROTO_GEN_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${PROTO_GEN_DIR})

set(PROTO_SRCS
  ${PROTO_GEN_DIR}/visionai/infer/v1/infer.pb.cc
  ${PROTO_GEN_DIR}/visionai/infer/v1/infer.grpc.pb.cc
)
set(PROTO_HDRS
  ${PROTO_GEN_DIR}/visionai/infer/v1/infer.pb.h
  ${PROTO_GEN_DIR}/visionai/infer/v1/infer.grpc.pb.h
)

add_custom_command(
  OUTPUT ${PROTO_SRCS} ${PROTO_HDRS}
  COMMAND ${CMAKE_COMMAND} -E make_directory ${PROTO_GEN_DIR}/visionai/infer/v1
  COMMAND ${Protobuf_PROTOC_EXECUTABLE}
    --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto
    --cpp_out=${PROTO_GEN_DIR}
    --grpc_out=${PROTO_GEN_DIR}
    --plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN}
    ${PROTO_FILE}
  DEPENDS ${PROTO_FILE}
  COMMENT "Generating gRPC/Protobuf sources for infer.proto"
  VERBATIM
)

add_library(infer_proto ${PROTO_SRCS})
target_include_directories(infer_proto PUBLIC ${PROTO_GEN_DIR})
target_link_libraries(infer_proto PUBLIC protobuf::libprotobuf PkgConfig::GRPC)

add_executable(visionai-inferd
  src/main.cpp
  src/infer_service_impl.cpp
  src/core/model_repository.cpp
  src/core/session_manager.cpp
  src/core/engine_hub.cpp
  src/backend/ort_yolo_backend.cpp
  src/prepost/yolo_letterbox.cpp
)
target_include_directories(visionai-inferd PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${PROTO_GEN_DIR}
  ${ORT_ROOT}/include
)
target_link_libraries(visionai-inferd PRIVATE
  infer_proto
  Threads::Threads
  ${ORT_ROOT}/lib/libonnxruntime.so
)
set_target_properties(visionai-inferd PROPERTIES
  BUILD_RPATH ${ORT_ROOT}/lib
  INSTALL_RPATH ${ORT_ROOT}/lib
)

install(TARGETS visionai-inferd RUNTIME DESTINATION bin)
