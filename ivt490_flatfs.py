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


def reader(log, producer, callback, done):
  log("Consumer thread starting")
  is_open = False
  open_when = time.time()
  while not done.wait(0.1):
    try:
      if not is_open and time.time() >= open_when:
        log("Opening the producer")
        messages = []
        producer.open(messages)
        for msg in messages:
          log(msg)
        is_open = True

      if is_open:
        data = producer.get()
        if data:
          callback(data.split(";"))
    except:
      err = traceback.format_exc()
      log("Error in the consumer thread: %s" % (err, ))
      closeIgnoringError(producer)
      is_open = False
      log("Will re-open the producer in 60 seconds...")
      open_when = time.time() + 60

  if not is_open:
    closeIgnoringError(producer)
  log("Consumer thread stopping")

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
  def __init__(self, name, data, ts):
    Item.__init__(self, FILE, name, data)
    self.atime = self.mtime = self.ctime = ts

class Filesystem(Fuse, Item):

  def __init__(self, *args, **kw):
    self._lock = threading.Lock()
    self._files = {}
    self._projected = []
    self._log = Log()

    Fuse.__init__(self, *args, **kw)
    Item.__init__(self, DIR, "/", [])

    self.add_file(self._log)

    # Default options
    self.port = SEROPTS["port"]

  def add_file(self, file):
    self._files["/" + file.name] = file

  def remove_file(self, name):
    del self._files["/" + name]

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

  def _read_projections(self):
    ret = {}
    if not self.projections:
      return ret
    if not os.path.exists(self.projections):
      if not self._logged_missing_projections:
        self.log_message("Cannot find projections file: " + self.projections)
        self._logged_missing_projections = True
      return ret
    with open(self.projections, "r") as f:
      for line in f:
        projection = line.strip()
        if len(projection) > 0:
          name, calc = projection.split("=")
          ret[name] = calc
    return ret

  def _clear_projected(self):
    while len(self._projected) > 0:
      p = self._projected.pop()
      self.remove_file(p)

  def add_reading(self, data):
    ts = time.time()
    projections = self._read_projections()
    with self._lock:
      values = {}
      for idx, val in enumerate(data):
        values["f" + str(idx + 1)] = int(val)
        r = Reading(".f" + str(idx + 1), val, ts)
        self.add_file(r)
      self._clear_projected()
      for name, calc in projections.iteritems():
        try:
          val = eval(calc, {}, values)
        except Exception, err:
          self.log_message("Projection %s failed: %s" % (calc, str(err)))
        r = Reading(name, str(val), ts)
        self.add_file(r)
        self._projected.append(name)


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
    return -errno.ENOENT

  def fsinit(self):
    log = self.log_message
    cb = self.add_reading
    self.done = threading.Event()
    self.reader_thread = t = threading.Thread(target=reader, args=(log, self.producer_class(*self.producer_args), cb, self.done))
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
      csv = ";".join([field.strip() for field in line.rstrip().split(";")])
      return csv
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

  server.parser.add_option(mountopt="port", metavar="DEVICE", default=server.port,
                           help="Serial port to read data from [default: %default]")
  server.parser.add_option(mountopt="projections", metavar="FILE", default=None,
                           help="File to read projections from [default: %default]")
  server.parse(values=server, errex=1)

  if server.projections:
    server.projections = os.path.abspath(server.projections)

  server.producer_class = Ivt490
  server.producer_args = [server.port]
  try:
    server.main()
  except Exception, e:
    print "An error occurred: " + str(e)


if __name__ == '__main__':
    main()
