#!/usr/bin/env python3
"""Test the real stdin/stdout process, including asynchronous YXSTOP."""
import argparse
import json
import queue
import re
import subprocess
import threading
import time


class Engine:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.transcript = []
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())

    def send(self, *lines):
        self.process.stdin.write(''.join(line + '\r\n' for line in lines))
        self.process.stdin.flush()

    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        result = []
        while time.monotonic() < deadline:
            line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            result.append(line)
            self.transcript.append(line)
            if predicate(line):
                return result
        raise AssertionError('No expected reply: ' + repr(result))

    def sentinel(self):
        self.send('ABOUT')
        return self.until(lambda s: s.startswith('name='))

    def close(self):
        self.send('END')
        self.process.wait(timeout=2)
        assert self.process.returncode == 0
        assert self.process.stderr.read() == ''
        assert self.lines.empty(), 'END must not emit output'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', default='target/release/nolos-nnue')
    args = p.parse_args()
    e = Engine(args.binary)
    try:
        e.send('start 15')
        assert e.until(lambda s: s.startswith('OK')) == ['OK']
        e.send('INFO irrelevant 9', 'yxboard', '7,7,1', '8,7,2', 'done')
        assert len(e.sentinel()) == 1, 'YXBOARD/INFO must be silent'
        e.send('YXSTATUS')
        status = json.loads(e.until(lambda s: s.startswith('MESSAGE STATUS '))[-1][15:])
        assert status['history'] == [[112, 1], [113, 2]]
        e.send('INFO max_depth 64', 'INFO max_node 100000000', 'INFO timeout_turn 60000', 'YXGO')
        e.until(lambda s: s.startswith('INFO DEPTH '))
        start = time.monotonic()
        e.send('YXSTOP')
        reply = e.until(lambda s: re.fullmatch(r'\d+,\d+', s))[-1]
        assert time.monotonic() - start < 2, 'YXSTOP did not interrupt promptly'
        assert reply not in ['7,7', '8,7']
        assert len(e.sentinel()) == 1, 'Search returned more than one final move'
        e.send('YXSTATUS')
        status = json.loads(e.until(lambda s: s.startswith('MESSAGE STATUS '))[-1][15:])
        assert len(status['history']) == 3
        e.send('INFO max_depth 2', 'INFO max_node 512', 'INFO timeout_turn 60000', 'YXSUGGEST')
        e.until(lambda s: s.startswith('SUGGEST '))
        e.send('YXSTATUS')
        assert len(json.loads(e.until(lambda s: s.startswith('MESSAGE STATUS '))[-1][15:])['history']) == 3
        e.send('INFO hash_size 0', 'YXHASHCLEAR', 'YXSHOWHASHUSAGE')
        assert e.until(lambda s: s.startswith('MESSAGE hash'))[-1] == 'MESSAGE hash 0 KB'
        e.send('YXNBEST 3')
        assert e.until(lambda s: s.startswith('UNKNOWN'))[-1] == 'UNKNOWN YXNBEST'
        e.send('START 15', 'INFO rule 2', 'YXBOARD', '6,7,1', '0,0,2', '8,7,1', '1,0,2', '7,6,1', '2,0,2', '7,8,1', '3,0,2', 'DONE', 'YXSHOWFORBID')
        forbid = e.until(lambda s: s.startswith('FORBID '))[-1]
        assert '0707' in forbid and forbid.endswith('.')
        e.send('PLAY 7,7')
        assert e.until(lambda s: s.startswith('ERROR'))[-1] == 'ERROR invalid PLAY coordinate'
        e.close()
        print('Native Yixin transport, CRLF, status, suggestion, forbidden moves and stop: PASS')
    finally:
        if e.process.poll() is None:
            e.process.kill()
            e.process.wait()


if __name__ == '__main__':
    main()
