# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2010, Stephen Griffiths <scgmk5@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, see <http://www.gnu.org/licenses/>.
import datetime
import multiprocessing
import os
import resource
import sys

from gi.repository import GObject

from pitivi.check import missing_soft_deps
from pitivi.configure import APPNAME
from pitivi.utils.loggable import Loggable


class System(GObject.Object, Loggable):
    """A base class for systems in which Pitivi runs."""

    __gsignals__ = {
        'update-power-inhibition': (GObject.SIGNAL_RUN_LAST, None, ()),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        Loggable.__init__(self)
        self.log("new object %s", self)
        self._reset()

        self._x11 = False
        try:
            from gi.repository import GdkX11
            self._x11 = True
        except ImportError:
            pass

    def has_x11(self):
        return self._x11

    def _reset(self):
        self._screensaver_keys = []
        self._sleep_keys = []

    # generic functions
    def _inhibit(self, list_, key):
        assert key is not None
        assert isinstance(key, str)
        if key not in list_:
            list_.append(key)
            self.log("emitting 'update-power-inhibition'")
            self.emit('update-power-inhibition')

    def _uninhibit(self, list_, key):
        if key is None:
            if self._isInhibited(list_):
                list_ = []
                self.log("emitting 'update-power-inhibition'")
                self.emit('update-power-inhibition')
        else:
            assert isinstance(key, str)
            if key in list_:
                list_.remove(key)
                self.log("emitting 'update-power-inhibition'")
                self.emit('update-power-inhibition')

    def _isInhibited(self, list_, key=None):
        if key is None:
            if list_:
                return True
        elif key in list_:
            return True

        return False

    # screensaver
    def inhibitScreensaver(self, key):
        """Increases the screensaver inhibitor count.

        It is safe to call this method with a key that is already inhibited.

        Args:
            key (str): A unique translated string, giving the reason for
                inhibiting sleep
        """
        self.info("Inhibiting the screensaver")
        self._inhibit(self._screensaver_keys, key)

    def uninhibitScreensaver(self, key):
        """Decreases screensaver inhibitor count.

        It is safe to call this method with a key that is not inhibited.

        Args:
            key (str): A unique translated string, giving the reason for
                inhibiting sleep
        """
        self.info("Uninhibiting the screensaver")
        self._uninhibit(self._screensaver_keys, key)

    def screensaverIsInhibited(self, key=None):
        """Checks whether inhibited."""
        return self._isInhibited(self._screensaver_keys, key)

    def getScreensaverInhibitors(self):
        """Returns a comma separated string of screensaver inhibitor keys."""
        return ", ".join(self._screensaver_keys)

    def screensaverIsBlockable(self):
        return False

    # Sleep
    def inhibitSleep(self, key):
        """Increase the sleep inhibitor count.

        It is safe to call this method with a key that is already inhibited.

        Args:
            key (str): A unique translated string, giving the reason for
                inhibiting sleep
        """
        self.info("Inhibiting sleep")
        self._inhibit(self._sleep_keys, key)

    def uninhibitSleep(self, key):
        """Decreases sleep inhibitor count.

        It is safe to call this method with a key that is not inhibited.

        Args:
            key (str): A unique translated string, giving the reason for
                inhibiting sleep
        """
        self.info("Uninhibiting sleep")
        self._uninhibit(self._sleep_keys, key)

    def sleepIsInhibited(self, key=None):
        """Returns whether inhibited."""
        return self._isInhibited(self._sleep_keys, key)

    def getSleepInhibitors(self):
        """Returns a comma separated strinsg of sleep inhibitor keys."""
        return ", ".join(self._sleep_keys)

    def sleepIsBlockable(self):
        return False

    # Other
    def uninhibitAll(self):
        self._reset()
        self.emit('update-power-inhibition')

    def desktopMessage(self, title, message, unused_icon=None):
        """Sends a message to the desktop to be displayed to the user.

        Args:
            title (str): The title of the message.
            message (str): The body of the message.
            icon (str): The icon to be shown with the message
        """
        self.debug("desktopMessage(): %s, %s", title, message)
        return None

    def getUniqueFilename(self, string):
        """Gets a filename which can only be obtained from the specified string.

        Args:
            string (str): The string identifying the filename.

        Returns:
            str: A filename which looks like the specified string.
        """
        return string.replace("%", "%37").replace("/", "%47")


class FreedesktopOrgSystem(System):
    """Provides messaging capabilites for desktops that implement fd.o specs."""

    def __init__(self):
        System.__init__(self)
        if "Notify" not in missing_soft_deps:
            from gi.repository import Notify
            Notify.init(APPNAME)

    def desktopMessage(self, title, message, icon="pitivi"):
        # call super method for consistent logging
        System.desktopMessage(self, title, message, icon)

        if "Notify" not in missing_soft_deps:
            from gi.repository import Notify
            notification = Notify.Notification.new(title, message, icon=icon)
            try:
                notification.show()
            except RuntimeError as e:
                # This can happen if the system is not properly configured.
                # See for example
                # https://bugzilla.gnome.org/show_bug.cgi?id=719627.
                self.error(
                    "desktopMessage: Failed displaying notification: %s", e.message)
                return None
            return notification
        return None


# org.gnome.SessionManager flags
INHIBIT_LOGOUT = 1
INHIBIT_USER_SWITCHING = 2
INHIBIT_SUSPEND = 4
INHIBIT_SESSION_IDLE = 8

COOKIE_NONE = 0
COOKIE_SCREENSAVER = 1
COOKIE_SLEEP = 2


class GnomeSystem(FreedesktopOrgSystem):

    def __init__(self):
        FreedesktopOrgSystem.__init__(self)

        import dbus
        self.bus = dbus.Bus(dbus.Bus.TYPE_SESSION)

        # connect to gnome sessionmanager
        self.sessionmanager = self.bus.get_object('org.gnome.SessionManager',
                                                  '/org/gnome/SessionManager')
        self.session_iface = dbus.Interface(self.sessionmanager,
                                            'org.gnome.SessionManager')
        self.cookie = None
        self.cookie_type = COOKIE_NONE

        self.connect('update-power-inhibition', self._updatePowerInhibitionCb)

    def _updatePowerInhibitionCb(self, unused_system):
        # there are two states we want the program to be in, with regards to
        # power saving, the screen saver is inhibited when the viewer is watched.
        # or we inhibit sleep/powersaving when we are processing data
        # we do things the way we do here because the viewer shows the the output
        # of the render pipeline
        self.log("updating power inhibitors")
        toplevel_id = 0

        # inhibit power saving if we are rendering, maybe downloading a video
        if self.sleepIsInhibited():
            if self.cookie_type != COOKIE_SLEEP:
                new_cookie = self.session_iface.Inhibit(APPNAME, toplevel_id,
                                                        self.getSleepInhibitors(), INHIBIT_SUSPEND | INHIBIT_LOGOUT)
                if self.cookie is not None:
                    self.session_iface.Uninhibit(self.cookie)
                self.cookie = new_cookie
                self.cookie_type = COOKIE_SLEEP
                self.debug("sleep inhibited")
            else:
                self.debug("sleep already inhibited")
        # inhibit screensaver if we are just watching the viewer
        elif self.screensaverIsInhibited():
            if self.cookie_type != COOKIE_SCREENSAVER:
                new_cookie = self.session_iface.Inhibit(APPNAME, toplevel_id,
                                                        self.getScreensaverInhibitors(), INHIBIT_SESSION_IDLE)
                if self.cookie is not None:
                    self.session_iface.Uninhibit(self.cookie)
                self.cookie = new_cookie
                self.cookie_type = COOKIE_SCREENSAVER
                self.debug("screensaver inhibited")
            else:
                self.debug("screensaver already inhibited")
        # unblock everything otherwise
        else:
            if self.cookie != COOKIE_NONE:
                self.session_iface.Uninhibit(self.cookie)
                self.cookie = None
                self.cookie_type = COOKIE_NONE
                self.debug("uninhibited")
            else:
                self.debug("already uninhibited")


class DarwinSystem(System):
    """Apple OS X."""

    def __init__(self):
        System.__init__(self)


class WindowsSystem(System):
    """Microsoft Windows."""

    def __init__(self):
        System.__init__(self)


def get_system():
    """Creates a System object.

    Returns:
        System: A System object.
    """
    if os.name == 'posix':
        if sys.platform == 'darwin':
            return DarwinSystem()

        if 'GNOME_DESKTOP_SESSION_ID' in os.environ:
            return GnomeSystem()
        return FreedesktopOrgSystem()
    if os.name == 'nt':
        return WindowsSystem()
    return System()


class CPUUsageTracker(object):

    def __init__(self):
        self.reset()

    def usage(self):
        delta_time = (datetime.datetime.now() - self.last_moment).total_seconds()
        delta_usage = resource.getrusage(
            resource.RUSAGE_SELF).ru_utime - self.last_usage.ru_utime
        usage = float(delta_usage) / delta_time * 100
        return usage / multiprocessing.cpu_count()

    def reset(self):
        self.last_moment = datetime.datetime.now()
        self.last_usage = resource.getrusage(resource.RUSAGE_SELF)
