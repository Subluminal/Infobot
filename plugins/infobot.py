"""
Info functionality

* depends: database, auth_ng, wait_for
"""
from .util import coroutine
from .util.decorators import command, init, process_privmsg
from .sed import Substitution
from .wait_for import wait_for_auth
from .util.data import get_doc
from functools import partial
import re
import traceback
import inspect
import gc

db = None

def caller():
    code_obj = inspect.stack()[1][0].f_code
    referrers = [x for x in gc.get_referrers(code_obj) if inspect.isfunction(x)]
    return referrers[0]

def addinfo(bot, pmsg):
    nick, chan, msg = process_privmsg(pmsg)
    ret, cr = addinfo_inner(bot, nick, chan, msg, pmsg)
    if ret:
        wait_for_auth(bot, nick, lambda authed: (next(cr), cr.send(authed)))

@coroutine
def addinfo_inner(bot, nick, chan, msg, pmsg):
    m = re.search(r"^!add .+", msg)
    if not m:
        yield False

    if ' ' not in msg:
        bot.msg(chan, "Usage: !add <info>")
        yield False

    user, host = pmsg['host'].split("@")
    user = user.split("!")[1]

    info = msg.split(" ", 1)[1]

    yield True
    is_authed = (yield)

    if not is_authed:
        bot.notice(nick, "You are not registered with NickServ or not properly identified.")
        yield

    if 'alias' in info:
        alias = msg.split()[2]

        success = db.execute("SELECT addalias(%s, %s);", (nick, alias)).fetchone()[0]

        if not success:
            bot.notice(nick, "Error setting alias; you are creating an"
                " infinitely looping alias chain.")
        else:
            bot.notice(nick, "The info of your current nick %s now points to %s." % (nick, alias))

    else:
        db.execute("SELECT addinfo(%s, %s, %s, %s);", (nick, user, host, info))
        bot.notice(nick, "Info set to '%s'" % (info))

    yield

__callbacks__ = {"PRIVMSG": [addinfo]}

@command('infohist', '^!$name(\s|$)')
def getinfohist(bot, nick, chan, gr, arg):
    """!infohist -> get your info history. """
    if not arg:
        arg = 0
    else:
        try:
            arg = int(arg)
        except:
            arg = 0

    info = db.execute("SELECT nick, info FROM infohistory(%s);", (nick,)).fetchall()

    if not info:
        return bot.notice(nick, "No info found for {0}.".format(nick))

    for n, item in list(enumerate(info))[::-1][int(arg):int(arg)+6]:
        bot.notice(nick, "#%d: %s →  %s: %s" % (n, arg, item[0], item[1]))

@command('inforestore', '^!$name(?:\s|$)', pass_privmsg=True)
def inforestore(bot, nick, chan, arg, pmsg):
    """!inforestore <n> -> set your info to a previous info. """
    try:
        arg = int(arg)
    except:
        return bot._msg(chan, get_doc())

    if not arg:
        return bot._msg(chan, get_doc())

    user, host = pmsg['host'].split("@")
    user = user.split("!")[1]

    info = db.execute("SELECT nick, info FROM infohistory(%s);", (nick,)).fetchall()

    if not info:
        return bot.notice(nick, "No info found for {0}.".format(nick))

    toset = info[arg]

    db.execute("SELECT addinfo(%s, %s, %s, %s);", (nick, user, host, toset[1]))
    bot.notice(nick, "Info set to '%s'" % (toset[1]))


@command('info', '^(!|@)$name(\s|$)')
def getinfo(bot, nick, chan, gr, arg):
    """ !info <nick> -> get the info for a given user. """
    if not arg:
        return bot._msg(chan, get_doc())
    info = db.execute("SELECT nick, info FROM info(%s);", (arg,)).fetchone()
    if gr[0] == '@':
        msgfn = partial(bot._msg, chan)
    else:
        msgfn = partial(bot.notice, nick)

    if not info:
        return msgfn("No info found for {0}. Use '!add <info>' to add your info.".format(arg))

    if info[0].lower() == arg.lower():
        return msgfn("%s: %s" % (arg, info[1]))
    msgfn("%s → %s: %s" % (arg, info[0], info[1]))

@command('del|rm', r'^!($name)(\s|$)')
def rmalias(bot, nick, chan, _, arg):
    """ !del <type> -> delete 'alias' or 'info' """
    if not arg or arg not in ('alias', 'info'):
        return bot._msg(chan, get_doc())

    if not bot.auth.is_authed(nick):
        return bot.notice(nick, "You are not registered with NickServ or not properly identified.")

    if arg == 'alias':
        db.execute("SELECT delalias(%s);", (nick,))
        bot.notice(nick, "Your nick now points to itself instead of to an alias.")
    else:
        db.execute("SELECT delinfo(%s);", (nick,))
        bot.notice(nick, "Deleted info.")

@command('append', r'^!$name(?:\s|$)', pass_privmsg=True)
def appendinfo(bot, nick, chan, arg, pmsg):
    """ !append <info> -> Append <info> to your info. """
    if not arg:
        return bot._msg(chan, get_doc())

    user, host = pmsg['host'].split("@")
    user = user.split("!")[1]

    if not bot.auth.is_authed(nick):
        return bot.notice(nick, "You are not registered with NickServ or not properly identified.")

    alias, info = db.execute("SELECT nick, info FROM info(%s)", (nick,)).fetchone()
    info += (" " + arg)
    db.execute("SELECT addinfo(%s, %s, %s, %s);", (alias, user, host, info))
    bot.notice(nick, "Info set to '%s'" % (info))

@command('sql', auth=True)
def execsql(bot, nick, chan, arg):
    db.execute(arg)
    try:
        bot._msg(chan, "%s" % ", ".join([str(list(i)) for i in db.fetchall()]))
    except:
       traceback.print_exc()

@command('sed', '^!$name .+', pass_privmsg=True)
def sedinfo(bot, nick, chan, arg, pmsg):
    # first, get the info for the current nick
    info = db.execute("SELECT nick, info FROM info(%s);", (nick,)).fetchone()

    user, host = pmsg['host'].split("@")
    user = user.split("!")[1]

    if not bot.auth.is_authed(nick):
        return bot.notice(nick, "You are not registered with NickServ or not properly identified.")

    try:
        sub = Substitution(arg)
    except TypeError as e:
        return bot.notice(nick, "Error: %s" % (e))

    newinfo = sub.do(info[1])

    if info[0].lower() != nick.lower():
        bot.notice(nick, "Note: because your current nick is an alias, your alias will"
                "be removed and your info will be set to %r." % (newinfo))

    db.execute("SELECT addinfo(%s, %s, %s, %s);", (nick, user, host, newinfo))
    bot.notice(nick, "Info set to '%s'" % (newinfo))

@init
def init(bot):
    global db
    db = bot.data["db"]
