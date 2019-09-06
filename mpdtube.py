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

    def __init__(self):
        self.log.info("MPDTube is starting")
        self.load_config()
        os.makedirs(self.config['paths']['download'], exist_ok=True)

        self.mpd = MPDClient()
        self.mqtt = mqtt.Client()
        
        self.mqtt.connect(self.config['mqtt']['host'], self.config['mqtt']['port'], 60)
        self.mqtt.on_connect = self.on_mqtt_connect
        self.mqtt.on_message = self.on_mqtt_message
        
        self.queue = Queue()

        self.ydl_opts = {'noprogress': True, 'format': 'bestaudio/best', "noplaylist": True,
                         'outtmpl': os.path.join(self.config['paths']['download'], "%(title)s.%(ext)s"),
                         'postprocessors': [{'key': 'FFmpegExtractAudio',}], 'logger': ydl_logger(),
                        }
        
        threading.Thread(target=self.queue_thread).start()
        self.mqtt.loop_forever()

    def load_config(self):
        with open("settings.yaml", "r") as f:
            self.config = yaml.load(f)

    def queue_thread(self):
        self.log.info("Queue thread is up")
        while True:
            item = self.queue.get()
            if item:
                try:
                    self.play_song(item)
                except Exception as e:
                    self.log_error("An exception occured while processing %s (%s)" % (item, e))
                    
                    traceback.print_exc()

        self.log.warning("Queue thread has stopped")

    def log_info(self, msg):
        self.log.info(msg)
        self.mqtt.publish(os.path.join(self.config['mqtt']['topics']['status'], "info"), msg)

    def log_error(self, msg):
        self.log.error(msg)
        self.mqtt.publish(os.path.join(self.config['mqtt']['topics']['status'], "error"), msg)

    def log_warning(self, msg):
        self.log.error(msg)
        self.mqtt.publish(os.path.join(self.config['mqtt']['topics']['status'], "warning"), msg)
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        self.log.info("MQTT connected.")
        self.log.info("Subscribing to: %s", self.config['mqtt']['topics']['play'])
        self.mqtt.subscribe(self.config['mqtt']['topics']['play'])
        self.mqtt.publish(self.config['mqtt']['topics']['status'], "MPDTube running.")

    def on_mqtt_message(self, client, userdata, msg):
        if msg.topic == self.config['mqtt']['topics']['play']:
            self.queue.put(msg.payload.decode("utf-8"))
            self.log_info("Received on play: %s" % msg.payload.decode("utf-8"))

    def download(self, url):
        global destination_song 

        with youtube_dl.YoutubeDL(self.ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            self.log_info("Destination song: %s" % destination_song)
            return destination_song

    def find_prio(self):
        """ Increase the priority of every song and returns the lowest priority 
            that should be used for the next song. Causing it to be played after the 
            previous high prio songs. """
        
        lowest_prio = 255

        for song in self.mpd.playlistinfo():
            if "prio" in song:
                if int(song['prio']) < lowest_prio:
                    lowest_prio = int(song['prio'])

        if lowest_prio > 1:
            return lowest_prio - 1
        
        return 1

    def play_song(self, url):
        self.mpd.connect(self.config['mpd']['host'], self.config['mpd']['port'])

        file = self.download(url)

        if not os.path.exists(file):
            self.log_error("Couldn't find %s" % file)
            self.mpd.close()
            self.mpd.disconnect()  
            return

        file = os.path.basename(file)

        self.log_info("Adding: %s " % os.path.join(self.config['paths']['relative'], file))
        self.mpd.update(os.path.join(self.config['paths']['relative'], file))

        if self.config['paths']['nfs_delay'] > 0:
            time.sleep(self.config['paths']['nfs_delay'] ) # Wait a bit for it to sync back to NFS
        
        song_id = self.mpd.addid(os.path.join(self.config['paths']['relative'], file))

        self.log_info("[%s] Song id is: %s" % (file, song_id))

        mpd_status = self.mpd.status()

        if mpd_status['state'] != "play":
            # Start playing the song right away if we aren't playing anything yet.

            self.log_info("playing song %s right away" % file)
            self.mpd.playid(song_id)
        else:
            prio = self.find_prio()
            self.log_info("putting song %s at priority %s" % (file, prio))
            self.mpd.prioid(prio, song_id)
        
        self.mpd.close()
        self.mpd.disconnect()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    coloredlogs.install(level='INFO', fmt="%(asctime)s %(name)s %(levelname)s %(message)s")
    mpdtube = tube()


