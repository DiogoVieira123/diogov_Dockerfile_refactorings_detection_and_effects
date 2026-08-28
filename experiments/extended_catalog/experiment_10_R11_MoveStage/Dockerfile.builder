# AFTER (extracted stage) — R11 Move Stage
# The build stage has been moved out into this standalone Dockerfile.
# It is built separately and produces a reusable image (tagged r11-builder:1.0).

FROM alpine:3.20
WORKDIR /build
COPY app.txt /build/app.txt
RUN cp /build/app.txt /build/artifact.txt
