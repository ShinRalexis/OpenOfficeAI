# -*- coding: utf-8 -*-
# What happens when a toolbar button or menu entry is pressed.
from __future__ import unicode_literals

import os
import re
import threading
import traceback

import uno
from com.sun.star.beans import PropertyValue

# Absolute imports on purpose: inside the office, uno's import hook hides the
# real cause of a failed "from ... import" behind a "type ... is unknown" error.
import openofficeai.dialogs as dialogs
import openofficeai.i18n as i18n
import openofficeai.log as log
import openofficeai.prompts as prompts
import openofficeai.providers as providers
import openofficeai.settings as S

# One request at a time: the UI stays responsive while waiting, so a second
# click must not start a second request on the same selection.
_busy = [False]


def run(ctx, frame, command):
    try:
        _run(ctx, frame, command)
    except Exception:
        log.write("crash in {0}:\n{1}".format(command, traceback.format_exc()))
        dialogs.msgbox(ctx, frame, traceback.format_exc(), "error")


def _run(ctx, frame, command):
    path, s = load_settings(ctx)
    log.write("command {0} ({1})".format(command, S.describe(s)))
    if command == "settings":
        new = dialogs.settings_dialog(ctx, frame, s, path)
        if new:
            apply_language(ctx, new)
        return
    action = prompts.BY_KEY.get(command)
    if action is None:
        return
    if _busy[0]:
        dialogs.msgbox(ctx, frame, i18n.tr("msg.busy"), "warning")
        return

    doc = _document(frame)
    if doc is None:
        dialogs.msgbox(ctx, frame, i18n.tr("msg.no_doc"), "warning")
        return
    rng = _selected_range(doc)
    text = rng.getString() if rng is not None else ""
    if not text.strip():
        dialogs.msgbox(ctx, frame, i18n.tr(action.needs), "warning")
        return

    if not S.active_model(s):
        dialogs.msgbox(ctx, frame, i18n.tr("err.no_model", S.provider_label(s["provider"])), "warning")
        s = dialogs.settings_dialog(ctx, frame, s, path)
        if not s or not S.active_model(s):
            return
        apply_language(ctx, s)

    _busy[0] = True
    try:
        out = _ask(ctx, frame, s, action, text)
        log.write("{0}: {1} chars in, {2} chars out".format(command, len(text), len(out)))
    except Exception as e:
        log.write("{0} failed: {1}".format(command, providers.text_of(e)))
        dialogs.msgbox(ctx, frame, providers.text_of(e), "error")
        return
    finally:
        _busy[0] = False

    if action.output == "synonyms":
        items = providers.split_synonyms(out)
        if not items:
            dialogs.msgbox(ctx, frame, i18n.tr("msg.no_synonyms"), "warning")
            return
        choice = dialogs.pick_synonym(ctx, frame, text.strip(), items)
        if choice:
            _write(ctx, frame, doc, rng, choice, "replace", action.label)
        return

    if action.key == "elenco":
        out = providers.bulletize(out)
    out = _as_paragraphs(out, keep_blank_lines=bool(re.search(r"\n\s*\n", _normalize(text))))
    _write(ctx, frame, doc, rng, out, s["output_mode"], action.label)


# ------------------------------------------------------------ settings ----

def settings_path(ctx):
    subst = ctx.ServiceManager.createInstanceWithContext("com.sun.star.util.PathSubstitution", ctx)
    user_dir = uno.fileUrlToSystemPath(subst.substituteVariables("$(user)", True))
    return os.path.join(user_dir, S.FILE_NAME)


def office_language(ctx):
    try:
        provider = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", ctx)
        arg = PropertyValue()
        arg.Name, arg.Value = "nodepath", "/org.openoffice.Setup/L10N"
        access = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess", (arg,))
        return access.getByName("ooLocale") or "en"
    except Exception:
        return "en"


def apply_language(ctx, s):
    code = s["ui_language"]
    i18n.set_language(office_language(ctx) if code == "auto" else code)


def load_settings(ctx):
    path = settings_path(ctx)
    log.set_path(os.path.join(os.path.dirname(path), "openofficeai.log"))
    s = S.load(path)
    apply_language(ctx, s)
    return path, s


# ------------------------------------------------------------ document ----

def _document(frame):
    try:
        doc = frame.getController().getModel()
    except Exception:
        return None
    if doc is None or not doc.supportsService("com.sun.star.text.TextDocument"):
        return None
    return doc


def _selected_range(doc):
    """First non-empty selected text range, or None (e.g. an image is selected)."""
    sel = doc.getCurrentController().getSelection()
    if sel is None:
        return None
    if sel.supportsService("com.sun.star.text.TextRanges"):
        first = None
        for i in range(sel.getCount()):
            r = sel.getByIndex(i)
            if first is None:
                first = r
            if r.getString().strip():
                return r
        return first
    if sel.supportsService("com.sun.star.text.TextRange") or sel.supportsService(
            "com.sun.star.text.TextCursor"):
        return sel
    return None


def _normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _as_paragraphs(text, keep_blank_lines):
    """Writer splits paragraphs on CR; a plain LF would become a line break."""
    text = _normalize(text).strip("\n")
    if not keep_blank_lines:
        text = re.sub(r"\n\s*\n+", "\n", text)
    return text.replace("\n", "\r")


def _write(ctx, frame, doc, rng, out, mode, label):
    undo = None
    try:
        undo = doc.getUndoManager()
        undo.enterUndoContext(label)
    except Exception:
        undo = None
    try:
        text = rng.getText()
        if mode == "after":
            target = text.createTextCursorByRange(rng.getEnd())
            out = "\r" + out
        else:
            target = text.createTextCursorByRange(rng)
        # absorb=True replaces the range, which then spans the new text.
        text.insertString(target, out, True)
        try:
            doc.getCurrentController().select(target)
        except Exception:
            pass
    except Exception:
        dialogs.msgbox(ctx, frame, i18n.tr("msg.write_failed", out.replace("\r", "\n")), "error")
    finally:
        if undo is not None:
            undo.leaveUndoContext()


# ------------------------------------------------------------- request ----

def _ask(ctx, frame, s, action, text):
    """Run the HTTP request on a worker thread while keeping the office UI alive."""
    box = {}
    system = s["system_prompt"]
    user = action.build(text, s)

    def work():
        try:
            box["out"] = providers.chat(s, system, user)
        except Exception as e:
            box["err"] = e

    worker = threading.Thread(target=work, name="OpenOfficeAI request")
    worker.daemon = True
    worker.start()

    status = None
    try:
        status = frame.createStatusIndicator()
        status.start(i18n.tr("msg.working", action.label, S.describe(s)), 0)
    except Exception:
        status = None
    toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    can_reschedule = hasattr(toolkit, "reschedule")
    try:
        while worker.is_alive():
            if can_reschedule:
                try:
                    toolkit.reschedule()
                except Exception:
                    can_reschedule = False
            worker.join(0.05)
    finally:
        if status is not None:
            status.end()
    if "err" in box:
        raise box["err"]
    return box["out"]
