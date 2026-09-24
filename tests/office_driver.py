# -*- coding: utf-8 -*-
# End-to-end check inside a running office (run with the office's own Python).
#
#   soffice -env:UserInstallation=file:///C:/tmp/ooai_profile -headless -norestore
#           -accept="socket,host=127.0.0.1,port=2099;urp;"
#   python tests/office_driver.py [model]
#
# The extension must be installed in that profile (unopkg add ... -env:...).
# It writes openofficeai.json in the profile, opens a Writer document and runs
# the commands through the dispatch framework, like a toolbar click.
from __future__ import print_function, unicode_literals

import io
import json
import os
import sys
import time

import uno
from com.sun.star.beans import PropertyValue

MODEL = sys.argv[1] if len(sys.argv) > 1 else "llama3.2:3b"


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def connect():
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(90):
        try:
            return resolver.resolve("uno:socket,host=127.0.0.1,port=2099;urp;StarOffice.ComponentContext")
        except Exception:
            time.sleep(1)
    raise SystemExit("office not reachable")


def config(ctx, path):
    cp = ctx.ServiceManager.createInstanceWithContext("com.sun.star.configuration.ConfigurationProvider", ctx)
    return cp.createInstanceWithArguments("com.sun.star.configuration.ConfigurationAccess",
                                          (prop("nodepath", path),))


def paragraphs(doc):
    out = []
    e = doc.getText().createEnumeration()
    while e.hasMoreElements():
        p = e.nextElement()
        if p.supportsService("com.sun.star.text.Paragraph"):
            out.append(p.getString())
    return out


def select_all(doc):
    c = doc.getText().createTextCursor()
    c.gotoStart(False)
    c.gotoEnd(True)
    doc.getCurrentController().select(c)


def run(ctx, doc, command):
    frame = doc.getCurrentController().getFrame()
    helper = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.DispatchHelper", ctx)
    t = time.time()
    helper.executeDispatch(frame, "org.openofficeai:" + command, "", 0, ())
    return time.time() - t


def main():
    ctx = connect()
    smgr = ctx.ServiceManager

    # 1. Configuration layer accepted our xcu files.
    handlers = config(ctx, "/org.openoffice.Office.ProtocolHandler/HandlerSet")
    assert handlers.hasByName("org.openofficeai.ProtocolHandler"), "protocol handler not registered"
    bars = config(ctx, "/org.openoffice.Office.Addons/AddonUI/OfficeToolBar")
    bar = bars.getByName("org.openofficeai.toolbar")
    items = bar.getByName("ToolBarItems")
    print("toolbar title:", bar.Title, "| items:", len(items.getElementNames()))
    for n in sorted(items.getElementNames()):
        it = items.getByName(n)
        print("  ", n, it.URL, "|", it.Title)
    menu = config(ctx, "/org.openoffice.Office.Addons/AddonUI/OfficeMenuBar").getByName("org.openofficeai.menu")
    print("menu title:", menu.Title, "| entries:", len(menu.getByName("Submenu").getElementNames()))
    images = config(ctx, "/org.openoffice.Office.Addons/AddonUI/Images")
    img = images.getByName("org.openofficeai.image.migliora").getByName("UserDefinedImages").ImageSmallURL
    print("image url:", img)

    # 2. Settings file in the profile.
    subst = smgr.createInstanceWithContext("com.sun.star.util.PathSubstitution", ctx)
    user_dir = uno.fileUrlToSystemPath(subst.substituteVariables("$(user)", True))
    path = os.path.join(user_dir, "openofficeai.json")

    def write_settings(**extra):
        data = {"provider": "ollama", "ollama": {"model": MODEL}, "ui_language": "it", "timeout": 120}
        data.update(extra)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False))

    write_settings()

    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    text = doc.getText()
    original = ("Qvesto testo a degli errori di ortografia e di grammatica.\r"
                "Il secondo paragrafo anche, perche non ce la punteggiatura giusta")
    text.setString(original)
    before = paragraphs(doc)
    print("\nbefore:", before)

    # 3. Editing replaces the selection, keeps paragraphs, one undo step.
    select_all(doc)
    secs = run(ctx, doc, "editing")
    after = paragraphs(doc)
    print("editing ({0:.1f}s):".format(secs), after)
    assert after != before, "text unchanged"
    sel = doc.getCurrentController().getSelection().getByIndex(0).getString()
    print("selection after write spans", len(sel), "chars")
    doc.getUndoManager().undo()
    assert paragraphs(doc) == before, "undo did not restore in one step: {0}".format(paragraphs(doc))
    print("undo: restored in one step")

    # 4. Bullet list produces bullet paragraphs.
    select_all(doc)
    secs = run(ctx, doc, "elenco")
    print("elenco ({0:.1f}s):".format(secs), paragraphs(doc))
    doc.getUndoManager().undo()

    # 5. Keep original, translation appended below.
    write_settings(output_mode="after", translate_to="English")
    select_all(doc)
    secs = run(ctx, doc, "traduci")
    result = paragraphs(doc)
    print("traduci after ({0:.1f}s):".format(secs), result)
    assert result[:len(before)] == before, "original not kept"
    assert len(result) > len(before), "nothing appended"

    doc.setModified(False)
    doc.close(True)
    print("\nALL OK")


if __name__ == "__main__":
    main()
