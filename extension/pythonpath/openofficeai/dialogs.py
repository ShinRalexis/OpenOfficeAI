# -*- coding: utf-8 -*-
# Dialogs built in code (no .xdl files): message boxes, settings, synonyms.
from __future__ import unicode_literals

import copy

import unohelper
from com.sun.star.awt import XActionListener
from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
from com.sun.star.awt.MessageBoxType import ERRORBOX, INFOBOX, WARNINGBOX

# Absolute imports on purpose: inside the office, uno's import hook hides the
# real cause of a failed "from ... import" behind a "type ... is unknown" error.
import openofficeai.i18n as i18n
import openofficeai.log as log
import openofficeai.providers as providers
import openofficeai.settings as S

OK, CANCEL = 1, 2  # PushButtonType values


def _parent(ctx, frame):
    if frame is None:
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        frame = desktop.getCurrentFrame()
    return frame.getContainerWindow() if frame is not None else None


def msgbox(ctx, frame, text, kind="info", title=None):
    log.write("message box ({0}): {1}".format(kind, text.replace("\n", " | ")[:300]))
    toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
    box_type = {"info": INFOBOX, "warning": WARNINGBOX, "error": ERRORBOX}[kind]
    if title is None:
        title = i18n.tr("msg.error_title" if kind == "error" else "msg.title")
    box = toolkit.createMessageBox(_parent(ctx, frame), box_type, BUTTONS_OK, title, text)
    box.execute()
    box.dispose()


class _OnAction(unohelper.Base, XActionListener):
    """Button click (or list double click) that runs fn and reports errors."""

    def __init__(self, fn, on_error):
        self.fn = fn
        self.on_error = on_error

    def actionPerformed(self, event):
        try:
            self.fn()
        except Exception as e:
            self.on_error(e)

    def disposing(self, event):
        pass


class Form(object):
    """A modal dialog laid out in dialog units (AppFont)."""

    def __init__(self, ctx, frame, title, width, height):
        self.ctx = ctx
        self.frame = frame
        smgr = ctx.ServiceManager
        self.model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", ctx)
        self.model.Title = title
        self.model.Width = width
        self.model.Height = height
        self.dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
        self.dialog.setModel(self.model)
        self._selections = {}

    def add(self, kind, name, x, y, w, h, **props):
        m = self.model.createInstance("com.sun.star.awt.UnoControl{0}Model".format(kind))
        m.PositionX, m.PositionY, m.Width, m.Height = x, y, w, h
        for key, value in props.items():
            setattr(m, key, value)
        self.model.insertByName(name, m)
        return m

    def get(self, name):
        return self.model.getByName(name)

    def on_click(self, name, fn):
        self.dialog.getControl(name).addActionListener(_OnAction(fn, self.show_error))

    def show_error(self, exc):
        msgbox(self.ctx, self.frame, providers.text_of(exc), "error")

    def select(self, name, index):
        # A list box ignores the selection until its window exists: remember
        # it and apply it in execute(), right after the peer is created.
        self._selections[name] = index

    def selected(self, name):
        items = self.get(name).SelectedItems
        return items[0] if items else -1

    def execute(self):
        toolkit = self.ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", self.ctx)
        self.dialog.createPeer(toolkit, _parent(self.ctx, self.frame))
        for name, index in self._selections.items():
            self.dialog.getControl(name).selectItemPos(index, True)
        return self.dialog.execute()

    def dispose(self):
        self.dialog.dispose()


# ------------------------------------------------------------ settings ----

UI_LANGUAGE_CODES = ("auto",) + i18n.LANGUAGES


