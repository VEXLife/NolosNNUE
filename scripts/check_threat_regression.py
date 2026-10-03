"""Cold/undo regression for the reported counter-four defensive position."""
import argparse
import json
from pathlib import Path
import time
import re
from scripts.match_external import Peer, digest, save

def commands(moves, nodes):
    side = len(moves) % 2 + 1
    return ['INFO rule 0', 'INFO max_depth 64', f'INFO max_node {nodes}',
            'INFO timeout_turn 600000', 'INFO show_detail 2', 'YXBOARD',
            *[f'{p % 15},{p // 15},{1 if i % 2 + 1 == side else 2}' for i, p in enumerate(moves)],
            'DONE', 'YXSUGGEST']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--nodes', type=int, default=1_000_000)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-unresolved', action='store_true')
    parser.add_argument('--wasm', type=Path)
    parser.add_argument('--sequence', default='h8g8i7g9g7i9h7f7h9h6j7k7i8g10j9')
    parser.add_argument('--defenses', default='g6,k10,g11,g12')
    parser.add_argument('--skip-undo', action='store_true')
    parser.add_argument('--hash-kb', type=int)
    parser.add_argument('--winner', choices=['black', 'white'], default='black',
                        help='expected winning color (default: black)')
    args = parser.parse_args()
    tokens = re.findall(r'[a-o](?:1[0-5]|[1-9])', args.sequence)
    if ''.join(tokens) != args.sequence:
        parser.error('expected concatenated a1..o15 coordinates')
    moves_base = [(int(token[1:]) - 1) * 15 + ord(token[0]) - ord('a') for token in tokens]
    defenses = []
    for token in args.defenses.split(',') if args.defenses else []:
        if not re.fullmatch(r'[a-o](?:1[0-5]|[1-9])', token):
            parser.error('expected comma-separated a1..o15 defenses')
        defenses.append((token, (int(token[1:]) - 1) * 15 + ord(token[0]) - ord('a')))
    report = {'engine_sha256': digest(args.engine), 'nodes': args.nodes,
              'weights_sha256': digest(args.weights) if args.weights else None,
              'sequence': args.sequence, 'winner': args.winner, 'results': []}
    report['hash_kb_override'] = args.hash_kb
    wasm_cases = []
    for label, extra in [('root', None), *defenses]:
        command = [str(args.engine.resolve())]
        if args.weights:
            command += ['--weights', str(args.weights.resolve())]
        peer = Peer(command)
        try:
            peer.send('START 15')
            peer.receive(lambda line: line == 'OK', 10)
            if args.hash_kb is not None:
                peer.send(f'INFO hash_size {args.hash_kb}')
            moves = moves_base + ([] if extra is None else [extra])
            for phase in ['cold'] if extra is None or args.skip_undo else ['cold', 'web_undo', 'undo']:
                if phase == 'web_undo':
                    # The web UI replaces YXBOARD without clearing the TT.
                    moves = moves_base
                if phase == 'undo':
                    peer.send(*commands(moves_base + [extra], args.nodes)[:-1])
                    peer.send(f'TAKEBACK {extra % 15},{extra // 15}')
                    peer.receive(lambda line: line == 'OK', 10)
                    moves = moves_base
                query = commands(moves, args.nodes)
                started = time.monotonic()
                peer.send(*query)
                lines = peer.receive(lambda line: line.startswith('SUGGEST '), 120)
                fields = {}
                for line in lines:
                    if line.startswith('INFO '):
                        parts = line.split(maxsplit=2)
                        if len(parts) == 3:
                            fields[parts[1]] = parts[2]
                row = {'position': label, 'phase': phase, 'seconds': time.monotonic() - started,
                       'analysis': fields, 'transcript': lines}
                winning_color = 1 if args.winner == 'black' else 2
                expected = '+M' if len(moves) % 2 + 1 == winning_color else '-M'
                row['found_mate'] = fields.get('EVAL', '').startswith(expected)
                report['results'].append(row)
                save(args.output, report)
                print(label, phase, row['seconds'], fields.get('EVAL'), fields.get('NODES'), flush=True)
                if not args.allow_unresolved:
                    assert row['found_mate'], row
                if phase == 'cold':
                    wasm_cases.append({'commands': ['START 15', *([] if args.hash_kb is None else [f'INFO hash_size {args.hash_kb}']), *query],
                                       'expected': f'INFO EVAL {fields["EVAL"]}', 'move': lines[-1]})
        finally:
            peer.close()
    if args.wasm:
        javascript = """
const fs=require('node:fs'), enc=new TextEncoder(),dec=new TextDecoder();let w,out=[];
(async()=>{const i=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),
{host:{now_ms:()=>0,output:(p,n)=>out.push(dec.decode(new Uint8Array(w.memory.buffer,p,n)))}});
w=i.instance.exports;w.engine_init();
function bytes(b,f){const p=w.engine_alloc(b.length);new Uint8Array(w.memory.buffer,p,b.length).set(b);
try{return f(p,b.length)}finally{w.engine_free(p,b.length)}}
if(process.argv[2])bytes(fs.readFileSync(process.argv[2]),(p,n)=>{if(!w.engine_load_weights(p,n))throw Error('weights')});
for(const row of JSON.parse(fs.readFileSync(0,'utf8'))){out=[];
for(const c of row.commands)bytes(enc.encode(c),(p,n)=>w.engine_command(p,n));
let ticks=0;while(w.engine_tick(128)){if(++ticks>100000)throw Error('nontermination')}
const evals=out.filter(x=>x.startsWith('INFO EVAL '));
if(evals.at(-1)!==row.expected||!out.includes(row.move))throw Error(JSON.stringify(out));}
console.log('Native / WASM cold-position mate and move agreement: PASS');
})().catch(e=>{console.error(e);process.exit(1)});
"""
        import subprocess
        subprocess.run(['node', '-e', javascript, str(args.wasm),
                        str(args.weights) if args.weights else ''],
                       input=json.dumps(wasm_cases), text=True, check=True)
        report['wasm_cold_agreement'] = True
        report['wasm_sha256'] = digest(args.wasm)
        save(args.output, report)


if __name__ == '__main__':
    main()
