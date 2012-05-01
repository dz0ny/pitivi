# PiTiVi , Non-linear video editor
#
#       pitivi/timeline/ruler.py
#
# Copyright (c) 2006, Edward Hervey <bilboed@bilboed.com>
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
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""
Widget for the complex view ruler
"""

import gobject
import gtk
import gst

from pitivi.utils.playback import Seeker
from pitivi.utils.timeline import Zoomable
from pitivi.utils.loggable import Loggable

from pitivi.utils.ui import time_to_string


class ScaleRuler(gtk.DrawingArea, Zoomable, Loggable):

    __gsignals__ = {
        "expose-event": "override",
        "button-press-event": "override",
        "button-release-event": "override",
        "motion-notify-event": "override",
        "scroll-event": "override",
        "seek": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                [gobject.TYPE_UINT64])
        }

    border = 0
    min_tick_spacing = 3
    scale = [0, 0, 0, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 3600]
    subdivide = ((1, 1.0), (2, 0.5), (10, .25))

    def __init__(self, instance, hadj):
        gtk.DrawingArea.__init__(self)
        Zoomable.__init__(self)
        Loggable.__init__(self)
        self.log("Creating new ScaleRuler")
        self.app = instance
        self._seeker = Seeker()
        self.hadj = hadj
        hadj.connect("value-changed", self._hadjValueChangedCb)
        self.add_events(gtk.gdk.POINTER_MOTION_MASK |
            gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_RELEASE_MASK)

        # double-buffering properties
        self.pixmap = None
        # all values are in pixels
        self.pixmap_offset = 0
        self.pixmap_offset_painted = 0
        # This is the number of visible_width we allocate for the pixmap
        self.pixmap_multiples = 4

        self.position = 0  # In nanoseconds
        self.pressed = False
        self.need_update = True
        self.min_frame_spacing = 5.0
        self.frame_height = 5.0
        self.frame_rate = gst.Fraction(1 / 1)

    def _hadjValueChangedCb(self, hadj):
        self.pixmap_offset = self.hadj.get_value()
        self.queue_draw()

## Zoomable interface override

    def zoomChanged(self):
        self.need_update = True
        self.queue_draw()

## timeline position changed method

    def timelinePositionChanged(self, value, unused_frame=None):
        self.log("value : %r", value)
        ppos = max(self.nsToPixel(self.position) - 1, 0)
        self.position = value
        npos = max(self.nsToPixel(self.position) - 1, 0)
        self._hadjValueChangedCb(self.hadj)
        height = self.get_allocation().height
        self.window.invalidate_rect((ppos, 0, 2, height), True)
        self.window.invalidate_rect((npos, 0, 2, height), True)

## gtk.Widget overrides

    def do_expose_event(self, event):
        self.log("exposing ScaleRuler %s", list(event.area))
        x, y, width, height = event.area

        self.repaintIfNeeded(width, height)
        # offset in pixmap to paint
        offset_to_paint = self.pixmap_offset - self.pixmap_offset_painted

        self.window.draw_drawable(
            self.style.fg_gc[gtk.STATE_NORMAL],
            self.pixmap,
            int(offset_to_paint), 0,
            x, y, width, height)

        # draw the position
        context = self.window.cairo_create()
        self.drawPosition(context)
        return False

    def do_button_press_event(self, event):
        self.debug("button pressed at x:%d", event.x)
        self.pressed = True
        position = self.pixelToNs(event.x + self.pixmap_offset)
        self._seeker.seek(position)
        return True

    def do_button_release_event(self, event):
        self.debug("button released at x:%d", event.x)
        self.pressed = False
        # The distinction between the ruler and timeline canvas is theoretical.
        # If the user interacts with the ruler, have the timeline steal focus
        # from other widgets. This reactivates keyboard shortcuts for playback.
        timeline = self.app.gui.timeline_ui
        timeline._canvas.grab_focus(timeline._root_item)
        return False

    def do_motion_notify_event(self, event):
        if self.pressed:
            self.debug("motion at event.x %d", event.x)
            position = self.pixelToNs(event.x + self.pixmap_offset)
            self._seeker.seek(position)
        return False

    def do_scroll_event(self, event):
        if event.state & gtk.gdk.CONTROL_MASK:
            # Control + scroll = zoom
            if event.direction == gtk.gdk.SCROLL_UP:
                Zoomable.zoomIn()
                self.log("Setting 'zoomed_fitted' to False")
                self.app.gui.zoomed_fitted = False
            elif event.direction == gtk.gdk.SCROLL_DOWN:
                Zoomable.zoomOut()
                self.log("Setting 'zoomed_fitted' to False")
                self.app.gui.zoomed_fitted = False
        else:
            # No modifier key held down, just scroll
            if event.direction == gtk.gdk.SCROLL_UP or\
                event.direction == gtk.gdk.SCROLL_LEFT:
                self.app.gui.timeline_ui.scroll_left()
            elif event.direction == gtk.gdk.SCROLL_DOWN or\
                event.direction == gtk.gdk.SCROLL_RIGHT:
                self.app.gui.timeline_ui.scroll_right()

## Drawing methods

    def repaintIfNeeded(self, width, height):
        """ (re)create the buffered drawable for the Widget """
        # we can't create the pixmap if we're not realized
        if self.pixmap:
            # The new offset starts before painted in pixmap
            if (self.pixmap_offset < self.pixmap_offset_painted):
                self.need_update = True
            # The new offsets end after pixmap we have
            if (self.pixmap_offset + width > self.pixmap_offset_painted + self.pixmap.get_size()[0]):
                self.need_update = True

        # Can't create pixmap if not REALIZED
        if self.need_update and self.flags() & gtk.REALIZED:
            self.debug("Ruller is repainted")
            # We create biger pixmap to not repaint ruller every time
            if self.pixmap is None or (width >= self.pixmap.get_size()[0]):
                if self.pixmap:
                    del self.pixmap
                self.pixmap = gtk.gdk.Pixmap(self.window, width *
                                         self.pixmap_multiples, height)
            self.pixmap_offset_painted = self.pixmap_offset
            self.drawBackground()
            self.drawRuler()
            self.need_update = False

    def setProjectFrameRate(self, rate):
        """
        Set the lowest scale based on project framerate
        """
        self.frame_rate = rate
        self.scale[0] = float(2 / rate)
        self.scale[1] = float(5 / rate)
        self.scale[2] = float(10 / rate)

    def drawBackground(self):
        self.pixmap.draw_rectangle(
            self.style.bg_gc[gtk.STATE_NORMAL],
            True,
            0, 0,
            self.pixmap.get_size()[0], self.pixmap.get_size()[1])
        offset = int(self.nsToPixel(gst.CLOCK_TIME_NONE)) - self.pixmap_offset
        if offset > 0:
            self.pixmap.draw_rectangle(
                self.style.bg_gc[gtk.STATE_ACTIVE],
                True,
                0, 0,
                int(offset),
                int(self.pixmap.get_size()[1]))

    def drawRuler(self):
        layout = self.create_pango_layout(time_to_string(0))
        textwidth, textheight = layout.get_pixel_size()

        for scale in self.scale:
            spacing = Zoomable.zoomratio * scale
            if spacing >= textwidth * 1.5:
                break

        offset = self.pixmap_offset % spacing
        zoomRatio = self.zoomratio
        self.drawFrameBoundaries()
        self.drawTicks(offset, spacing, scale)
        self.drawTimes(offset, spacing, scale, layout)

    def drawTick(self, paintpos, height):
        paintpos = int(paintpos)
        height = self.pixmap.get_size()[1] - int(self.pixmap.get_size()[1] * height)
        self.pixmap.draw_line(
            self.style.fg_gc[gtk.STATE_NORMAL],
            paintpos, height, paintpos,
            self.pixmap.get_size()[1])

    def drawTicks(self, offset, spacing, scale):
        for subdivide, height in self.subdivide:
            spc = spacing / float(subdivide)
            dur = scale / float(subdivide)
            if spc < self.min_tick_spacing:
                break
            paintpos = -spacing + 0.5
            paintpos += spacing - offset
            while paintpos < self.pixmap.get_size()[0]:
                self.drawTick(paintpos, height)
                paintpos += spc

    def drawTimes(self, offset, spacing, scale, layout):
        # figure out what the optimal offset is
        interval = long(gst.SECOND * scale)
        seconds = self.pixelToNs(self.pixmap_offset)
        paintpos = float(self.border) + 2
        if offset > 0:
            seconds = seconds - (seconds % interval) + interval
            paintpos += spacing - offset

        while paintpos < self.pixmap.get_size()[0]:
            timevalue = time_to_string(long(seconds))
            layout.set_text(timevalue)
            if paintpos < self.nsToPixel(gst.CLOCK_TIME_NONE):
                state = gtk.STATE_ACTIVE
            else:
                state = gtk.STATE_NORMAL
            self.pixmap.draw_layout(
                self.style.fg_gc[state],
                int(paintpos), 0, layout)
            paintpos += spacing
            seconds += interval

    def drawFrameBoundaries(self):
        ns_per_frame = float(1 / self.frame_rate) * gst.SECOND
        frame_width = self.nsToPixel(ns_per_frame)
        if frame_width >= self.min_frame_spacing:
            offset = self.pixmap_offset % frame_width
            paintpos = -frame_width + 0.5
            height = self.pixmap.get_size()[1]
            y = int(height - self.frame_height)
            states = [gtk.STATE_ACTIVE, gtk.STATE_PRELIGHT]
            paintpos += frame_width - offset
            frame_num = int(paintpos // frame_width) % 2
            while paintpos < self.pixmap.get_size()[0]:
                self.pixmap.draw_rectangle(
                    self.style.bg_gc[states[frame_num]],
                    True,
                    int(paintpos), y, frame_width, height)
                frame_num = (frame_num + 1) % 2
                paintpos += frame_width

    def drawPosition(self, context):
        # a simple RED line will do for now
        xpos = self.nsToPixel(self.position) + self.border - self.pixmap_offset
        context.save()
        context.set_line_width(1.5)
        context.set_source_rgb(1.0, 0, 0)
        context.move_to(xpos, 0)
        context.line_to(xpos, self.pixmap.get_size()[1])
        context.stroke()
        context.restore()
