"""
IRC API - irc.py
"""

import collections
import sys
from .buffer import Buffer
from . import parse
from .threads import HandlerThread
import socket
import types
import inspect
import logging
import threading

logger = logging.getLogger("irc")

CONFIG = {}

class IRCHandler(object):
    """ IRCHandler(Dict<string, object> config) - a standard IRC handler """
    def __init__(self, bconfig, verbose=False, print_raw=False):
        globals()["CONFIG"] = bconfig
        self.sock = socket.socket()
        self.sock_file = None
        self.verbose = verbose
        self.print_raw = print_raw
        self.running = True
        self.buff = Buffer()
        self.outbuff = Buffer()
        self.is_welcome = False

        self.cond = threading.Condition(threading.Lock())

        self.cmd_thread = HandlerThread(self, self.cond)
        self.cmd_thread.daemon = True

        self.cond.acquire()

    def connect(self):
        """ Connect to the IRC server """
        self.cmd_thread.start()
        logger.debug("Waiting for handler thread...")
        self.cond.wait()
        logger.debug("Handler thread sent notify.")

        server = CONFIG["server"].split("|")[0].split(":")
        self.sock.connect((server[0], int(server[1])))
        try:
            passwd = CONFIG["server"].split("|", 1)[1]
            if passwd:
                self._send("PASS "+passwd)
        except:
            pass

    def handle_messages(self):
        for msg in self.buff:
            pmsg = parse.parse(msg)
            if pmsg["method"] == "PING":
                self._send("PONG "+pmsg["arg"])
            elif pmsg["method"] in ("376", "422"):
                self.is_welcome = True
                self.run_callback(pmsg["method"], pmsg)
            else:
                self.run_callback(pmsg["method"], pmsg)

    def run(self):
        """ The main loop. """
        self.sock_file = self.sock.makefile('rb')
        self.sendnick()
        self.senduser()
        try:
            while self.running:
                data = self.sock_file.readline().decode('utf-8', errors='ignore')
                if data == '':
                    self.running = False
                if self.print_raw:
                    logger.debug(data.strip())
                self.buff.append(data)

                self.handle_messages()

        except KeyboardInterrupt:
            sys.exit()

    def _send(self, data, newline="\r\n", sock=None):
        """ Send data through the socket and append CRLF. """
        self.outbuff.append(data+newline)
        for msg in self.outbuff:
            if self.print_raw:
                logger.debug(msg.strip())
            self.sock.sendall((msg+newline).encode("utf-8"))

    def run_callback(self, cname, *args):
        funcs = self.__irccallbacks__.get(cname, None)
        __core__ = None

        if not funcs:
            return

        for func in funcs:
            __core__ = getattr(func, "__core__", False)
            if __core__:
                if type(func) == types.MethodType:
                    func(*args)
                else:
                    func(self, *args)

        if not __core__:
            self.cmd_thread.push(cname, args)
            self.switch()

    def switch(self):
        logger.debug("Calling notify")
        self.cond.notify()
        logger.debug("Calling wait")
        self.cond.wait()
        logger.debug("Wait over")

    def senduser(self):
        """ Send the IRC USER message. """
        self._send("USER %s * * :%s" % (CONFIG["nick"], CONFIG["real"]))

    def sendnick(self):
        """ Send the IRC NICK message. """
        self._send("NICK %s" % (CONFIG["nick"]))

    def register_callbacks(self):
        self.__irccallbacks__ = collections.defaultdict(list)
        funcs = list(dict(inspect.getmembers(self, predicate=inspect.ismethod)).values())
        for func in funcs:
            if hasattr(func, "__irccallback_hooks__"):
                for item in func.__irccallback_hooks__:
                    logger.debug("Registering %s for %s", func, item)
                    self.__irccallbacks__[item].append(func)

    def register_callback(self, ctype, func):
        self.__irccallbacks__[ctype].append(func)


    def gracefully_terminate(self):
        """ Gracefully terminate the bot. """
        self.running = False
