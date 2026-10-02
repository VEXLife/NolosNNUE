#!/usr/bin/env python3
"""Compare PyTorch, native Rust and WASM evaluations on generated positions."""
import argparse
import json
import subprocess
from pathlib import Path
import torch
from trainer.model import NNUE, SCALE
from trainer.train import batch
from scripts.check_protocol import Engine


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--samples', type=int, default=100)
    p.add_argument('--binary', default='target/release/nolos-nnue')
    args = p.parse_args()
    torch.set_num_threads(1)
    model = NNUE()
    model.load_state_dict(torch.load(args.weights.with_suffix('.pt'), map_location='cpu', weights_only=True))
    data = sorted((json.loads(line) for line in args.data.read_text().splitlines()), key=lambda s: (s['game'],s['board']))
    samples = data[::max(1,len(data)//args.samples)][:args.samples]
    e = Engine(args.binary)
    comparisons = []
    try:
        e.send(f'YXLOADNNUE {args.weights.resolve()}')
        assert e.until(lambda s:s.startswith(('OK','ERROR')))[-1]=='OK'
        for sample in samples:
            n, side = sample['size'], sample['side']
            black = [i for i,c in enumerate(sample['board']) if c=='1']
            white = [i for i,c in enumerate(sample['board']) if c=='2']
            history = []
            for i in range(max(len(black),len(white))):
                if i<len(black):history.append((black[i],1))
                if i<len(white):history.append((white[i],2))
            commands = [f'START {n}','INFO rule 0','YXBOARD'] + [f'{q%n},{q//n},{1 if c==side else 2}' for q,c in history] + ['DONE','YXEVAL']
            e.send(*commands)
            line=e.until(lambda s:s.startswith('MESSAGE EVAL '))[-1]
            native=int(line.split()[-1])
            b=batch([sample],torch.device('cpu'),0.3)
            with torch.no_grad():expected=round(max(-12000,min(12000,model(*b[:4]).item()*SCALE)))
            assert abs(native-expected)<=1,(native,expected,sample['game'])
            comparisons.append({'commands':commands,'expected':expected,'native':native})
        e.close()
        node_script = """
const fs=require('node:fs');const enc=new TextEncoder(),dec=new TextDecoder();let w,out=[];
(async()=>{const i=await WebAssembly.instantiate(fs.readFileSync('web/nolos_nnue.wasm'),{host:{now_ms:()=>0,output:(p,n)=>out.push(dec.decode(new Uint8Array(w.memory.buffer,p,n)))}});w=i.instance.exports;w.engine_init();
function bytes(b,f){let p=w.engine_alloc(b.length);new Uint8Array(w.memory.buffer,p,b.length).set(b);try{return f(p,b.length)}finally{w.engine_free(p,b.length)}};
bytes(fs.readFileSync(process.argv[1]),(p,n)=>{if(!w.engine_load_weights(p,n))throw Error('weights')});
const positions=JSON.parse(fs.readFileSync(0,'utf8'));for(const s of positions){out=[];for(const l of s.commands)bytes(enc.encode(l),(p,n)=>w.engine_command(p,n));let score=Number(out.find(x=>x.startsWith('MESSAGE EVAL ')).split(' ').at(-1));if(Math.abs(score-s.expected)>1||Math.abs(score-s.native)>1)throw Error(JSON.stringify({score,...s}));}console.log('PyTorch / native Rust / WASM agreement: '+positions.length+' positions PASS');})().catch(e=>{console.error(e);process.exit(1)});
"""
        subprocess.run(['node','-e',node_script,str(args.weights.resolve())], input=json.dumps(comparisons), text=True,check=True)
    finally:
        if e.process.poll() is None:e.process.kill();e.process.wait()


if __name__=='__main__':main()
