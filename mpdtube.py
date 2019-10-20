import shutil
import os
import youtube_dl
import paho.mqtt.client as mqtt
import threading
import requests
import re
import time
import logging
import yaml
import coloredlogs
import traceback
import json
import shlex

from queue import Queue
from mpd import MPDClient

destination_song = ""


# zonder shuffle werkt 'next in queue' met die prioriteit niet

class ydl_logger(object):
    log = logging.getLogger("YoutubeDL")

    def error(self, msg):
        self.log.error(msg)

    def debug(self, msg):
        global destination_song # fuck you for forcing me to use this ytdl
        self.log.info(msg)

        if msg.startswith("Destination: "):
            destination_song  = "Destination: ".join(msg.split("Destination: ")[:1])

        elif msg.startswith("[ffmpeg] Post-process file "):
            destination_song  = msg.split("Post-process file ")[1].split(" exists")[0]

        elif msg.startswith("[ffmpeg] Destination: "):
            destination_song  = msg.split("[ffmpeg] Destination: ")[1]

class tube():
    log = logging.getLogger("MPDTube")
    config = {}
    songs = []

    def __init__(self):
        self.log.info("MPDTube is starting")
        self.load_config()
        os.makedirs(self.config['paths']['download'], exist_ok=True)

        self.mqtt = mqtt.Client()
        self.mqtt.connect(self.config['mqtt']['host'], self.config['mqtt']['port'], 60)
        self.mqtt.on_connect = self.on_mqtt_connect
        self.mqtt.on_message = self.on_mqtt_message

        self.queue = Queue()

        self.ydl_opts = {'noprogress': True, 'format': 'bestaudio/best', "noplaylist": True, "default_search": "ytsearch",
                         'outtmpl': os.path.join(self.config['paths']['download'], "%(title)s.%(ext)s"), "no_color": True,
                         'postprocessors': [{'key': 'FFmpegExtractAudio',}], 'logger': ydl_logger(),
                        }
        threading.Thread(target=self.queue_thread).start()
        self.mqtt.loop_forever()

    def load_config(self):
        with open("settings.yaml", "r") as f:
            self.config = yaml.safe_load(f)

    def queue_thread(self):
        self.log.info("Queue thread is up")
        while True:
            item = self.queue.get()
            if item:
                try:
                    self.play_song(item[0], item[1])
                except Exception as e:
                    self.log_error("An exception occured while processing %s (%s)" % (item, e))
                    self.log.error(traceback.print_exc())

        self.log.warning("Queue thread has stopped")

    def log_nurdbot(self, type, msg):
        message = shlex.quote("<MPDTUBE:%s> %s" % (type, msg))
        cmd = "%s %s -m %s" % (self.config['nurdbot']['python2'], self.config['nurdbot']['jsb-udp'], message)
        os.system(cmd)

    def log_info(self, msg):
        self.log.info(msg)
        topic = os.path.join(self.config['mqtt']['topics']['status'], "info")
        self.mqtt.publish(topic , msg)

    def log_error(self, msg):
        self.log.error(msg)
        topic = os.path.join(self.config['mqtt']['topics']['status'], "error")
        self.mqtt.publish(topic, msg)

    def log_warning(self, msg):
        self.log.error(msg)
        topic = os.path.join(self.config['mqtt']['topics']['status'], "error")
        self.mqtt.publish(topic, msg)

    def on_mqtt_connect(self, client, userdata, flags, rc):
        self.log.info("MQTT connected.")

        for subscribe in [self.config['mqtt']['topics']['play'], os.path.join(self.config['mqtt']['topics']['play'], "nurdbot")]:
            self.log.info("Subscribing to: %s", subscribe)
            self.mqtt.subscribe(subscribe)
            self.mqtt.publish(self.config['mqtt']['topics']['status'], "MPDTube running.")

    def on_mqtt_message(self, client, userdata, msg):
        if msg.topic == self.config['mqtt']['topics']['play']:
            self.queue.put((msg.payload.decode("utf-8"), False))
            self.log_info("Received on play: %s" % msg.payload.decode("utf-8"))

        elif msg.topic == os.path.join(self.config['mqtt']['topics']['play'], "nurdbot"):
            self.queue.put((msg.payload.decode("utf-8"), True))
            self.log_info("Received on play (nurdbot): %s" % msg.payload.decode("utf-8"))
    def download(self, url):
        global destination_song

        with youtube_dl.YoutubeDL(self.ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            self.log_info("Destination song: %s" % destination_song)
            return destination_song

    def find_prio(self, mpd):
        """ Increase the priority of every song and returns the lowest priority
            that should be used for the next song. Causing it to be played after the
            previous high prio songs. """

        lowest_prio = 255

        for song in mpd.playlistinfo():
            if "prio" in song:
                if int(song['prio']) < lowest_prio:
                    lowest_prio = int(song['prio'])

        if lowest_prio > 1:
            return lowest_prio - 1

        return 1

    def find_song_spotify(self, url):
        """ Try to return a spotify song into an youtube version of the song """
        self.log.warning("Spotify is not supported.")
        return None

    def play_song(self, url, nurdbot=False):
        mpd = MPDClient()
        mpd.connect(self.config['mpd']['host'], self.config['mpd']['port'])

        if url.startswith("spotify:"):
            # Handle spotify urls
           self.find_song_spotify(url)
        else:
            if nurdbot:
                self.log_nurdbot("INFO","Processing: %s" % url)
            file = self.download(url)

        if not file:
            return

        if not os.path.exists(file):
            self.log_error("Couldn't find %s" % file)
            if nurdbot:
                self.log_nurdbot("ERROR", "Couldn't find %s" % file)

            mpd.close()
            mpd.disconnect()
            return

        file = os.path.basename(file)

        self.log_info("Attempting to add: %s " % url)
        mpd.update(os.path.join(self.config['paths']['relative'], file))

        # Set creation and modification time to now
        os.utime(os.path.join(self.config['paths']['download'], file), times=None)

        if self.config['paths']['nfs_delay'] > 0:
            time.sleep(self.config['paths']['nfs_delay'] ) # Wait a bit for it to sync back to NFS

        song_id = mpd.addid(os.path.join(self.config['paths']['relative'], file))

        if nurdbot:
            self.log_nurdbot("INFO", "Adding %s to MPD @ pos %s" % (file, song_id))

        self.log_info("[%s] Song id is: %s" % (file, song_id))

        mpd_status = mpd.status()
        self.log_info("MPD status: %s" % mpd_status)
        self.log.info("Current MPD song: %s" % mpd.currentsong())

        if mpd_status['state'] != "play":
            # Start playing the song right away if we aren't playing anything yet.

            self.log_info("playing song %s right away" % file)
            mpd.playid(song_id)

        elif mpd_status['random'] != "1":
            self.log_warning("MPD is not in random mode, this is currently unsupported!") 
            self.songs.append(song_id)
        else:
            prio = self.find_prio(mpd)
            self.log_info("putting song %s at priority %s" % (file, prio))
            mpd.prioid(prio, song_id)

        mpd.close()
        mpd.disconnect()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    coloredlogs.install(level='INFO', fmt="%(asctime)s %(name)s %(levelname)s %(message)s")
    mpdtube = tube()