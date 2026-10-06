"""Engine clients: each turns a consumer's question into an Answer (text plus the sources it cited)."""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
ANTHROPIC_DEFAULTS = {"model": "claude-sonnet-5-5", "web_search": True, "max_searches": 4, "max_tokens": 2000,
                      "tool_version": "web_search_20250305", "country": ""}


class EngineError(Exception):
    """One question failed; the run carries on with the next."""


class AuthError(EngineError):
    """The key or permissions are wrong. Every question would fail, so the run stops."""


@dataclass
class Answer:
    text: str
    citations: list
    model: str = ""
    searches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    warnings: list = field(default_factory=list)


def http_post(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8")), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            data = {}
        return e.code, data, {k.lower(): v for k, v in e.headers.items()}


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


class AnthropicEngine:
    """Claude through the Messages API, with the web search tool so answers draw on live results."""

    def __init__(self, engine_id, settings=None, system=None, post=http_post, sleep=time.sleep, api_key=None, retries=3, timeout=180):
        self.id, self.system, self.post, self.sleep = engine_id, system, post, sleep
        self.api_key, self.retries, self.timeout = api_key, retries, timeout
        self.s = {**ANTHROPIC_DEFAULTS, **{k: v for k, v in (settings or {}).items() if k != "provider" and v is not None}}

    @property
    def location(self):
        return (self.s.get("country") or "").upper()

    def check(self):
        import os

        if not (self.api_key or os.environ.get("ANTHROPIC_API_KEY")):
            raise AuthError("No API key. Set the ANTHROPIC_API_KEY environment variable.")

    def _tool(self):
        tool = {"type": self.s["tool_version"], "name": "web_search", "max_uses": int(self.s["max_searches"])}
        if self.s["tool_version"] != "web_search_20250305":
            tool["allowed_callers"] = ["direct"]  # newer versions otherwise route search through code execution
        if self.location:
            tool["user_location"] = {"type": "approximate", "country": self.location}
        return tool

    def _call(self, body):
        import os

        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise AuthError("No API key. Set the ANTHROPIC_API_KEY environment variable.")
        headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        url = self.s.get("api_url") or API_URL
        for attempt in range(self.retries + 1):
            try:
                status, data, hdr = self.post(url, headers, body, self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt == self.retries:
                    raise EngineError(f"Could not reach the API: {e}") from None
                self.sleep(2 * 2 ** attempt)
                continue
            if status == 200:
                return data
            msg = ((data or {}).get("error") or {}).get("message") or f"HTTP {status}"
            if status in (401, 403):
                raise AuthError(f"{status}: {msg}")
            if status in (429, 500, 502, 503, 504, 529) and attempt < self.retries:
                try:
                    wait = float(hdr.get("retry-after"))
                except (TypeError, ValueError):
                    wait = 5 * 2 ** attempt
                self.sleep(min(wait, 120))
                continue
            hint = ""
            if status == 400 and "web search" in msg.lower():
                hint = " An administrator may need to enable web search in the Claude Console, or set web_search: false for this engine."
            elif status == 404:
                hint = " Check the model name under this engine in config/research.yaml."
            raise EngineError(f"{status}: {msg}{hint}")
        raise EngineError("Gave up after repeated errors")

    def ask(self, question):
        messages = [{"role": "user", "content": question}]
        base = {"model": self.s["model"], "max_tokens": int(self.s["max_tokens"])}
        if self.system:
            base["system"] = self.system
        if self.s["web_search"]:
            base["tools"] = [self._tool()]
        text, gap, cited, found, warnings = "", False, [], [], []
        searches = tokens_in = tokens_out = 0
        model = self.s["model"]
        for _ in range(5):  # a long search can pause the turn; send it back unchanged to carry on
            resp = self._call({**base, "messages": list(messages)})
            usage = resp.get("usage") or {}
            tokens_in += usage.get("input_tokens") or 0
            tokens_out += usage.get("output_tokens") or 0
            searches += (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
            model = resp.get("model") or model
            blocks = resp.get("content") or []
            for b in blocks:
                kind = b.get("type")
                if kind == "text":
                    text += ("\n\n" if gap and text else "") + (b.get("text") or "")
                    gap = False
                    for c in b.get("citations") or []:
                        if c.get("url"):
                            cited.append({"url": c["url"], "title": c.get("title") or ""})
                else:
                    gap = True
                    if kind == "web_search_tool_result":
                        content = b.get("content")
                        if isinstance(content, dict):
                            warnings.append(content.get("error_code") or "search error")
                        else:
                            found += [{"url": r["url"], "title": r.get("title") or ""} for r in content or [] if r.get("url")]
            if resp.get("stop_reason") == "pause_turn":
                messages.append({"role": "assistant", "content": blocks})
                continue
            if resp.get("stop_reason") == "max_tokens":
                warnings.append("answer was cut off at max_tokens")
            break
        else:
            raise EngineError("The engine kept pausing. Try again.")
        if not text.strip():
            raise EngineError("The engine returned no text")
        return Answer(text.strip(), _dedupe(cited) or _dedupe(found), model, searches, tokens_in, tokens_out, warnings)


PROVIDERS = {"anthropic": AnthropicEngine}


def make_engine(engine_id, api=None, system=None, model=None, **kw):
    api = dict(api or {})
    provider = api.get("provider") or ("anthropic" if engine_id == "claude" else None)
    if provider not in PROVIDERS:
        raise EngineError(f"The engine '{engine_id}' has no API settings yet. Runnable so far: claude. "
                          "More can be added in runner/engines.py.")
    if model:
        api["model"] = model
    return PROVIDERS[provider](engine_id, api, system=system, **kw)
