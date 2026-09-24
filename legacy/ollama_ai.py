# Ollama AI Macro for OpenOffice / LibreOffice
# Author: (MetaDarko)
# Year: 2025
# License: Apache 2.0
#
# This macro connects OpenOffice Writer to local Ollama models.
# It is an independent project and not affiliated with Apache Software Foundation.
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import json

# Compatibility: AOO uses Python 2.7 (urllib2); on LO/Python3 it falls back to urllib.request
try:
    import urllib2 as _url
    from urllib2 import URLError, HTTPError
except ImportError:
    import urllib.request as _url
    from urllib.error import URLError, HTTPError

from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
from com.sun.star.awt.MessageBoxType import MESSAGEBOX, WARNINGBOX, ERRORBOX

# === Basic settings (editable) ===
SETTINGS = {
    "host": "http://127.0.0.1:11434",
    "model": "gemma3:12b",
    "mode": "generate",  # "generate" or "chat"
    "system_prompt": "You are an Italian assistant: improve the clarity of texts while maintaining their meaning and tone.",
    "timeout": 180,  # seconds (fix #6: configurable timeout; default was 120)
    # If True, prepend system_prompt to user prompt even when using /api/generate (optional behavior)
    "prepend_system_to_generate": False
}

# --- UI ---
def _mbox(ctx, text, title="Ollama AI", box=MESSAGEBOX):
    """
    Robust message box (fix #1): gracefully handles missing current frame/window.
    """
    smgr = ctx.ServiceManager
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    frame = desktop.getCurrentFrame() if desktop else None
    window = frame.getContainerWindow() if frame else None
    # Fallback to desktop window if needed
    if window is None:
        try:
            window = toolkit.getDesktopWindow()
        except:
            window = None
    mb = toolkit.createMessageBox(window, box, BUTTONS_OK, title, text)
    mb.execute()

# --- HTTP helper with clear error messages ---
def _http_post_json(url, payload, timeout=None):
    """
    Sends a JSON POST and returns parsed JSON.
    Uses SETTINGS['timeout'] if timeout is None. Adds robust JSON error reporting.
    """
    if timeout is None:
        timeout = SETTINGS.get("timeout", 120)
    data = json.dumps(payload).encode('utf-8')
    req = _url.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = _url.urlopen(req, timeout=timeout)
        try:
            raw = resp.read()
        finally:
            try:
                resp.close()
            except:
                pass
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception as je:
            # More informative error if Ollama returns non-JSON (fix: robust JSON handling)
            raise URLError("Invalid JSON from Ollama: {}".format(je))
    except HTTPError as e:
        try:
            body = e.read().decode('utf-8', 'replace')
        except:
            body = str(e)
        # Keep details for diagnostics
        raise URLError("HTTP {} {}\n{}".format(getattr(e, "code", "?"),
                                              getattr(e, "reason", ""), body[:500]))
    except URLError as e:
        raise

# --- Selection / insertion ---
def _get_selection(doc):
    sel = doc.getCurrentController().getSelection()
    try:
        rng = sel.getByIndex(0)
    except:
        rng = sel
    return rng

def _get_selection_text(doc):
    rng = _get_selection(doc)
    try:
        return rng.getString(), rng
    except:
        return "", None

def _replace(rng, text):
    """
    Safer replacement (fix #4): try setString; if it fails (e.g., protected areas),
    attempt a true replace via cursor; finally, fall back to insert near selection.
    """
    try:
        rng.setString(text)
        return
    except:
        pass
    try:
        t = rng.getText()
        c = t.createTextCursorByRange(rng)
        # True = replace selection contents
        t.insertString(c, text, True)
        return
    except:
        pass
    try:
        cursor = rng.getText().createTextCursor()
        rng.getText().insertString(cursor, text, False)
    except:
        # Last resort: ignore if even insert fails
        raise

# --- Call to Ollama ---
def _ask_ollama(user_prompt):
    host = SETTINGS["host"].rstrip('/')
    model = SETTINGS["model"]
    sys = SETTINGS["system_prompt"]
    mode = SETTINGS.get("mode", "generate")

    if mode == "chat":
        url = host + "/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": sys},
                         {"role": "user", "content": user_prompt}],
            "stream": False
        }
        data = _http_post_json(url, payload)
        return data.get("message", {}).get("content", "")
    else:
        url = host + "/api/generate"
        prompt = user_prompt
        if SETTINGS.get("prepend_system_to_generate"):
            if sys:
                prompt = sys + "\n\n" + user_prompt
        payload = {"model": model, "prompt": prompt, "stream": False}
        data = _http_post_json(url, payload)
        return data.get("response", "")

