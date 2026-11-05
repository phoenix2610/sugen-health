"""Mock Anthropic + OpenAI endpoints and a mock HTTPS_PROXY (DEV ONLY, stdlib only).

The real coder image is pointed at this server with ANTHROPIC_BASE_URL / OPENAI_BASE_URL, so the request goes
through the real SDKs (anthropic, openai) exactly as shipped. Responses follow the public wire formats:
  POST /v1/messages          -> Anthropic Messages response (a thinking block, then a text block)
  POST /v1/chat/completions  -> OpenAI chat.completion response
Every request body is logged so tests can check what the SDKs actually sent.

Scenarios (one per server):
  ok             valid JSON answers. The choose answer is [invalid code, the 6th listed leaf, a [parent] code],
                 which exercises code validation and forcing to a leaf.
  no_output_cfg  Anthropic: 400 whenever output_config is present (an older API surface).
  no_reasoning   OpenAI: 400 whenever reasoning_effort is present.
  garbage        non-JSON text and unknown codes.
  refusal        Anthropic: stop_reason "refusal" with no text.
  flaky          the first attempt of every request gets 529 (Anthropic) or 500 (OpenAI); the SDK's retry gets 200.
  auth           401 on every request (bad key).
  ratelimit      429 on every request (exhausted quota, the response our unfunded OpenAI key gets).
  expensive      valid answers that report 20M input tokens per call (budget guard).
  slow           valid answers after a 2 s delay (deadline guard).
"""
import hashlib
import json
import re
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CAND = re.compile(r"^(\S+)( \[parent\])? \| ", re.M)


def note_of(prompt):
    m = re.search(r"NOTE:\n(.*?)(?:\n\nCANDIDATES|\Z)", prompt, re.S)
    return m.group(1) if m else ""


def answer(prompt, scenario):
    """Return (text, chosen) for an extract or a choose prompt."""
    if scenario == "garbage":
        return ("Sure! I think the code is probably QQ00.0 or similar." if "CANDIDATES" in prompt
                else "not json at all"), None
    if "CANDIDATES" not in prompt:
        return json.dumps({"language": "English", "main": "mock diagnosis", "qualifiers": "",
                           "synonyms": ["mock synonym"], "others": []}), None
    cands = CAND.findall(prompt.split("CANDIDATES", 1)[1])
    leaves = [c for c, p in cands if not p]
    parents = [c for c, p in cands if p]
    chosen = leaves[min(5, len(leaves) - 1)] if leaves else None
    codes = ["ZZ99.9"] + ([chosen] if chosen else []) + parents[:1]
    return json.dumps({"codes": codes}), chosen


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, status, obj, headers=()):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        srv = self.server
        n = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        retry = int(self.headers.get("x-stainless-retry-count", "0") or 0)
        sc = srv.scenario
        anth = self.path.endswith("/v1/messages")
        if anth:
            prompt = "".join(m["content"] if isinstance(m["content"], str) else
                             "".join(b.get("text", "") for b in m["content"]) for m in req.get("messages", []))
        else:
            prompt = "".join(m["content"] for m in req.get("messages", []) if m.get("role") == "user")
        rec = {"t": time.time(), "path": self.path, "retry": retry, "body": req,
               "auth": bool(self.headers.get("x-api-key") or self.headers.get("authorization")),
               "note_sha": hashlib.sha1(note_of(prompt).encode()).hexdigest()}

        def err(status, etype, msg):
            rec["status"] = status
            srv.record(rec)
            if anth:
                return self.send(status, {"type": "error", "error": {"type": etype, "message": msg}})
            return self.send(status, {"error": {"message": msg, "type": etype, "param": None, "code": etype}})

        if sc == "auth":
            return err(401, "authentication_error", "invalid x-api-key")
        if sc == "ratelimit":
            return err(429, "insufficient_quota", "You exceeded your current quota")
        if sc == "flaky" and retry == 0:
            return err(529 if anth else 500, "overloaded_error", "Overloaded")
        if sc == "no_output_cfg" and anth and "output_config" in req:
            return err(400, "invalid_request_error", "output_config: Extra inputs are not permitted")
        if sc == "no_reasoning" and not anth and "reasoning_effort" in req:
            return err(400, "invalid_request_error", "Unrecognized request argument supplied: reasoning_effort")
        if sc == "slow":
            time.sleep(2.0)
        text, chosen = answer(prompt, sc)
        tin, tout = (20_000_000 if sc == "expensive" else len(prompt) // 4), 120
        rec.update(status=200, chosen=None if sc == "refusal" else chosen, usage=[tin, 0 if sc == "refusal" else tout])
        srv.record(rec)
        model = req.get("model")
        if anth:
            if sc == "refusal":
                return self.send(200, {"id": "msg_mock", "type": "message", "role": "assistant", "model": model,
                                       "content": [], "stop_reason": "refusal", "stop_sequence": None,
                                       "usage": {"input_tokens": tin, "output_tokens": 0}})
            return self.send(200, {"id": "msg_mock", "type": "message", "role": "assistant", "model": model,
                                   "content": [{"type": "thinking", "thinking": "", "signature": "mock"},
                                               {"type": "text", "text": text}],
                                   "stop_reason": "end_turn", "stop_sequence": None,
                                   "usage": {"input_tokens": tin, "output_tokens": tout}})
        return self.send(200, {"id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
                               "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                                                            "message": {"role": "assistant", "content": text}}],
                               "usage": {"prompt_tokens": tin, "completion_tokens": tout,
                                         "total_tokens": tin + tout}})


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, scenario, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.scenario, self.log, self.lock = scenario, [], threading.Lock()

    def record(self, rec):
        with self.lock:
            self.log.append(rec)

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class ProxyHandler(socketserver.BaseRequestHandler):
    """HTTP CONNECT proxy: 'deny' answers 403 (proxy up, destination refused); 'tunnel' relays the TLS bytes."""

    def handle(self):
        srv, s = self.server, self.request
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = s.recv(4096)
            if not chunk:
                return
            head += chunk
        line = head.split(b"\r\n", 1)[0].decode(errors="replace")
        with srv.lock:
            srv.log.append({"t": time.time(), "line": line})
        if srv.mode == "deny" or not line.startswith("CONNECT "):
            s.sendall(b"HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\n\r\n")
            return
        host, port = line.split()[1].rsplit(":", 1)
        up = socket.create_connection((host, int(port)), timeout=15)
        s.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

        def pipe(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                for x in (a, b):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        t = threading.Thread(target=pipe, args=(up, s), daemon=True)
        t.start()
        pipe(s, up)
        t.join(5)


class MockProxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode, port=0):
        super().__init__(("127.0.0.1", port), ProxyHandler)
        self.mode, self.log, self.lock = mode, [], threading.Lock()

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self
