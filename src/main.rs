use nolos_nnue::protocol::Engine;
use nolos_nnue::search::now_ms;
use std::io::{self, BufRead, Read, Write};
use std::sync::mpsc;

fn main() {
    let mut engine = Engine::new();
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        if args.len() != 3 || args[1] != "--weights" {
            eprintln!("Usage: nolos-nnue [--weights PATH]");
            std::process::exit(2);
        }
        match std::fs::read(&args[2])
            .map_err(|e| e.to_string())
            .and_then(|b| engine.load_network(&b))
        {
            Ok(()) => {}
            Err(e) => {
                eprintln!("Cannot load weights: {e}");
                std::process::exit(2);
            }
        }
    }
    let (tx, rx) = mpsc::sync_channel::<String>(1024);
    // Input thread never evaluates or emits protocol output. One search thread.
    std::thread::spawn(move || {
        let input = io::stdin();
        let mut reader = input.lock();
        loop {
            let mut bytes = Vec::new();
            // Bounded input also protects against a nonconforming host.
            match reader.by_ref().take(8194).read_until(b'\n', &mut bytes) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if bytes.len() >= 8194 && !bytes.ends_with(b"\n") {
                        let mut discard = Vec::new();
                        loop {
                            discard.clear();
                            match reader.by_ref().take(8194).read_until(b'\n', &mut discard) {
                                Ok(0) | Err(_) => break,
                                Ok(_) if discard.ends_with(b"\n") => break,
                                _ => {}
                            }
                        }
                        bytes = vec![b'X'; 8193];
                    }
                    if tx
                        .send(String::from_utf8_lossy(&bytes).into_owned())
                        .is_err()
                    {
                        break;
                    }
                }
            }
        }
    });
    let mut output = io::stdout().lock();
    let emit = |lines: Vec<String>, output: &mut io::StdoutLock<'_>| {
        for line in lines {
            if writeln!(output, "{line}").is_err() {
                return false;
            }
        }
        output.flush().is_ok()
    };
    let mut disconnected = false;
    loop {
        if engine.ended {
            break;
        }
        if engine.busy() {
            loop {
                match rx.try_recv() {
                    Ok(line) => {
                        if !emit(engine.command(&line, now_ms()), &mut output) {
                            return;
                        }
                    }
                    Err(mpsc::TryRecvError::Disconnected) => {
                        disconnected = true;
                        break;
                    }
                    Err(mpsc::TryRecvError::Empty) => break,
                }
                if engine.ended {
                    return;
                }
            }
            if !emit(engine.tick(64, now_ms()), &mut output) {
                return;
            }
        } else if disconnected {
            break;
        } else {
            match rx.recv() {
                Ok(line) => {
                    if !emit(engine.command(&line, now_ms()), &mut output) {
                        return;
                    }
                }
                Err(_) => break,
            }
        }
    }
}
