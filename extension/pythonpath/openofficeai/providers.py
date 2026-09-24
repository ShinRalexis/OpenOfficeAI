# -*- coding: utf-8 -*-
# HTTP clients for Ollama, OpenAI and Anthropic.
# Plain urllib (urllib2 on the Python 2.7 bundled with OpenOffice), no SDKs:
# the office Python cannot install packages.
from __future__ import unicode_literals

import json
import os
import re
import sys


def _import_ssl():
    """Import ssl, helping Apache OpenOffice on Windows find its OpenSSL DLLs.

    AOO keeps libeay32.dll and ssleay32.dll in its program folder. The office
    process does not search that folder when Python loads _ssl.pyd, so the
    first import fails with "DLL load failed"; putting the folder on PATH fixes
    it. Without ssl only HTTPS (OpenAI, Anthropic) is unavailable.
    """
    try:
        import ssl
        return ssl
    except ImportError:
        pass
    if os.name != "nt":
        return None
    # <program>/python-core-2.7.18/lib/os.py -> <program>
    program = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(os.__file__))))
    if not os.path.exists(os.path.join(program, "libeay32.dll")):
        return None
    os.environ["PATH"] = program + os.pathsep + os.environ.get("PATH", "")
    sys.modules.pop("ssl", None)
    try:
        import ssl
        return ssl
    except ImportError:
        return None


ssl = _import_ssl()

try:  # Python 2.7 (Apache OpenOffice)
    import urllib2 as _url
    from urllib2 import URLError, HTTPError
except ImportError:  # Python 3 (LibreOffice)
    import urllib.request as _url
    from urllib.error import URLError, HTTPError

try:
    import socket
    _TIMEOUT_ERRORS = (socket.timeout,)
except ImportError:  # pragma: no cover
    _TIMEOUT_ERRORS = ()

# Absolute imports on purpose: inside the office, uno's import hook hides the
# real cause of a failed "from ... import" behind a "type ... is unknown" error.
import openofficeai.i18n as i18n
import openofficeai.settings as S

ANTHROPIC_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
# Server-side refusal fallback (Claude API beta): a request declined by the
# model's safety classifier is re-run on Anthropic's recommended model.
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ANTHROPIC_FALLBACK_MODELS = ("claude-opus-5", "claude-opus-5-5", "claude-fable-5", "claude-fable-5-1")
ANTHROPIC_MAX_TOKENS = 16000

USER_AGENT = "OpenOfficeAI/2.0"


class AIError(Exception):
    """Error with a message meant for the user (always text, never bytes)."""

    def __init__(self, message):
        Exception.__init__(self, message)
        self.text = message

    def __str__(self):  # Python 3
        return self.text

    def __unicode__(self):  # Python 2
        return self.text


def text_of(exc):
    """Readable text for any exception, on Python 2 and 3."""
    if isinstance(exc, AIError):
        return exc.text
    for attr in ("reason", "msg", "strerror"):
        value = getattr(exc, attr, None)
        if value:
            return _to_text(value)
    try:
        return _to_text(exc.args[0]) if exc.args else exc.__class__.__name__
    except Exception:
        return exc.__class__.__name__


def _to_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, type("")):
        return value
    try:
        return type("")(value)
    except Exception:
        return repr(value)


# ---------------------------------------------------------------- HTTP ----

def _ssl_context():
    try:
        return ssl.create_default_context()
    except AttributeError:  # very old Python: no context support
        return None


def _check_https(url):
    if url.startswith("https://") and ssl is None:
        raise AIError(i18n.tr("err.no_ssl", _host_of(url)))


def _request(method, url, payload=None, headers=None, timeout=60):
    _check_https(url)
    body = None
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    req = _url.Request(url, data=body, headers=all_headers)
    req.get_method = lambda: method
    kwargs = {"timeout": timeout}
    if url.startswith("https://"):
        ctx = _ssl_context()
        if ctx is not None:
            kwargs["context"] = ctx
    try:
        resp = _url.urlopen(req, **kwargs)
        try:
            raw = resp.read()
        finally:
            resp.close()
    except HTTPError as e:
        raise AIError(_http_error_text(e))
    except _TIMEOUT_ERRORS:
        raise AIError(i18n.tr("err.timeout", timeout))
    except URLError as e:
        reason = text_of(e)
        if "timed out" in reason:
            raise AIError(i18n.tr("err.timeout", timeout))
        raise AIError(i18n.tr("err.connect", _host_of(url), reason))
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise AIError(i18n.tr("err.not_json", _host_of(url)))


def _host_of(url):
    m = re.match(r"^(https?://[^/]+)", url)
    return m.group(1) if m else url


def _http_error_text(e):
    code = getattr(e, "code", "?")
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        body = ""
    detail = body
    try:
        data = json.loads(body)
        err = data.get("error", data)
        if isinstance(err, dict):
            detail = err.get("message") or json.dumps(err)
        elif err:
            detail = _to_text(err)
    except ValueError:
        pass
    parts = [i18n.tr("err.http", code)]
    if code in (401, 403, 404, 429):
        parts.append(i18n.tr("err.http{0}".format(code)))
    if detail:
        parts.append(detail[:600])
    return "\n".join(parts)


# ------------------------------------------------------------ cleanup ----

