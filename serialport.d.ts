/// <reference path="node.d.ts" />

declare module "serialport" {
  import events = module("events");

  export interface ParserFunc {
    (emitter: events.NodeEventEmitter, buffer: NodeBuffer): void;
  }

  interface Parsers {
    raw: ParserFunc;
    readline: (delimiter?: string) => ParserFunc;
  }

  export interface SerialOptions {
    baudrate?: number;
    databits?: number;
    stopbits?: number;
    parity?: string;
    buffersize?: number;
    parser?: ParserFunc;
  }
  /*export var parsers = {
    raw: ParserFunc,
    readline: (delimiter?: string): ParserFunc
  };*/
  export var parsers: Parsers;
  export class SerialPort {
    constructor(port: string, options: SerialOptions);
    on(event: string, listener: Function): void;
    close(): void;
  }
}

