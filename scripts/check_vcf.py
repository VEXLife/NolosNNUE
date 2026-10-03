"""Check long forcing proofs independently, and compare native/WASM results."""
import json
import argparse
from pathlib import Path
import subprocess
from scripts.match_external import Peer, winning


def validate(fixture, pv):
    size, attacker = fixture['size'], fixture['side']
    cells = [0] * size ** 2
    for i, p in enumerate(fixture['moves']):
        cells[p] = i % 2 + 1
        assert not winning(cells, size, p % size, p // size, cells[p])
    for i, p in enumerate(pv):
        side = attacker if i % 2 == 0 else 3 - attacker
        if side != attacker:
            for q, color in enumerate(cells):
                if color or q == p:
                    continue
                cells[q] = side
                assert not winning(cells, size, q % size, q // size, side)
                assert any(not cells[r] and winning(cells, size, r % size, r // size, attacker)
                           for r in range(len(cells)))
                cells[q] = 0
        assert cells[p] == 0
        cells[p] = side
        won = winning(cells, size, p % size, p // size, side)
        assert won == (i == len(pv) - 1)
        if won:
            assert side == attacker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='target/release/nolos-nnue')
    parser.add_argument('--selective', action='store_true')
    args = parser.parse_args()
    fixtures = json.loads(Path('artifacts/search-vcf-fixtures.json').read_text())['fixtures']
    positions = []
    peer = Peer([args.engine, '--weights', 'artifacts/cloud-gen9.nnue'])
    try:
        for fixture in fixtures:
            n = fixture['size']
            peer.send(f'START {n}')
            peer.receive(lambda line: line == 'OK', 10)
            commands = ['INFO rule 0', 'INFO max_depth 1', 'INFO max_node 10000',
                        'INFO timeout_turn 600000', 'INFO show_detail 2', 'YXBOARD']
            if args.selective:
                commands.insert(0, 'INFO selective_search 1')
            commands += [f'{p%n},{p//n},{1 if i%2+1 == fixture["side"] else 2}'
                         for i, p in enumerate(fixture['moves'])]
            commands += ['DONE', 'YXSUGGEST']
            peer.send(*commands)
            lines = peer.receive(lambda line: line.startswith('SUGGEST '), 20)
            line = next(line for line in lines if line.startswith('INFO BESTLINE '))
            pv = [int(pair.split(',')[1]) * n + int(pair.split(',')[0]) for pair in line[14:].split()]
            assert len(pv) == fixture['expected_plies']
            assert f'INFO EVAL +M{len(pv)}' in lines
            assert any(line.startswith(f'MESSAGE VCF proof {len(pv)} plies') for line in lines)
            validate(fixture, pv)
            positions.append({'commands': [f'START {n}', *commands],
                              'expected': line, 'move': lines[-1]})
    finally:
        peer.close()
    javascript = """
const fs=require('node:fs'), enc=new TextEncoder(),dec=new TextDecoder();let w,out=[];
(async()=>{const i=await WebAssembly.instantiate(fs.readFileSync('web/nolos_nnue.wasm'),
{host:{now_ms:()=>0,output:(p,n)=>out.push(dec.decode(new Uint8Array(w.memory.buffer,p,n)))}});
w=i.instance.exports;w.engine_init();
function bytes(b,f){const p=w.engine_alloc(b.length);new Uint8Array(w.memory.buffer,p,b.length).set(b);
try{return f(p,b.length)}finally{w.engine_free(p,b.length)}}
bytes(fs.readFileSync('artifacts/cloud-gen9.nnue'),(p,n)=>{if(!w.engine_load_weights(p,n))throw Error('weights')});
for(const row of JSON.parse(fs.readFileSync(0,'utf8'))){out=[];
for(const c of row.commands)bytes(enc.encode(c),(p,n)=>w.engine_command(p,n));
let ticks=0;while(w.engine_tick(32)){if(++ticks>10000)throw Error('nontermination')}
if(!out.includes(row.expected)||!out.includes(row.move))throw Error(JSON.stringify(out));}
console.log('Independent defense validation / native / WASM: 17- and 31-ply forcing lines PASS');
})().catch(e=>{console.error(e);process.exit(1)});
"""
    subprocess.run(['node', '-e', javascript], input=json.dumps(positions), text=True, check=True)


if __name__ == '__main__':
    main()