_THINK_RE = re.compile(r"<(think|thinking)>.*?</\1>", re.S | re.I)
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*)\n```\s*$", re.S)


def clean_output(text):
    """Remove reasoning blocks and a code fence wrapping the whole answer."""
    text = _THINK_RE.sub("", text or "").strip()
    # A model that stops mid-thought leaves an unterminated block and no answer.
    if text.lower().startswith("<think>"):
        text = ""
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    return text


def split_synonyms(text):
    items = []
    for part in re.split(r"[,;\n]", clean_output(text)):
        part = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", part).strip().strip(".\"'")
        if part and part.lower() not in [i.lower() for i in items]:
            items.append(part)
    return items


def bulletize(text):
    """Turn Markdown-style list markers into real bullet characters."""
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"^(\s*)(?:[-*+]|\u2022)\s+", "\\1\u2022 ", line))
    return "\n".join(lines)


# --------------------------------------------------------------- chat ----

def chat(s, system, user):
    """Send one request to the active provider and return the answer text."""
    provider = s["provider"]
    model = S.active_model(s)
    if not model:
        raise AIError(i18n.tr("err.no_model", S.provider_label(provider)))
    timeout = s["timeout"]
    if provider == "ollama":
        out = _chat_ollama(s["ollama"], model, system, user, timeout)
    elif provider == "openai":
        out = _chat_openai(s, model, system, user, timeout)
    else:
        out = _chat_anthropic(s, model, system, user, timeout)
    out = clean_output(out)
    if not out:
        raise AIError(i18n.tr("err.empty"))
    return out


def _chat_ollama(cfg, model, system, user, timeout):
    url = cfg["host"].rstrip("/") + "/api/chat"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    data = _request("POST", url, {"model": model, "messages": messages, "stream": False},
                    timeout=timeout)
    if data.get("error"):
        raise AIError("Ollama: {0}".format(data["error"]))
    return (data.get("message") or {}).get("content", "")


def _require_key(s, provider):
    key = S.api_key(s, provider)
    if not key:
        raise AIError(i18n.tr("err.no_key", S.provider_label(provider)))
    return key


def _chat_openai(s, model, system, user, timeout):
    key = _require_key(s, "openai")
    url = s["openai"]["base_url"].rstrip("/") + "/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    data = _request("POST", url, {"model": model, "messages": messages},
                    headers={"Authorization": "Bearer " + key}, timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise AIError(i18n.tr("err.no_content", "OpenAI"))
    msg = choices[0].get("message") or {}
    if msg.get("refusal"):
        raise AIError(i18n.tr("err.refused", "OpenAI") + "\n" + msg["refusal"])
    return msg.get("content") or ""


def _anthropic_headers(key, beta=None):
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if beta:
        headers["anthropic-beta"] = beta
    return headers


def _chat_anthropic(s, model, system, user, timeout):
    key = _require_key(s, "anthropic")
    payload = {
        "model": model,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        payload["system"] = system
    url = ANTHROPIC_URL + "/messages"
    if model in ANTHROPIC_FALLBACK_MODELS:
        fb = dict(payload, fallbacks="default")
        try:
            data = _request("POST", url, fb, _anthropic_headers(key, ANTHROPIC_FALLBACK_BETA), timeout)
        except AIError as e:
            # If the beta is not accepted for this account/model, retry plainly.
            if "400" not in e.text or "fallback" not in e.text.lower():
                raise
            data = _request("POST", url, payload, _anthropic_headers(key), timeout)
    else:
        data = _request("POST", url, payload, _anthropic_headers(key), timeout)

    if data.get("type") == "error":
        raise AIError("Anthropic: {0}".format((data.get("error") or {}).get("message", "error")))
    if data.get("stop_reason") == "refusal":
        details = data.get("stop_details") or {}
        why = details.get("explanation") or details.get("category") or ""
        raise AIError(i18n.tr("err.refused", "Claude") + ("\n" + why if why else ""))
    parts = [b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text"]
    return "".join(parts)


# ------------------------------------------------------------- models ----

_OLLAMA_SKIP = ("embed", "bge-", "bge:", "minilm", "rerank")
_OPENAI_KEEP = re.compile(r"^(gpt-|o\d|chatgpt-)")
_OPENAI_SKIP = ("audio", "realtime", "transcribe", "tts", "image", "search", "embedding",
                "instruct", "moderation", "codex", "computer-use")


def list_models(s, provider, timeout=15):
    """Model ids usable for text generation, best guess first."""
    if provider == "ollama":
        url = s["ollama"]["host"].rstrip("/") + "/api/tags"
        data = _request("GET", url, timeout=timeout)
        names = [m.get("name") or m.get("model") for m in data.get("models") or []]
        return sorted(n for n in names if n and not any(k in n.lower() for k in _OLLAMA_SKIP))
    if provider == "openai":
        key = _require_key(s, "openai")
        url = s["openai"]["base_url"].rstrip("/") + "/models"
        data = _request("GET", url, headers={"Authorization": "Bearer " + key}, timeout=timeout)
        ids = [m.get("id", "") for m in data.get("data") or []]
        official = "api.openai.com" in s["openai"]["base_url"]
        if official:
            ids = [i for i in ids if _OPENAI_KEEP.match(i) and not any(k in i for k in _OPENAI_SKIP)]
        return sorted(set(ids), reverse=official)
    if provider == "anthropic":
        key = _require_key(s, "anthropic")
        data = _request("GET", ANTHROPIC_URL + "/models?limit=100", headers=_anthropic_headers(key),
                        timeout=timeout)
        # The API lists newest first; keep that order.
        return [m.get("id") for m in data.get("data") or [] if m.get("id")]
    raise AIError("Unknown provider: {0}".format(provider))


def test_connection(s, provider):
    """Check that the provider answers and the chosen model exists."""
    models = list_models(s, provider)
    model = (s[provider].get("model") or "").strip()
    label = S.provider_label(provider)
    if not model:
        return i18n.tr("test.ok_no_model", label, len(models))
    if models and model not in models:
        return i18n.tr("test.model_missing", label, model, len(models))
    return i18n.tr("test.ok", label, model)
