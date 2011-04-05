#!/usr/bin/env python

# Madeo MUMS Player
# Copyright 2011  Brendan Le Foll -  brendan@fridu.net
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import sys, os

import gobject
gobject.threads_init()
import logging
import gst
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import logging

UPLAYER_BUS_NAME = 'uk.co.madeo.uplayer'
UPLAYER_BUS_PATH = '/uk/co/madeo/uplayer'
LOG_FILENAME = '/tmp/uplayer.log'

logging.basicConfig(filename=LOG_FILENAME,level=logging.DEBUG)

class GstPlayer:
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2
    BUFFERING = 3
    PREROLLING = 4

    def __init__(self):
        self.status = self.STOPPED
        self.target_status = self.STOPPED

        self._rate = 1.0

        self.c_video = 0
        self.c_audio = 0
        self.c_text = 0
        self.n_video = 0
        self.n_audio = 0
        self.n_text = 0

        self._videosink = None

        self.player = gst.element_factory_make('playbin2', None)

        bus = self.player.get_bus()
        bus.connect('message::eos', self.on_message_eos)
        bus.connect('message::error', self.on_message_error)
        bus.connect('message::state-changed', self.on_message_state_changed)
        bus.connect('message::async-done', self.on_message_async_done)
        bus.add_signal_watch()

    def on_message_async_done(self, bus, message):
        self.n_video = self.player.get_property('n-video')
        self.n_audio = self.player.get_property('n-audio')
        self.n_text = self.player.get_property('n-text')
        logging.debug ("%d video %d audio %d text" % (self.n_video, self.n_audio, self.n_text))
        if self.n_video > 0:
            self.player.set_property("current-video", self.c_video)
        if self.n_audio > 0:
            self.player.set_property("current-audio", self.c_audio)
        if self.n_text > 0:
            self.player.set_property("current-text", self.c_text)
        sink = self.player.get_property('video-sink')
        if sink is not None:
            factory = sink.get_factory()
            if "ismd_vidrend_bin" in factory.get_name():
                logging.debug("using SMD video sink %s" % sink)
                self._videosink = sink
            elif "autovideosink" in factory.get_name():
                logging.debug("using Autovideosink")
                for child in sink.sinks():
                    factory = child.get_factory()
                    if "ismd_vidrend_bin" in factory.get_name():
                        logging.debug("SMD video sink %s" % child)
                        self._videosink = child

        sink = self.player.get_property('audio-sink')
        if sink is not None:
            factory = sink.get_factory()
            if "ismd_audio_sink" in factory.get_name():
                logging.debug("Using SMD audio sink %s" % sink)
            elif "autoaudiosink" in factory.get_name():
                logging.debug("Using Autoaudiosink")
                for child in sink.sinks():
                    factory = child.get_factory()
                    if "ismd_audio_sink" in factory.get_name():
                        logging.debug("SMD audio sink %s" % child)

    def cleanup(self):
        current = self.player.get_state(0)[1]
        if current != gst.STATE_NULL:
            logging.debug ('do_cleanup')
            self.player.set_state(gst.STATE_READY)
            current = self.player.get_state(1000000000)[1]
            logging.debug ('changed state to %s' % current)
            self.player.set_state(gst.STATE_NULL)
            current = self.player.get_state(1000000000)[1]
            logging.debug ('changed state to %s' % current)

    def on_message_eos(self, bus, message):
        send_eos()
        self.playing = False
        self.stop()

    def set_location(self, location):
        if not gst.uri_is_valid(location):
            logging.debug ("Error: Invalid URI: %s\n" % location)
            return False
        self.player.set_property('uri', location)
        return True

    def on_message_error(self, bus, message):
        err, msg = message.parse_error()
        code = message.structure['gerror'].code
        self.stop()
        self.status = self.STOPPED
        self.target_status = self.status
        logging.debug ("Gstreamer %s:%s" % (err, msg))

    def on_message_state_changed(self, bus, message):
        if message.src != self.player:
            return

        old_state, new_state, pending = message.parse_state_changed()
        logging.debug ("old %s current %s pending %s status %s target status %s" % \
            (old_state, new_state, pending, self.status, self.target_status))
        if new_state == gst.STATE_PLAYING:
            if self.status != self.PLAYING:
                self.status = self.PLAYING
                self.playing = True

        elif new_state == gst.STATE_PAUSED:
            if self.status != self.BUFFERING:
                if self.target_status == self.PLAYING:
                    self.player.set_state(gst.STATE_PLAYING)
                else:
                    self.status = self.PAUSED
        elif new_state == gst.STATE_READY:
            if self._videosink is not None:
                del self._videosink
                self._videosink = None

    def pause(self):
        self.target_status = self.PAUSED
        self.player.set_state(gst.STATE_PAUSED)
        current = self.player.get_state(0)[1]
        self.playing = False

    def play(self):
        self.target_status = self.PLAYING
        current = self.player.get_state(0)[1]
        if current == gst.STATE_PAUSED:
            self.player.set_state(gst.STATE_PLAYING)
        elif current != gst.STATE_PLAYING :
            self.player.set_state(gst.STATE_PAUSED)
            self.status = self.PREROLLING

    def stop(self):
        self.player.set_state(gst.STATE_READY)
        current = self.player.get_state(0)[1]
        if self.status != self.STOPPED:
            self.status = self.STOPPED
            self.target_status = self.status

    def get_state(self, timeout=1):
        return self.player.get_state(timeout=timeout)

    def is_playing(self):
        return self.playing

    def get_position(self):
        try:
            position, format = self.player.query_position(gst.FORMAT_TIME)
        except:
            position = gst.CLOCK_TIME_NONE

        return position

    def seek(self, location):
        """
        @param location: time to seek to, in nanoseconds
        """
        if self._rate < 0:
            res = self.player.seek (self._rate, gst.FORMAT_TIME,
                gst.SEEK_FLAG_FLUSH | gst.SEEK_FLAG_KEY_UNIT,
                gst.SEEK_TYPE_SET, 0,
                gst.SEEK_TYPE_SET, location)
        else:
            res = self.player.seek (self._rate, gst.FORMAT_TIME,
                gst.SEEK_FLAG_FLUSH | gst.SEEK_FLAG_KEY_UNIT,
                gst.SEEK_TYPE_SET, location,
                gst.SEEK_TYPE_SET, -1)

        if not res:
            logging.debug ("seek failed");

    def set_rate(self, rate):
        self.pause()

        self._rate = rate
        try:
            position, format = self.player.query_position(gst.FORMAT_TIME)
        except:
            position = gst.CLOCK_TIME_NONE

        if self._rate < 0:
            res = self.player.seek(self._rate, gst.FORMAT_TIME,
                gst.SEEK_FLAG_FLUSH,
                gst.SEEK_TYPE_SET, 0,
                gst.SEEK_TYPE_SET, position)
        else:
            res = self.player.seek(self._rate, gst.FORMAT_TIME,
                gst.SEEK_FLAG_FLUSH,
                gst.SEEK_TYPE_SET, position,
                gst.SEEK_TYPE_SET, -1)

        if res:
            gst.info("rate set to %s" % rate)
        else:
            logging.debug ("failed to change video rate");
        self.play()

    def next_video_stream(self):
        if self.n_video > 0:
            current = (self.c_video + 1) % self.n_video
            if current != self.c_video:
                self.player.set_property("current-video", current)
                self.c_video = current

    def next_audio_stream(self):
        if self.n_audio > 0:
            current = (self.c_audio + 1) % self.n_audio
            if current != self.c_audio:
                self.player.set_property("current-audio", current)
                self.c_audio = current

    def next_text_stream(self):
        if self.n_text > 0:
            current = (self.c_text + 1) % self.n_text
            if current != self.c_text:
                self.player.set_property("current-text", current)
                self.c_text = current

    def set_gdl_plane(self, plane):
        if plane > 0 and plane < 7:
            self._videosink.set_property('gdl-plane', plane)
            return True
        return False

    def set_user_agent(self, user_agent):
        source = self.player.get_property('source')
        try:
            source.set_property("user-agent", user_agent)
        except:
            logging.debug ("failed to set user-agent to %s" % user_agent)
            pass

    def set_rectangle_size(self, x, y, w, h):
        # check we are using ismd sink
        if self._videosink is not None:
            logging.debug ("rectangle size changed to %s %d %d %d %d" % (self._videosink, x, y, w, h))
            self._videosink.set_property ("rectangle", "%d,%d,%d,%d" % (x, y, w, h))
            return True
        return False

