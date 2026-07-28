FROM rust:1.78 AS builder

WORKDIR /usr/src/myapp
RUN cargo new --bin testapp
WORKDIR /usr/src/myapp/testapp
RUN cargo build --release

FROM alpine:3.20

WORKDIR /app

COPY --from=builder /usr/src/myapp/testapp/target/release/testapp .

CMD ["./testapp"]