# --- Specialized prompts ---
def _prompt_migliora(text):
    return (
        SETTINGS["system_prompt"] + "\n\n"
        "GOAL: Improve form, fluency, and cohesion of the highlighted text "
        "without changing its meaning. Maintain tone, register, and information. "
        "Integrate implicit context. Avoid embellishments.\n\n"
        "TEXT:\n" + text + "\n\n"
        "RESULT (text only, no comments):"
    )

def _prompt_editing(text):
    return (
        SETTINGS["system_prompt"] + "\n\n"
        "GOAL: MINIMAL professional editing. Correct only evident errors "
        "(spelling, punctuation, agreement, syntax). Do not change style or authorial voice. "
        "Reduce obvious redundancies without wide rewrites. Keep similar length.\n\n"
        "TEXT:\n" + text + "\n\n"
        "RESULT (text only, no comments):"
    )

def _prompt_riassunto(text):
    return (
        "GOAL: Summarize the following text in Italian while keeping the key information. "
        "Clear and compact style (3–5 sentences if possible). No comments, no titles.\n\n"
        "TEXT:\n" + text + "\n\n"
        "SUMMARY:"
    )

def _prompt_traduci_it(text):
    return (
        "TRANSLATE INTO ITALIAN the following text, maintaining meaning, tone, and nuances. "
        "Avoid notes, explanations, or introductions. Return only the Italian translation.\n\n"
        "TEXT:\n" + text + "\n\n"
        "TRANSLATION (Italian):"
    )

def _prompt_bullets(text):
    return (
        "GOAL: Convert the following text into a bulleted list in Italian, "
        "with clear and concise points (max one line each). No preamble.\n\n"
        "TEXT:\n" + text + "\n\n"
        "BULLETED LIST:"
    )

def _prompt_spiega(text):
    return (
        "GOAL: Explain the text in Italian as if speaking to a non-expert reader. "
        "Use simple examples, concrete analogies, and short sentences. "
        "Avoid jargon; define technical terms if they appear. "
        "Do not add preambles or comments; return only the explanation.\n\n"
        "TEXT:\n" + text + "\n\n"
        "SIMPLE EXPLANATION:"
    )

# >>> New prompt: SYNONYMS <<<
def _prompt_sinonimi(text):
    return (
        "GOAL: Provide synonyms and expressive alternatives for the following phrase, "
        "keeping the same register (formal/informal) and the same language as the source text. "
        "If the phrase is an idiom, provide equivalent paraphrases. "
        "Avoid explanations or comments: return only a single line with 6–12 proposals, "
        "separated by commas, without numbers or dashes.\n\n"
        "PHRASE:\n" + text + "\n\n"
        "RESULT (one line, items separated by commas):"
    )

# --- Macro: IMPROVE ---
def ai_migliora_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_migliora(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# --- Macro: EDITING ---
def ai_editing_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_editing(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# --- Macro: SUMMARY ---
def ai_riassunto_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_riassunto(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# --- Macro: TRANSLATE TO ITALIAN ---
def ai_traduci_it_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_traduci_it(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# --- Macro: BULLET POINTS ---
def ai_bullets_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_bullets(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# --- Macro: EXPLAIN / DIDACTIC ---
def ai_spiega_replace(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select some text.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_spiega(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _replace(rng, out)
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# >>> New macro: SYNONYMS (shows popup, does not modify text) <<<
def ai_sinonimi_show(*args):
    ctx = XSCRIPTCONTEXT.getComponentContext()
    smgr = ctx.ServiceManager
    doc = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentComponent()
    if not doc:
        _mbox(ctx, "No active document.", box=WARNINGBOX); return
    text, rng = _get_selection_text(doc)
    if not text:
        _mbox(ctx, "Select a word or phrase.", box=WARNINGBOX); return
    try:
        out = _ask_ollama(_prompt_sinonimi(text))
        if not out:
            _mbox(ctx, "Empty response from model.", box=ERRORBOX); return
        _mbox(ctx, out.strip(), title="Synonyms / Alternatives")
    except URLError as e:
        _mbox(ctx, "Cannot contact Ollama:\n{0}".format(e), box=ERRORBOX)
    except Exception as e:
        _mbox(ctx, "Error: {0}".format(e), box=ERRORBOX)

# Export all macros
g_exportedScripts = (
    ai_migliora_replace,
    ai_editing_replace,
    ai_riassunto_replace,
    ai_traduci_it_replace,
    ai_bullets_replace,
    ai_spiega_replace,
    ai_sinonimi_show
)
