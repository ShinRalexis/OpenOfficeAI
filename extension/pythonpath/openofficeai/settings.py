# -*- coding: utf-8 -*-
# Settings: a JSON file in the office user profile (openofficeai.json).
# Human readable on purpose, so it can still be edited by hand.
from __future__ import unicode_literals

import copy
import io
import json
import os

# Absolute imports on purpose: inside the office, uno's import hook hides the
# real cause of a failed "from ... import" behind a "type ... is unknown" error.
import openofficeai.i18n as i18n

PROVIDERS = ("ollama", "openai", "anthropic")

DEFAULT_SYSTEM_PROMPT = (
    "You are a careful writing assistant working inside a word processor. "
    "Improve clarity while preserving the author's meaning and tone."
)

DEFAULTS = {
    "provider": "ollama",
    "ollama": {
        "host": "http://127.0.0.1:11434",
        "model": "",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-5-mini",
    },
    "anthropic": {
        "api_key": "",
        "model": "claude-opus-5",
    },
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    # Empty: translate into the interface language.
    "translate_to": "",
    # "auto" follows the office UI language; otherwise one of i18n.LANGUAGES.
    "ui_language": "auto",
    # "replace": the result replaces the selection.
    # "after": the selection is kept and the result is inserted below it.
    "output_mode": "replace",
    "timeout": 180,
}

# Suggestions shown in the model lists before "Aggiorna" fetches the live list.
SUGGESTED_MODELS = {
    "ollama": [],
    "openai": ["gpt-5-mini", "gpt-5", "gpt-5-nano"],
    "anthropic": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
}

# Used when the API key field is left empty.
ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

FILE_NAME = "openofficeai.json"


def _merge(base, override):
    """Deep-merge override into a copy of base, keeping only known keys."""
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if key not in out:
            continue
        if isinstance(out[key], dict):
            out[key] = _merge(out[key], value)
        elif isinstance(out[key], int) and not isinstance(out[key], bool):
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                pass
        elif value is not None:
            out[key] = value
    return out


def normalize(data):
    s = _merge(DEFAULTS, data)
    if s["provider"] not in PROVIDERS:
        s["provider"] = DEFAULTS["provider"]
    if s["ui_language"] not in ("auto",) + i18n.LANGUAGES:
        s["ui_language"] = "auto"
    if s["output_mode"] not in ("replace", "after"):
        s["output_mode"] = "replace"
    s["timeout"] = max(10, min(int(s["timeout"]), 1800))
    return s


def load(path):
    """Read settings; a missing or broken file gives the defaults."""
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return normalize(json.load(f))
    except (IOError, OSError, ValueError):
        return normalize({})


def save(path, data):
    text = json.dumps(normalize(data), indent=2, ensure_ascii=False, sort_keys=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text if isinstance(text, type("")) else text.decode("utf-8"))
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def api_key(s, provider):
    key = (s.get(provider, {}).get("api_key") or "").strip()
    if not key and provider in ENV_KEYS:
        key = os.environ.get(ENV_KEYS[provider], "").strip()
    return key


def active_model(s):
    return (s[s["provider"]].get("model") or "").strip()


def provider_label(provider):
    return i18n.tr("provider." + provider)


def describe(s):
    """Short label such as 'Ollama (local) · gpt-oss:20b' for status texts."""
    return "{0} · {1}".format(provider_label(s["provider"]), active_model(s) or "?")
