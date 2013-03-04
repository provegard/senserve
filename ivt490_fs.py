#!/usr/bin/env python

# Released under the MIT license, http://per.mit-license.org/2012

import time, errno, threading, stat, os
import serial, copy, traceback

SEROPTS = {
    "port": "/dev/ttyUSB0",
    "baudrate": 9600,
    "timeout": 5
    }


import fuse
from fuse import Fuse

# Must specify Fuse API version
fuse.fuse_python_api = (0, 2)

fuse.feature_assert("has_fsinit", "has_fsdestroy")


DIR = 0755 | stat.S_IFDIR
FILE = 0644 | stat.S_IFREG
LINK = 0644 | stat.S_IFLNK

def closeIgnoringError(closeable):
  try:
    closeable.close()
  except:
    pass # ignore


def reader(server, producer):
  server.log_message("Consumer thread starting")
  is_open = False
  open_when = time.time()
  while not server.done.wait(0.1):
    try:
      if not is_open and time.time() >= open_when:
        server.log_message("Opening the producer")
        messages = []
        producer.open(messages)
        for msg in messages:
          server.log_message(msg)
        is_open = True

      if is_open:
        data = producer.get()
        if data:
          server.add_reading(data)
    except:
      err = traceback.format_exc()
      server.log_message("Error in the consumer thread: %s" % (err, ))
      closeIgnoringError(producer)
      is_open = False
      server.log_message("Will re-open the producer in 60 seconds...")
      open_when = time.time() + 60

  if not is_open:
    closeIgnoringError(producer)
  server.log_message("Consumer thread stopping")

class Item(object):
  def __init__(self, mode, name, data):
    self.atime = self.mtime = self.ctime = time.time()
    self.data = data
    self.name = name
    self.mode = mode

  def fill_stat(self, stat):
    stat.st_mode  = self.mode
    stat.st_ino   = 0
    stat.st_dev   = 0
    stat.st_nlink = 1
    stat.st_uid   = os.getuid()
    stat.st_gid   = os.getgid()
    stat.st_size  = len(self.data)
    stat.st_atime = self.atime
    stat.st_mtime = self.mtime
    stat.st_ctime = self.ctime
    return stat

  def set_data(self, data):
    self.data = data
    self.mtime = time.time()

class Log(Item):
  def __init__(self):
    Item.__init__(self, FILE, "log", "")

  def log_message(self, message):
    self.set_data(self.data + message + "\n")

class Reading(Item):
  def __init__(self, name, data):
    Item.__init__(self, FILE, name, data)

class Filesystem(Fuse, Item):

  def __init__(self, *args, **kw):
    self._lock = threading.Lock()
    self._files = {}
    self._added = [] # to be able to purge in time order
    self._log = Log()
    self._latest = Item(LINK, "latest", "none")

    Fuse.__init__(self, *args, **kw)
    Item.__init__(self, DIR, "/", self._files)

    self.add_file(self._log)
    self.add_file(self._latest)

    # Default options
    self.keep = 60
    self.port = SEROPTS["port"]

  def add_file(self, file):
    self._files["/" + file.name] = file

  def find_item(self, path):
    if path == "/":
      return self
    with self._lock:
      if not path in self._files:
        return None
      return self._files[path]

  def log_message(self, message):
    # Don't care about threading issues for now
    self._log.log_message(message)

  def add_reading(self, data):
    name = str(int(time.time()))
    r = Reading(name, data)
    
    with self._lock:
      self.add_file(r)
      self._latest.set_data(name)

      self.purge_old_readings(r)

  def purge_old_readings(self, reading):
      self._added.append(reading.name)
      while len(self._added) > self.keep:
        name = self._added.pop(0)
        del self._files["/" + name]

  def getattr(self, path):
    item = self.find_item(path)
    if not item:
      return -errno.ENOENT
    return item.fill_stat(fuse.Stat())

  def readdir(self, path, offset):
    with self._lock:
      for _, f in self._files.iteritems():
        yield fuse.Direntry(f.name)

  def read(self, path, length, offset):
    item = self.find_item(path)
    if item:
      return item.data[offset:offset+length]
    return ""

  def readlink(self, path):
    return self._latest.data

  def fsinit(self):
    self.reader_thread = t = threading.Thread(target=reader, args=(self, self.producer_class(self.port)))
    self.done = threading.Event()
    t.start()

  def fsdestroy(self):
    self.done.set()
    self.reader_thread.join()

class Ivt490(object):

  def __init__(self, port):
    self.port = port

  def open(self, messages):
    opts = copy.copy(SEROPTS)
    opts["port"] = self.port
    messages.append("Using serial port options %s" % (opts, ))
    self.ser = serial.Serial(**opts)

  def get(self):
    line = self.ser.readline()
    if len(line) > 0 and line[0] != "\x00":
      secs = str(int(time.time()))
      csv = ";".join([field.strip() for field in line.rstrip().split(";")])
      return "%s;%s" % (secs, csv)
    return None

  def close(self):
    if hasattr(self, "ser"):
      self.ser.close()

def main():
  global running

  usage = """
Extracts data from an IVT490 heat pump and publishes readings in a FUSE file system.

""" + Fuse.fusage

  server = Filesystem(version="%prog " + fuse.__version__, usage=usage)
  server.log_message("Main program starting")

  server.parser.add_option(mountopt="keep", metavar="COUNT", default=server.keep, type="int",
                           help="Number of readings to keep [default: %default]")
  server.parser.add_option(mountopt="port", metavar="DEVICE", default=server.port,
                           help="Serial port to read data from [default: %default]")
  server.parse(values=server, errex=1)

  server.producer_class = Ivt490
  server.log_message("Keeping %d readings" % (server.keep, ))
  try:
    server.main()
  except Exception, e:
    print "An error occurred: " + str(e)


if __name__ == '__main__':
    main()
