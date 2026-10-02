use crate::protocol::Engine;
use std::cell::RefCell;

#[link(wasm_import_module = "host")]
extern "C" {
    fn output(ptr: *const u8, len: usize);
    fn now_ms() -> f64;
}

thread_local! { static ENGINE: RefCell<Option<Engine>> = const { RefCell::new(None) }; }

fn emit(lines: Vec<String>) {
    for line in lines {
        unsafe {
            output(line.as_ptr(), line.len());
        }
    }
}

#[no_mangle]
pub extern "C" fn engine_init() {
    ENGINE.with(|e| *e.borrow_mut() = Some(Engine::new()));
}

/// Host owns the returned buffer until engine_free; command/load copy or read
/// its contents synchronously. No wasm-bindgen-specific protocol adapter.
#[no_mangle]
pub extern "C" fn engine_alloc(len: usize) -> *mut u8 {
    let bytes = vec![0u8; len].into_boxed_slice();
    Box::into_raw(bytes) as *mut u8
}

#[no_mangle]
pub unsafe extern "C" fn engine_free(ptr: *mut u8, len: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
}

#[no_mangle]
pub unsafe extern "C" fn engine_command(ptr: *const u8, len: usize) {
    let line = String::from_utf8_lossy(std::slice::from_raw_parts(ptr, len));
    let lines = ENGINE.with(|e| e.borrow_mut().as_mut().unwrap().command(&line, now_ms()));
    emit(lines);
}

#[no_mangle]
pub extern "C" fn engine_tick(batch: usize) -> u32 {
    let (lines, busy) = ENGINE.with(|e| {
        let mut e = e.borrow_mut();
        let engine = e.as_mut().unwrap();
        let lines = engine.tick(batch.clamp(1, 1024), unsafe { now_ms() });
        (lines, engine.busy())
    });
    emit(lines);
    busy as u32
}

#[no_mangle]
pub unsafe extern "C" fn engine_load_weights(ptr: *const u8, len: usize) -> u32 {
    let result = ENGINE.with(|e| {
        e.borrow_mut()
            .as_mut()
            .unwrap()
            .load_network(std::slice::from_raw_parts(ptr, len))
    });
    match result {
        Ok(()) => 1,
        Err(e) => {
            emit(vec![format!("ERROR {e}")]);
            0
        }
    }
}