class uplayerDBUSService(dbus.service.Object):
    def __init__(self):
        bus_name = dbus.service.BusName(UPLAYER_BUS_NAME, bus=dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, UPLAYER_BUS_PATH)
        self.player = GstPlayer()

    @dbus.service.signal(UPLAYER_BUS_NAME)
    def emitEOSSignal(self):
        logging.debug ("EOS signal sent")
        return

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='s', out_signature='b')
    def set_uri(self, uri):
        return self.player.set_location(uri);

    @dbus.service.method(UPLAYER_BUS_NAME)
    def play(self):
        self.player.play();

    @dbus.service.method(UPLAYER_BUS_NAME)
    def pause(self):
        self.player.pause();

    @dbus.service.method(UPLAYER_BUS_NAME)
    def stop(self):
        self.player.stop();

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='', out_signature='t')
    def get_position(self):
        return self.player.get_position()

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='i', out_signature='')
    def seek(self, position):
        self.player.seek(position)

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='i', out_signature='')
    def set_rate(self, rate):
        self.player.set_rate(rate)

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='s', out_signature='b')
    def set_user_agent(self, user_agent):
        return self.player.set_user_agent(user_agent)

    @dbus.service.method(UPLAYER_BUS_NAME,
                        in_signature='iiii', out_signature='')
    def set_rectangle_size(self, x, y, w, h):
        self.player.set_rectangle_size(x,y,w,h)

    @dbus.service.method(UPLAYER_BUS_NAME,
                         in_signature='i', out_signature='b')
    def set_gdl_plane(self, gdl_plane):
        return self.player.set_gdl_plane (gdl_plane)

DBusGMainLoop(set_as_default=True)
uplayerService = uplayerDBUSService()
player = GstPlayer()

def send_eos ():
    uplayerService.emitEOSSignal()

logging.debug ("Starting uplayer...")
loop = gobject.MainLoop()
loop.run()
