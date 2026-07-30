# Build + run environment for visionai-inferd (S1).
# Host apt is optional; prefer: ./scripts/build_docker.sh
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    protobuf-compiler \
    libprotobuf-dev \
    libgrpc++-dev \
    protobuf-compiler-grpc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/native/inferd
