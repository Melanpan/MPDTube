### Overview

A program to add almost anything that youtube-dl supports to MPD with it's communication going over MQTT.

### About
My local hackers space, [Nurdspace](https://nurdspace.nl/Main_Page), has a MPD server running on a Raspberry Pi and have some of it's functionality accessable through IRC. (Think of the next command and so on.). While every member can upload their own music to a NFS share, it's often more cumbersome if you want to let the space enjoy some fresh new beats from Youtube. 

That's where MPDTube comes into play, with it being integrated into the bot people can simply do a `!mpdtube <url or search query>` and quickly play what they want to hear.

Under the hood, however, the bot sends the query over MQTT to MPDtube, which in turn downloads the music and puts it in MPD with a high priority so that the song will be played next.

### Usage
All you have to do after setting the config is to send a payload with the query to `mpd/youtube-dl/play` and the MPDTube will automatically download the file. The process can be followed by subscribing to `mpd/youtube-dl/status`

### Spotify
You can also give a spotify track as query, such as `spotify:track:2tI2DDT95lnvNhlPWZRMJ3`. However, Spotify requires some additional setting up to do. You have to register MPDTube as an application over [here](https://developer.spotify.com/dashboard/applications). And set the client id and client secret in the config file.

Then you have to start mpdtube from the terminal and follow the on-screen instructions. This should only have to be done once until the `.cache-<username>` file gets deleted. MPDTube will not halt when it's not running in a terminal (Such as when it's running as a service.)

### Config
Here is an example config file, the syntax is yaml and the config has to be saved as settings.yaml
```yaml
paths:
  download: "/mnt/mp3/youtube/"
  relative: "youtube/"
  nfs_delay: 10

mqtt:
  host: 192.168.1.7
  port: 1883

  topics:
    play: mpd/youtube-dl/play
    status: mpd/youtube-dl/status
  
mpd:
  host: localhost
  port: 6600

nurdbot:
  jsb-udp: /home/pi/mpdtube/jsb-udpsend
  python2: /usr/bin/python

abuse:
  length: 900
  filesize: 100000

spotify:
  client:
    id: 1337RICEDGKDGKDGOLS03
    secret: 1337RICEDGKDGKDGOLS03
  username: nurd@nurd.com
```


| Setting               | Description                              | Required
|-----------------------|------------------------------------------|------------------------------------------|
| paths:download        | The output path of where MPDTube should download the files. | Yes
| paths:relative        | The relative path as seen from MPD.      | Yes
| paths:nfs_timeout     | The amount of time to wait for NFS to get updated, if you're not using nfs you can set this to 0. | Yes
| mqtt:host             | mqtt host.                               | Yes
| mqtt:port             | mqtt port.                               | Yes
| mqtt:topics:play      | The topic to subscribe to, to look for queries. | Yes
| mqtt:topics:status    | The topic to send log messages to.       | Yes
| mpd:host              | The host/IP of the system running the MPD server. | Yes
| mpd:port              | The port the MPD server listens on.      | Yes
| nurdbot:jsb-udp       | Path to the jsb-udp python file for Jsonbot integration. | No
| nurdbot:python2       | Path to python2 for Jsonbot integration. | No
| abuse:length          | Max duration allowed. | No
| abuse:filesize        | Max file size allowed. | No
| spotify:client:id     | Spotify application id                   | No
| spotify:username      | Your spotify username                    | No
| spotify:client:secret | Spotify application secret               | No


### Note 1
It's tightly integrated with the Nurdbot (running jsonbot), as MPDtube has the abillity to directly communicate back using the bot's jsb-udpsend program
this might eventually get swapped out to only have this communication over MQTT.

### Note 2 
Spotify support seems to still be semi broken.