"""Integration tests of the keyed path against mocked APIs (DEV ONLY).

Each scenario starts tools/mock_api.py on localhost and runs the SHIPPED Docker image on the 60 dev notes:
    docker run --network host -e ANTHROPIC_API_KEY=mock -e ANTHROPIC_BASE_URL=http://127.0.0.1:<port> ...
so the request goes through the real anthropic/openai SDK versions in the image. The mock's answers are scripted, so
the accuracy numbers mean nothing here; the tests check behaviour: what the SDKs send, whether the answers are used,
and whether every failure mode leaves a complete, valid output file.

    .venv/bin/python tools/mock_test.py [--live-unauth]     # writes results/mock_tests.txt

--live-unauth adds two LIVE checks that need internet: a CONNECT proxy on localhost relays real TLS to
api.anthropic.com / api.openai.com with an invalid key ("mock-invalid-key"), so they test the route through
HTTPS_PROXY and the 401 handling, not model behaviour. No real key is used anywhere in this file.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from coder.kb import KB  # noqa: E402
from mock_api import MockProxy, MockServer  # noqa: E402

IMAGE = "sugen-icd11-coder"
NOTES = os.path.join(ROOT, "problem/data/dev_notes.jsonl")
NOKEY = os.path.join(ROOT, "results/dev_nokey.pred.jsonl")
KEY = "mock-invalid-key"


def load(path):
    return {r["id"]: r for r in (json.loads(l) for l in open(path, encoding="utf-8") if l.strip())}


def run_image(env, workdir):
    os.makedirs(os.path.join(workdir, "out"), exist_ok=True)
    cmd = ["docker", "run", "--rm", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}",
           "-v", f"{os.path.dirname(NOTES)}:/in:ro", "-v", f"{workdir}/out:/out"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    t0 = time.time()
    p = subprocess.run(cmd + [IMAGE, "/in/dev_notes.jsonl", "/out/predictions.jsonl"],
                       capture_output=True, text=True, timeout=900)
    wall = time.time() - t0
    preds = load(os.path.join(workdir, "out/predictions.jsonl"))
    return p.returncode, wall, preds, p.stderr


class Case:
    def __init__(self, name, provider, scenario, extra=None, proxy=None, live=False):
        self.name, self.provider, self.scenario = name, provider, scenario
        self.extra, self.proxy, self.live = extra or {}, proxy, live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-unauth", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    kb = KB()
    leaves = {c["c"] for c in kb.codes if c["leaf"]}
    notes = load(NOTES)
    sha = {nid: hashlib.sha1(r["text"][:6000].encode()).hexdigest() for nid, r in notes.items()}
    nokey = {k: v["codes"] for k, v in load(NOKEY).items()}

    cases = [
        Case("anthropic: happy path", "anthropic", "ok"),
        Case("openai: happy path", "openai", "ok"),
        Case("anthropic: output_config rejected -> retry plain", "anthropic", "no_output_cfg"),
        Case("openai: reasoning_effort rejected -> retry plain", "openai", "no_reasoning"),
        Case("anthropic: non-JSON answers", "anthropic", "garbage"),
        Case("openai: non-JSON answers", "openai", "garbage"),
        Case("anthropic: stop_reason refusal", "anthropic", "refusal"),
        Case("anthropic: 529 on first attempt (SDK retry)", "anthropic", "flaky"),
        Case("openai: 500 on first attempt (SDK retry)", "openai", "flaky"),
        Case("anthropic: 401 bad key -> breaker", "anthropic", "auth"),
        Case("openai: 429 insufficient_quota -> breaker", "openai", "ratelimit"),
        Case("anthropic: budget guard (20M tokens/call)", "anthropic", "expensive"),
        Case("anthropic: $0.01 budget cap, realistic usage", "anthropic", "ok", extra={"CODER_BUDGET_USD": "0.01"}),
        Case("openai: $0.05 budget cap, realistic usage", "openai", "ok", extra={"CODER_BUDGET_USD": "0.05"}),
        Case("anthropic: deadline guard (6 s, 2 s/call)", "anthropic", "slow", extra={"CODER_DEADLINE_S": "6"}),
        Case("both keys set -> anthropic preferred", "both", "ok"),
        Case("anthropic: HTTPS_PROXY refuses CONNECT", "anthropic", None, proxy="deny"),
        Case("openai: HTTPS_PROXY refuses CONNECT", "openai", None, proxy="deny"),
    ]
    if a.live_unauth:
        cases += [Case("LIVE anthropic via CONNECT proxy, invalid key", "anthropic", None, proxy="tunnel", live=True),
                  Case("LIVE openai via CONNECT proxy, invalid key", "openai", None, proxy="tunnel", live=True)]
    if a.only:
        cases = [c for c in cases if a.only in c.name]

    lines, n_fail = [], 0
    for c in cases:
        srv = MockServer(c.scenario).start() if c.scenario else None
        prx = MockProxy(c.proxy).start() if c.proxy else None
        env = dict(c.extra)
        url = f"http://127.0.0.1:{srv.server_address[1]}" if srv else None
        if c.provider in ("anthropic", "both"):
            env["ANTHROPIC_API_KEY"] = KEY
            if url:
                env["ANTHROPIC_BASE_URL"] = url
        if c.provider in ("openai", "both"):
            env["OPENAI_API_KEY"] = KEY
            if url:
                env["OPENAI_BASE_URL"] = url + "/v1"
        if prx:
            env["HTTPS_PROXY"] = f"http://127.0.0.1:{prx.server_address[1]}"
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as wd:
            rc, wall, preds, err = run_image(env, wd)
        log = srv.log if srv else []
        checks = []

        def check(label, ok):
            checks.append((label, bool(ok)))

        # contract checks, every case
        check("exit 0", rc == 0)
        check("60/60 ids", set(preds) == set(notes))
        allc = [x for p in preds.values() for x in p["codes"]]
        check("all codes valid leaves", all(x in leaves for x in allc) and all(1 <= len(p["codes"]) <= 3
                                                                             for p in preds.values()))
        chosen = {r["note_sha"]: r["chosen"] for r in log if r.get("chosen")}
        used = sum(1 for nid in notes if chosen.get(sha[nid]) and preds[nid]["codes"][0] == chosen[sha[nid]])
        same_nokey = sum(1 for nid in notes if preds[nid]["codes"] == nokey[nid])
        ok200 = [r for r in log if r.get("status") == 200]
        st = {}
        for r in log:
            st[r["status"]] = st.get(r["status"], 0) + 1

        sc = c.scenario
        price = {"anthropic": (0.10, 0.50), "both": (0.10, 0.50), "openai": (0.25, 2.00)}[c.provider]
        billed = sum(r["usage"][0] * price[0] + r["usage"][1] * price[1] for r in ok200) / 1e6
        cap = float(c.extra.get("CODER_BUDGET_USD", 0) or 0)
        if cap:
            check(f"billed ${billed:.4f} <= cap ${cap}", billed <= cap)
            check("calls made until the cap, then stopped", 10 < len(ok200) < 120)
        elif sc in ("ok", "no_output_cfg", "no_reasoning", "flaky"):
            check("LLM answer used for 60/60", used == 60)
            check("invalid code ZZ99.9 dropped", "ZZ99.9" not in allc)
            check("2 successful calls per note", len(ok200) == 120)
        if sc == "ok" and not cap and c.provider in ("anthropic", "both"):
            b = [r["body"] for r in log]
            check("anthropic path /v1/messages", all(r["path"].endswith("/v1/messages") for r in log))
            check("model claude-haiku-5-5", all(x["model"] == "claude-haiku-5-5" for x in b))
            check("output_config json_schema sent", all(x.get("output_config", {}).get("format", {}).get("type")
                                                        == "json_schema" for x in b))
            check("effort low (extract) + medium (choose)", {x["output_config"]["effort"] for x in b}
                  == {"low", "medium"})
            check("system prompt + max_tokens sent", all(x.get("system") and x.get("max_tokens") for x in b))
        if sc == "ok" and not cap and c.provider == "openai":
            b = [r["body"] for r in log]
            check("openai path /v1/chat/completions", all(r["path"].endswith("/chat/completions") for r in log))
            check("model gpt-5-mini", all(x["model"] == "gpt-5-mini" for x in b))
            check("response_format json_object", all(x.get("response_format") == {"type": "json_object"} for x in b))
            check("reasoning_effort low+medium", {x.get("reasoning_effort") for x in b} == {"low", "medium"})
            check("max_completion_tokens sent", all(x.get("max_completion_tokens") for x in b))
        if sc == "no_output_cfg":
            check("rejection remembered: <= 1 rejected call per worker", st.get(400, 0) <= 8)
            check("retried calls carry no output_config", all("output_config" not in r["body"] for r in ok200))
        if sc == "no_reasoning":
            check("rejection remembered: <= 1 rejected call per worker", st.get(400, 0) <= 8)
            check("successful calls carry no reasoning_effort", all("reasoning_effort" not in r["body"] for r in ok200))
        if sc == "flaky":
            check("SDK retried each failed first attempt", all(r["retry"] >= 1 for r in ok200))
        if sc in ("garbage", "refusal", "auth", "ratelimit") or c.proxy:
            check("output == no-key baseline", same_nokey == 60)
        if sc in ("auth", "ratelimit"):
            check("breaker stopped calls early", len(log) < 120)
        if sc == "expensive":
            check("budget guard stopped calls early", len(log) < 40)
        if sc == "slow":
            check("deadline guard: run ends < 30 s", wall < 30)
            check("some notes LLM, rest no-key", 0 < used < 60 and used + same_nokey >= 58)
        if c.provider == "both":
            check("only anthropic called", all(r["path"].endswith("/v1/messages") for r in log))
        if c.proxy:
            want = "api.anthropic.com:443" if c.provider == "anthropic" else "api.openai.com:443"
            check(f"CONNECT {want} seen by proxy", any(want in r["line"] for r in prx.log))
        if c.live:
            check("server rejected the key (401 in log)", "401" in err or "authentication" in err.lower()
                  or "invalid_api_key" in err)

        bad = [l for l, ok in checks if not ok]
        n_fail += bool(bad)
        tag = "PASS" if not bad else "FAIL"
        info = (f"wall {wall:5.1f}s  requests {len(log) if srv else len(prx.log) if prx else 0:4d}"
                f"  status {dict(sorted(st.items())) if st else '-'}  billed ${billed:.4f}  llm-used {used}/60  =no-key {same_nokey}/60")
        start = len(lines)
        lines.append(f"[{tag}] {'(live) ' if c.live else '(mock) '}{c.name}\n       {info}")
        for l, ok in checks:
            lines.append(f"       {'ok  ' if ok else 'FAIL'} {l}")
        if bad:
            lines.append("       stderr tail: " + " | ".join(err.strip().splitlines()[-4:]))
        print("\n".join(lines[start:] if bad else lines[start:start + 1]), flush=True)
        if srv:
            srv.shutdown()
        if prx:
            prx.shutdown()

    head = (f"tools/mock_test.py  {time.strftime('%Y-%m-%d %H:%M %Z')}  image {IMAGE}  60 dev notes\n"
            f"(mock) = scripted local server, real SDKs in the shipped image; (live) = real endpoint, invalid key.\n"
            f"{len(cases) - n_fail}/{len(cases)} cases pass\n")
    out = head + "\n".join(lines) + "\n"
    if not a.only:
        with open(os.path.join(ROOT, "results/mock_tests.txt"), "w") as f:
            f.write(out)
    print(head)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