def settings_dialog(ctx, frame, s, path):
    """Show the settings; returns the saved settings, or None if cancelled."""
    tr = i18n.tr
    f = Form(ctx, frame, tr("dlg.title"), 300, 346)
    label_w, field_x, field_w = 62, 74, 214

    def row(y, label, name, kind="Edit", w=field_w, **props):
        f.add("FixedText", name + "_label", 10, y + 2, label_w, 10, Label=label)
        return f.add(kind, name, field_x, y, w, 12, **props)

    def model_row(y, provider):
        row(y, tr("dlg.model"), provider + "_model", "ComboBox", 160, Dropdown=True, LineCount=15,
            StringItemList=tuple(S.SUGGESTED_MODELS[provider]), Text=s[provider]["model"])
        f.add("Button", provider + "_refresh", 238, y - 1, 50, 14, Label=tr("dlg.refresh"))

    f.add("FixedText", "provider_label", 8, 8, 72, 10, Label=tr("dlg.provider"))
    f.add("ListBox", "provider", 82, 6, 210, 12, Dropdown=True,
          StringItemList=tuple(S.provider_label(p) for p in S.PROVIDERS))
    f.select("provider", S.PROVIDERS.index(s["provider"]))

    f.add("GroupBox", "g_ollama", 4, 24, 292, 46, Label=S.provider_label("ollama"))
    row(35, tr("dlg.host"), "ollama_host", Text=s["ollama"]["host"])
    model_row(52, "ollama")

    f.add("GroupBox", "g_openai", 4, 74, 292, 62, Label="OpenAI")
    row(85, tr("dlg.api_key"), "openai_key", EchoChar=ord("*"), Text=s["openai"]["api_key"])
    row(101, tr("dlg.base_url"), "openai_url", Text=s["openai"]["base_url"])
    model_row(118, "openai")

    f.add("GroupBox", "g_anthropic", 4, 140, 292, 46, Label="Anthropic Claude")
    row(151, tr("dlg.api_key"), "anthropic_key", EchoChar=ord("*"), Text=s["anthropic"]["api_key"])
    model_row(168, "anthropic")

    f.add("GroupBox", "g_behaviour", 4, 190, 292, 108, Label=tr("dlg.behaviour"))
    f.add("FixedText", "system_label", 10, 201, 278, 10, Label=tr("dlg.system"))
    f.add("Edit", "system", 10, 211, 278, 32, MultiLine=True, VScroll=True, Text=s["system_prompt"])
    row(248, tr("dlg.translate_to"), "translate_to", "ComboBox", 100, Dropdown=True, LineCount=15,
        StringItemList=i18n.TRANSLATION_TARGETS, Text=s["translate_to"])
    f.add("FixedText", "timeout_label", 182, 250, 54, 10, Label=tr("dlg.timeout"))
    f.add("NumericField", "timeout", 238, 248, 50, 12, Spin=True, DecimalAccuracy=0,
          ValueMin=10.0, ValueMax=1800.0, ValueStep=10.0, Value=float(s["timeout"]))
    row(264, tr("dlg.ui_language"), "ui_language", "ListBox", Dropdown=True,
        StringItemList=(tr("dlg.auto"),) + tuple(i18n.LANGUAGE_NAMES[c] for c in i18n.LANGUAGES))
    f.select("ui_language", UI_LANGUAGE_CODES.index(s["ui_language"]))
    f.add("CheckBox", "keep", 10, 282, 278, 10, Label=tr("dlg.keep"),
          State=1 if s["output_mode"] == "after" else 0)

    f.add("FixedText", "keys_note", 6, 302, 288, 20, MultiLine=True, Label=tr("dlg.keys_note"))
    f.add("Button", "test", 4, 328, 84, 14, Label=tr("dlg.test"))
    f.add("Button", "cancel", 190, 328, 50, 14, Label=tr("dlg.cancel"), PushButtonType=CANCEL)
    f.add("Button", "save", 246, 328, 50, 14, Label=tr("dlg.save"), PushButtonType=OK,
          DefaultButton=True)

    def read_form():
        d = copy.deepcopy(s)
        d["provider"] = S.PROVIDERS[max(0, f.selected("provider"))]
        d["ollama"]["host"] = f.get("ollama_host").Text.strip()
        d["openai"]["api_key"] = f.get("openai_key").Text.strip()
        d["openai"]["base_url"] = f.get("openai_url").Text.strip() or S.DEFAULTS["openai"]["base_url"]
        d["anthropic"]["api_key"] = f.get("anthropic_key").Text.strip()
        for p in S.PROVIDERS:
            d[p]["model"] = f.get(p + "_model").Text.strip()
        d["system_prompt"] = f.get("system").Text.strip()
        d["translate_to"] = f.get("translate_to").Text.strip()
        d["timeout"] = int(f.get("timeout").Value)
        d["ui_language"] = UI_LANGUAGE_CODES[max(0, f.selected("ui_language"))]
        d["output_mode"] = "after" if f.get("keep").State == 1 else "replace"
        return S.normalize(d)

    def fill_models(provider, quiet=False):
        models = providers.list_models(read_form(), provider, timeout=3 if quiet else 15)
        combo = f.get(provider + "_model")
        current = combo.Text.strip()
        combo.StringItemList = tuple(models)
        if not current and models:
            combo.Text = models[0]
        if not quiet:
            msgbox(ctx, frame, tr("test.models_found", S.provider_label(provider), len(models)))

    def test_connection():
        d = read_form()
        msgbox(ctx, frame, providers.test_connection(d, d["provider"]))

    for p in S.PROVIDERS:
        f.on_click(p + "_refresh", lambda p=p: fill_models(p))
    f.on_click("test", test_connection)

    # Local models are cheap to list: fill the Ollama list right away.
    try:
        fill_models("ollama", quiet=True)
    except Exception:
        pass

    try:
        if f.execute() != OK:
            return None
        new = read_form()
    finally:
        f.dispose()
    S.save(path, new)
    return new


# ------------------------------------------------------------ synonyms ----

def pick_synonym(ctx, frame, word, items):
    """Let the user pick one synonym; returns it, or None."""
    tr = i18n.tr
    shown = word if len(word) <= 40 else word[:37] + "..."
    f = Form(ctx, frame, tr("syn.title"), 220, 176)
    f.add("FixedText", "label", 6, 6, 208, 18, MultiLine=True, Label=tr("syn.label", shown))
    f.add("ListBox", "list", 6, 26, 208, 124, StringItemList=tuple(items))
    f.select("list", 0)
    f.add("Button", "replace", 110, 156, 52, 14, Label=tr("syn.replace"), PushButtonType=OK,
          DefaultButton=True)
    f.add("Button", "close", 166, 156, 48, 14, Label=tr("syn.close"), PushButtonType=CANCEL)

    picked = []

    def on_double_click():
        picked.append(True)
        f.dialog.endExecute()

    f.on_click("list", on_double_click)
    try:
        result = f.execute()
        index = f.selected("list")
    finally:
        f.dispose()
    if (result == OK or picked) and 0 <= index < len(items):
        return items[index]
    return None
