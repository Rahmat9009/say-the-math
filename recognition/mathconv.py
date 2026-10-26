"""Manage the long-lived local Node worker (math_worker.mjs) for LaTeX -> MathML, speech and tree."""
import json
import queue
import shutil
import subprocess
import threading
import time

from . import config


class MathWorkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def node_executable():
    return shutil.which('node')


def worker_problems():
    problems = []
    if not node_executable():
        problems.append('Node.js was not found')
    if not config.WORKER_SCRIPT.is_file():
        problems.append('math_worker.mjs is missing')
    for pkg in ('@mathjax/src', 'speech-rule-engine', '@xmldom/xmldom'):
        if not (config.NODE_MODULES / pkg / 'package.json').is_file():
            problems.append(f'Node package {pkg} is not installed')
    return problems


class MathWorker:
    def __init__(self, timeout=config.WORKER_TIMEOUT_S):
        self.timeout = timeout
        self.proc = None
        self.versions = None
        self._lines = None
        self._lock = threading.Lock()
        self._next_id = 1

    def _start(self):
        node = node_executable()
        if not node:
            raise MathWorkerError('NOT_READY', 'Node.js was not found')
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        self.proc = subprocess.Popen([node, str(config.WORKER_SCRIPT)], cwd=str(config.ROOT), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                     bufsize=1, creationflags=flags)
        self._lines = queue.Queue()
        proc, lines = self.proc, self._lines

        def pump():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()
        hello = self._read(0, timeout=60.0)  # first start loads MathJax and SRE rules
        self.versions = hello.get('versions')

    def _read(self, want_id, timeout):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self._kill()
                raise MathWorkerError('TIMEOUT', 'The math converter took too long')
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                self._kill()
                raise MathWorkerError('WORKER_EXITED', 'The math converter stopped unexpectedly')
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get('id') == want_id:
                return msg

    def _kill(self):
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def ensure_started(self):
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            return self.versions

    def request(self, payload):
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            rid = self._next_id
            self._next_id += 1
            try:
                self.proc.stdin.write(json.dumps({'id': rid, **payload}) + '\n')
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self._kill()
                raise MathWorkerError('WORKER_EXITED', 'The math converter stopped unexpectedly')
            return self._read(rid, self.timeout)

    def convert(self, latex):
        msg = self.request({'op': 'convert', 'latex': latex})
        if not msg.get('ok'):
            raise MathWorkerError(msg.get('code', 'MATH_CONVERSION_FAILED'), msg.get('message', 'conversion failed'))
        return {k: msg[k] for k in ('mathml', 'speech', 'root_id', 'nodes', 'truncated')}

    def ping(self):
        return self.request({'op': 'ping'})

    def close(self):
        with self._lock:
            if self.proc is not None:
                try:
                    self.proc.stdin.close()
                    self.proc.wait(timeout=3)
                except Exception:
                    self._kill()
            self.proc = None
