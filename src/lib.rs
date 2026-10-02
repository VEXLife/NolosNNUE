pub mod board;
#[cfg(not(target_arch = "wasm32"))]
pub mod experiment;
pub mod network;
pub mod protocol;
pub mod search;

#[cfg(target_arch = "wasm32")]
mod wasm;
