# -*- coding: utf-8 -*-
# Tests for the uno-free core. Run with both interpreters:
#   python tests/test_core.py
#   "C:\Program Files (x86)\OpenOffice 4\program\python.exe" tests/test_core.py
# Set OOAI_LIVE_OLLAMA=model-name to also run one real request against Ollama.
from __future__ import unicode_literals

import json
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extension", "pythonpath"))

from openofficeai import i18n, prompts, providers, settings as S  # noqa: E402

# Error texts are asserted in Italian below.
i18n.set_language("it")

try:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeServer(object):
    """Tiny local HTTP server that records requests and answers with canned JSON."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                owner.requests.append((self.command, self.path, dict(self.headers.items()),
                                       json.loads(body.decode("utf-8")) if body else None))
                status, data = owner.routes.get((self.command, self.path), (404, {"error": "nope"}))
                if callable(data):
                    data = data(owner.requests[-1])
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = _answer
            do_POST = _answer

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{0}".format(self.httpd.server_address[1])
        t = threading.Thread(target=self.httpd.serve_forever)
        t.daemon = True
        t.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class SettingsTest(unittest.TestCase):
    def test_defaults_and_unknown_keys(self):
        s = S.normalize({"provider": "bogus", "extra": 1, "timeout": "5",
                         "ollama": {"model": "x", "zzz": 2}})
        self.assertEqual(s["provider"], "ollama")
        self.assertNotIn("extra", s)
        self.assertNotIn("zzz", s["ollama"])
        self.assertEqual(s["ollama"]["model"], "x")
        self.assertEqual(s["timeout"], 10)  # clamped

    def test_roundtrip_unicode(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "s.json")
        s = S.normalize({"system_prompt": "Perché è così? \u2022", "provider": "anthropic"})
        S.save(path, s)
        S.save(path, s)  # overwrite must work on Windows too
        self.assertEqual(S.load(path), s)

    def test_broken_file_gives_defaults(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "s.json")
        with open(path, "wb") as f:
            f.write(b"{not json")
        self.assertEqual(S.load(path), S.normalize({}))

    def test_env_key_fallback(self):
        os.environ["ANTHROPIC_API_KEY"] = "env-key"
        try:
            self.assertEqual(S.api_key(S.normalize({}), "anthropic"), "env-key")
            s = S.normalize({"anthropic": {"api_key": " typed "}})
            self.assertEqual(S.api_key(s, "anthropic"), "typed")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


class PromptsTest(unittest.TestCase):
    def test_seven_actions(self):
        self.assertEqual([a.key for a in prompts.ACTIONS],
                         ["migliora", "editing", "riassunto", "traduci", "elenco", "spiega", "sinonimi"])

    def test_translate_language(self):
        p = prompts.BY_KEY["traduci"].build("hello", S.normalize({"translate_to": "Deutsch"}))
        self.assertIn("into Deutsch", p)
        self.assertIn("hello", p)
        self.assertNotIn(prompts.SAME_LANGUAGE, p)
        # Empty target: the interface language.
        p = prompts.BY_KEY["traduci"].build("hello", S.normalize({}))
        self.assertIn("into Italiano", p)

    def test_paragraph_rule_only_for_multi_paragraph_text(self):
        a = prompts.BY_KEY["editing"]
        self.assertIn(prompts.SAME_PARAGRAPHS, a.build("uno\r\ndue", S.normalize({})))
        self.assertNotIn(prompts.SAME_PARAGRAPHS, a.build("uno", S.normalize({})))
        self.assertNotIn(prompts.SAME_PARAGRAPHS,
                         prompts.BY_KEY["riassunto"].build("uno\ndue", S.normalize({})))

    def test_other_actions_keep_language(self):
        p = prompts.BY_KEY["migliora"].build("ciao", S.normalize({}))
        self.assertIn(prompts.SAME_LANGUAGE, p)
        self.assertIn("ciao", p)

    def test_no_long_dashes(self):
        texts = [a.task for a in prompts.ACTIONS]
        for table in i18n.STRINGS.values():
            texts.extend(table.values())
        for t in texts:
            self.assertNotIn("\u2014", t)
            self.assertNotIn("\u2013", t)


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("it")

    def test_every_language_is_complete(self):
        keys = set(i18n.STRINGS["en"])
        for lang in i18n.LANGUAGES:
            self.assertEqual(set(i18n.STRINGS[lang]), keys, lang)

    def test_language_codes(self):
        self.assertEqual(i18n.set_language("de-DE"), "de")
        self.assertEqual(i18n.set_language("pt-BR"), "en")


class CleanupTest(unittest.TestCase):
    def test_think_and_fence(self):
        self.assertEqual(providers.clean_output("<think>hmm</think>\n\nCiao"), "Ciao")
        self.assertEqual(providers.clean_output("```text\nCiao\n```"), "Ciao")
        self.assertEqual(providers.clean_output("<think>never closed"), "")

    def test_synonyms(self):
        self.assertEqual(providers.split_synonyms("1. bello, - carino;\n\u2022 Bello, grazioso."),
                         ["bello", "carino", "grazioso"])

    def test_bulletize(self):
        self.assertEqual(providers.bulletize("- a\n* b\n  + c\nd"), "\u2022 a\n\u2022 b\n  \u2022 c\nd")


class ProvidersTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer({
            ("POST", "/api/chat"): (200, {"message": {"content": "<think>x</think>Ciao!"}}),
            ("GET", "/api/tags"): (200, {"models": [{"name": "gemma3:12b"}, {"name": "bge-m3:latest"},
                                                    {"name": "nomic-embed-text:latest"}, {"name": "a:1"}]}),
            ("POST", "/v1/chat/completions"): (200, {"choices": [{"message": {"content": "Ok"}}]}),
            ("GET", "/v1/models"): (200, {"data": [{"id": "local-model"}]}),
        })
        self.s = S.normalize({
            "ollama": {"host": self.srv.url, "model": "gemma3:12b"},
            "openai": {"base_url": self.srv.url + "/v1", "api_key": "sk-test", "model": "m"},
        })

    def tearDown(self):
        self.srv.close()

    def test_ollama_chat(self):
        out = providers.chat(self.s, "SYS", "USER")
        self.assertEqual(out, "Ciao!")
        method, path, headers, body = self.srv.requests[-1]
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})
        self.assertFalse(body["stream"])

    def test_ollama_models_skip_embeddings(self):
        self.assertEqual(providers.list_models(self.s, "ollama"), ["a:1", "gemma3:12b"])

    def test_openai_compatible(self):
        self.s["provider"] = "openai"
        self.assertEqual(providers.chat(self.s, "SYS", "U"), "Ok")
        headers = self.srv.requests[-1][2]
        auth = dict((k.lower(), v) for k, v in headers.items())["authorization"]
        self.assertEqual(auth, "Bearer sk-test")
        self.assertEqual(providers.list_models(self.s, "openai"), ["local-model"])

    def test_missing_model_and_key(self):
        self.s["ollama"]["model"] = ""
        self.assertRaises(providers.AIError, providers.chat, self.s, "", "x")
        self.s["provider"] = "anthropic"
        self.s["anthropic"]["api_key"] = ""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with self.assertRaises(providers.AIError) as cm:
            providers.chat(self.s, "", "x")
        self.assertIn("API key", cm.exception.text)

    def test_http_error_is_readable(self):
        self.s["ollama"]["host"] = self.srv.url + "/missing"
        with self.assertRaises(providers.AIError) as cm:
            providers.chat(self.s, "", "x")
        self.assertIn("404", cm.exception.text)

    def test_connection_refused(self):
        self.s["ollama"]["host"] = "http://127.0.0.1:9"
        with self.assertRaises(providers.AIError) as cm:
            providers.list_models(self.s, "ollama", timeout=3)
        self.assertIn("Connessione non riuscita", cm.exception.text)


class AnthropicTest(unittest.TestCase):
    """Anthropic request shape, served by the fake server via a patched base URL."""

    def setUp(self):
        self.calls = []

        def answer(req):
            body = req[3]
            if body.get("fallbacks") and self.reject_fallback:
                return {"type": "error", "error": {"message": "fallbacks: not supported"}}
            return {"type": "message", "stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "Risposta"}]}

        self.reject_fallback = False
        self.srv = FakeServer({("POST", "/v1/messages"): (200, answer),
                               ("GET", "/v1/models?limit=100"): (200, {"data": [{"id": "claude-opus-5"}]})})
        self.old = providers.ANTHROPIC_URL
        providers.ANTHROPIC_URL = self.srv.url + "/v1"
        self.s = S.normalize({"provider": "anthropic", "anthropic": {"api_key": "k", "model": "claude-opus-5"}})

    def tearDown(self):
        providers.ANTHROPIC_URL = self.old
        self.srv.close()

    def test_request_shape(self):
        self.assertEqual(providers.chat(self.s, "SYS", "U"), "Risposta")
        _, _, headers, body = self.srv.requests[-1]
        h = dict((k.lower(), v) for k, v in headers.items())
        self.assertEqual(h["x-api-key"], "k")
        self.assertEqual(h["anthropic-version"], "2023-06-01")
        self.assertEqual(h["anthropic-beta"], providers.ANTHROPIC_FALLBACK_BETA)
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["system"], "SYS")
        self.assertEqual(body["max_tokens"], providers.ANTHROPIC_MAX_TOKENS)

    def test_no_fallback_for_haiku(self):
        self.s["anthropic"]["model"] = "claude-haiku-4-5"
        providers.chat(self.s, "", "U")
        _, _, headers, body = self.srv.requests[-1]
        self.assertNotIn("fallbacks", body)
        self.assertNotIn("anthropic-beta", dict((k.lower(), v) for k, v in headers.items()))

    def test_refusal(self):
        self.srv.routes[("POST", "/v1/messages")] = (200, {
            "type": "message", "stop_reason": "refusal", "content": [],
            "stop_details": {"type": "refusal", "category": "cyber", "explanation": "no"}})
        with self.assertRaises(providers.AIError) as cm:
            providers.chat(self.s, "", "U")
        self.assertIn("rifiutato", cm.exception.text)

    def test_fallback_rejected_retries_plain(self):
        # The server rejects the fallback request with a 400; the plain retry is
        # answered by the patched _request below.
        self.srv.routes[("POST", "/v1/messages")] = (
            400, {"type": "error", "error": {"message": "fallbacks: unsupported"}})
        orig = providers._request

        def patched(method, url, payload=None, headers=None, timeout=60):
            if payload and "fallbacks" not in payload:
                return {"type": "message", "stop_reason": "end_turn", "content": [{"type": "text", "text": "plain"}]}
            return orig(method, url, payload, headers, timeout)

        providers._request = patched
        try:
            self.assertEqual(providers.chat(self.s, "", "U"), "plain")
        finally:
            providers._request = orig

    def test_models(self):
        self.assertEqual(providers.list_models(self.s, "anthropic"), ["claude-opus-5"])


@unittest.skipUnless(os.environ.get("OOAI_LIVE_OLLAMA"), "set OOAI_LIVE_OLLAMA=model to run")
class LiveOllamaTest(unittest.TestCase):
    def test_real_request(self):
        s = S.normalize({"ollama": {"model": os.environ["OOAI_LIVE_OLLAMA"]}})
        a = prompts.BY_KEY["editing"]
        out = providers.chat(s, s["system_prompt"], a.build("Qvesto testo a degli errori.", s))
        print("\nLIVE:", out)
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
