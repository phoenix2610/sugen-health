"""Minimal WHO ICD-API client (build-time only; never used at run time)."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
RELEASE = "2026-01"
BASE = f"https://id.who.int/icd/release/11/{RELEASE}/mms"


def _creds(path=None):
    path = path or os.environ.get("ICD_ENV_FILE", os.path.join(os.path.dirname(__file__), "..", "ICP_API.env"))
    kv = {}
    for line in open(path):
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip().lower()] = v.strip().strip("\"'")
    return kv["clientid"], kv["clientsecret"]


class WHO:
    def __init__(self):
        self.cid, self.secret = _creds()
        self._tok, self._exp = None, 0
        self._lock = threading.Lock()

    def token(self):
        with self._lock:
            if time.time() > self._exp - 120:
                data = urllib.parse.urlencode({
                    "client_id": self.cid, "client_secret": self.secret,
                    "scope": "icdapi_access", "grant_type": "client_credentials"}).encode()
                r = json.load(urllib.request.urlopen(TOKEN_URL, data, timeout=60))
                self._tok, self._exp = r["access_token"], time.time() + int(r.get("expires_in", 3600))
            return self._tok

    def get(self, url, lang="en", tries=6):
        for i in range(tries):
            req = urllib.request.Request(url, headers={
                "Authorization": "Bearer " + self.token(), "API-Version": "v2",
                "Accept-Language": lang, "Accept": "application/json"})
            try:
                return json.load(urllib.request.urlopen(req, timeout=60))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 401:
                    self._exp = 0
                time.sleep(1.5 * (i + 1))
            except Exception:
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"failed: {url} [{lang}]")
