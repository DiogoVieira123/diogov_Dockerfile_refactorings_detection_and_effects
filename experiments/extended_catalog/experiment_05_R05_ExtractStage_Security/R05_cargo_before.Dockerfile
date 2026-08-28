FROM rust:1.78

WORKDIR /usr/src/myapp

RUN cargo new --bin testapp
WORKDIR /usr/src/myapp/testapp

RUN cargo build --release

CMD ["./target/release/testapp"]
