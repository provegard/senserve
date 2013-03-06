///<reference path="node.d.ts"/>
///<reference path="serialport.d.ts"/>

import sp = module("serialport");
import repl = module("repl");

var SerialPort = sp.SerialPort;
var SERPORT = "/dev/ttyUSB0";
var SEROPTS = {
  "baudrate": 9600,
  "parser": sp.parsers.readline("\r\n")
};

var port = new SerialPort(SERPORT, SEROPTS);

port.on("open", function () {
  console.log('open');
  port.on('data', function(data) {
    console.log('data received: ' + data);
  });
  port.on("error", function(msg : string) {
    console.log("error: " + msg);
  });
});

console.log("repl");
var r = repl.start({});
r.on("exit", function() {
  port.close();
});
