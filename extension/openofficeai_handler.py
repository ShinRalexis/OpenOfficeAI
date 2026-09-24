# -*- coding: utf-8 -*-
# OpenOfficeAI: UNO entry point.
# A protocol handler for URLs of the form "org.openofficeai:<command>", used by
# the toolbar buttons and menu entries declared in Addons.xcu. The actual work
# is in pythonpath/openofficeai, which the Python loader puts on sys.path.
from __future__ import unicode_literals

import uno
import unohelper
from com.sun.star.frame import XDispatch, XDispatchProvider
from com.sun.star.lang import XInitialization, XServiceInfo

IMPLEMENTATION_NAME = "org.openofficeai.ProtocolHandler"
SERVICE_NAMES = ("com.sun.star.frame.ProtocolHandler",)
PROTOCOL = "org.openofficeai:"


class ProtocolHandler(unohelper.Base, XInitialization, XDispatchProvider, XDispatch, XServiceInfo):
    def __init__(self, ctx, *args):
        self.ctx = ctx
        self.frame = None

    # XInitialization: the office passes the frame the handler works for.
    def initialize(self, args):
        if args:
            self.frame = args[0]

    # XDispatchProvider
    def queryDispatch(self, url, target, flags):
        return self if url.Protocol == PROTOCOL else None

    def queryDispatches(self, requests):
        return tuple(self.queryDispatch(r.FeatureURL, r.FrameName, r.SearchFlags) for r in requests)

    # XDispatch
    def dispatch(self, url, args):
        # "import a.b" rather than "from a import b": uno's import hook turns a
        # failed "from" import into a misleading "type a.b is unknown" error.
        try:
            import openofficeai.actions
        except Exception:
            _report_import_error(self.ctx)
            return
        openofficeai.actions.run(self.ctx, self.frame, url.Path)

    def addStatusListener(self, listener, url):
        # Report the command as enabled, otherwise some toolbars grey it out.
        event = uno.createUnoStruct("com.sun.star.frame.FeatureStateEvent")
        event.FeatureURL = url
        event.Source = self
        event.IsEnabled = True
        event.Requery = False
        try:
            listener.statusChanged(event)
        except Exception:
            pass

    def removeStatusListener(self, listener, url):
        pass

    # XServiceInfo
    def getImplementationName(self):
        return IMPLEMENTATION_NAME

    def supportsService(self, name):
        return name in SERVICE_NAMES

    def getSupportedServiceNames(self):
        return SERVICE_NAMES


def _report_import_error(ctx):
    """The package could not be loaded: show why, with the Python search path."""
    import sys
    import traceback
    detail = "{0}\nsys.path:\n{1}".format(traceback.format_exc(), "\n".join(
        type("")(p) for p in sys.path))
    try:
        import io
        import os
        subst = ctx.ServiceManager.createInstanceWithContext("com.sun.star.util.PathSubstitution", ctx)
        user_dir = uno.fileUrlToSystemPath(subst.substituteVariables("$(user)", True))
        with io.open(os.path.join(user_dir, "openofficeai.log"), "a", encoding="utf-8") as f:
            f.write("import failed:\n" + detail + "\n")
    except Exception:
        pass
    try:
        from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
        from com.sun.star.awt.MessageBoxType import ERRORBOX
        smgr = ctx.ServiceManager
        toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        frame = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx).getCurrentFrame()
        parent = frame.getContainerWindow() if frame is not None else None
        toolkit.createMessageBox(parent, ERRORBOX, BUTTONS_OK, "OpenOfficeAI", detail).execute()
    except Exception:
        sys.stderr.write(detail)


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(ProtocolHandler, IMPLEMENTATION_NAME, SERVICE_NAMES)
