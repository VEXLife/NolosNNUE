# Yixin protocol support

English | [简体中文](protocol.zh-CN.md)

Implemented against the [original Yixin protocol](https://github.com/accreator/Yixin-protocol) and [base Gomocup protocol](https://plastovicka.github.io/protocl2en.htm), with the local Yixin-Board `send_board` and analysis parsers checked as references. Commands are case-insensitive and accept CRLF/LF. Coordinates are zero-based: `p = y * size + x`.

Both native and WASM use the Engine in `src/protocol.rs`. Browser JavaScript does not translate to a second game API: it calls the command entry point and uploads weight bytes that would otherwise come from the filesystem.

## Standard commands and original extensions

| Command | Behavior |
| --- | --- |
| `START N` | Initialize a 5..20 square board; reply `OK`, make no move, retain rules and network |
| `RESTART` | Clear position and transposition table; reply `OK` |
| `RECTSTART W,H` | Require W=H; otherwise reply `ERROR` |
| `ABOUT` | Output name, version, and author |
| `BEGIN` | Search and play black on an empty board |
| `TURN X,Y` | Place the opponent's stone, search, and output the engine's `X,Y` |
| `BOARD` + rows `X,Y,field` + `DONE` | Replace the board, then search and play |
| `YXBOARD` + the same rows | Replace the board; **no search or move response** |
| `PLAY X,Y` | Commit an engine move and echo `X,Y`; no search |
| `TAKEBACK X,Y` | Remove the specified stone; reply `OK` or `ERROR` |
| `YXSTOP` | Stop a search and output one move; silent when no search is running |
| `YXHASHCLEAR` | Clear the transposition table; silent |
| `YXSHOWFORBID` | Renju black forbidden moves as `FORBID X1Y1X2Y2... .`, with no actual space before the dot and two digits per coordinate; `ERROR` outside Renju |
| `END` | Terminate immediately without further output |

`field=1` means the engine's stones; `field=2` means the opponent's. With chronological input, the first stone is black, allowing actual colors to be reconstructed. Renju requires alternating chronological history. Non-alternating `BOARD` order under unrestricted rules uses stone counts to infer the engine's color. Duplicate coordinates and field=3 are rejected. Rows are buffered and replace the board only after a valid `DONE`; errors preserve the previous position.

Search uses its own board copy. Stopping commits only the chosen move to the protocol board, never an unfinished search variation. `START`, `RESTART`, and a new `BOARD` cancel an existing search.

| `INFO` parameter | Support |
| --- | --- |
| `rule` | **Yixin 0=freestyle, 1=standard, 2=Renju**, not the older Gomocup bitmask; unsupported values produce a deferred error |
| `timeout_turn` | Milliseconds; 0 immediately returns a move from static pattern ordering |
| `time_left`, `time_increment` | Allocate search time from the remaining clock |
| `max_depth` | Positive values limit iterative depth; non-positive values remove that limit |
| `max_node` | Positive values limit total nodes; non-positive values remove the node limit |
| `hash_size` | **KB**, capped at 64 MiB; 0 disables the table |
| `max_memory` | Reduce the transposition-table budget; not a hard process-wide memory limit |
| `thread_num` | One search thread satisfies any positive upper limit; native also has an input-only thread |
| `thread_split_depth` | Ignored; no search task splitting |
| `show_detail` | Positive values enable Yixin log statistics and `MESSAGE REALTIME` PV updates; 0 disables them |
| Other INFO | Silently ignored; no automatic pondering |

Analysis output is compatible with the local Yixin-Board: `INFO NUMPV 1`, `INFO PV 0`, `INFO DEPTH`, `INFO NODES`, `INFO EVAL`, `INFO WINRATE`, `INFO BESTLINE`, and `INFO PV DONE`. WINRATE maps evaluation through a sigmoid; it is not a probability calibrated against external competition. Winning scores use `+M`/`-M`, but selective search is not an exhaustive formal proof.

## Project extensions

| Command | Behavior |
| --- | --- |
| `YXGO` | Search the current position as the engine and commit a move |
| `YXSUGGEST` | Analyze without playing; final output is `SUGGEST X,Y`; stopping also only suggests |
| `YXSTATUS` | `MESSAGE STATUS {JSON}`, including size, rule, side to move, winner, board, and history |
| `YXLOADNNUE PATH` | Native loads from a file and replies `OK`; WASM receives bytes from its host |
| `YXUNLOADNNUE` | Restore HCE, clear the table, and reply `OK` |
| `YXEVAL` | `MESSAGE EVAL value`, from the engine's perspective |
| `YXSHOWINFO` | Report engine name, version, evaluator, maximum search threads and hash capacity |
| `YXSHOWHASHUSAGE` | Report allocated transposition-table capacity |

Stop searching before changing the evaluator. Invalid weights retain the previous network. Unsupported additional commands, including databases, `YXNBEST` multi-PV, Swap2/Soosõrv opening negotiation, and blocked paths, return `UNKNOWN`. Implementing the core original protocol does not imply support for all Rapfi private GUI extensions.

The browser ABI exports `engine_init`, `engine_alloc`, `engine_free`, `engine_command`, `engine_tick`, and `engine_load_weights`. The host provides an output callback and monotonic clock. The Worker periodically yields so `YXSTOP` reaches the shared protocol state machine without shared memory.
