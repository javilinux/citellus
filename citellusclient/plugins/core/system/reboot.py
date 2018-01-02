#!/bin/env python

# Copyright (C) 2017  David Vallee Delisle (dvd@redhat.com)

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# long_name: Reboot Validation
# description: We try to guess if the latest reboot(s) were clean or not

# Loading some modules
from __future__ import print_function
import os
import re
import sys
from datetime import datetime
from datetime import timedelta

# Getting environment
root_path = os.getenv('CITELLUS_ROOT', '')


# Defining some globals
now = datetime.now()
events = []
lastcontext = None
RC_OKAY = int(os.environ['RC_OKAY'])
RC_FAILED = int(os.environ['RC_FAILED'])
RC_SKIPPED = int(os.environ['RC_SKIPPED'])
exitCode = RC_OKAY
errorMsg = ""
rebootList = ""


def errorprint(*args, **kwargs):
    """
    Prints to stderr a string
    :type args: String to print
    """
    print(*args, file=sys.stderr, **kwargs)


def exitcitellus(code=False, msg=False):
    """
    Exits back to citellus with errorcode and message
    :param msg: Message to report on stderr
    :param code: return code
    """
    if msg:
        errorprint(msg)
    sys.exit(code)


def gettime(line):
    """
    Extracts the timestamps off a regular syslog line
    :param line: syslog line
    """
    mg = re.match("([a-zA-Z]{3})[\s]+([0-9]+)[\s]+([0-9]+):([0-9]+):([0-9]+)", line)
    ts = mg.group(1) + " " + mg.group(2) + " " + mg.group(3) + ":" + mg.group(4) + ":" + mg.group(5)
    """
    Because we don't have the year in the timestamp, we need to guess it
    and it can be tricky when we're overlapping 2 years
    """
    thisyear = now.year
    # With UTC, we can consider that now in 12h later
    nnow = now + timedelta(hours=12)
    while True:
        # Prepending the year to the TS and parsing
        tts = str(thisyear) + " " + ts
        tsobj = datetime.strptime(tts, "%Y %b %d %H:%M:%S")
        if tsobj < nnow:
            # We're not in the future
            return tsobj
        # Let's try once more
        thisyear -= 1


def setcontext(context):
    """
    Sets the context to the latest event
    :param context: either bootloader or os
    """
    global lastcontext
    lastcontext = context
    # We sort our event to get the latest one
    events.sort(key=lambda x: x.time, reverse=True)
    events[0].context = context


def findevent(context, desc, index, reverse):
    """
    Returns the first event with a specific context and desc,
    starting at $index, reverse or not
    :param context: context to look for
    :param desc: description; either start or stop
    :param index: start looking at a specific index
    :param reverse: sort by time asc or desc
    """
    tmp = reversed(list(events[:index])) if reverse is True else list(events[index:])
    for i in tmp:
        if i.context == context and i.desc == desc:
            return i
    return None


class Event(object):
    def __init__(self, desc, time, context=None, status=None, index=None, duration_down=0, duration_bootloader=0, duration_os=0):
        """
        Events are journald stop/start events in syslog. This is how we determine the timestamps
        :param desc: Description: Either stop or start; all events
        :param time: datetime object; all events
        :param context: This is eiter os or bootloader; all events
        :param status: only three possible values: clean, hard or None; seen in os start
        :param index: This is the index number of the object once we sort the list of events at the end; all events
        :param duration_down: This is the number of seconds a system was down; seen in bootloader start
        :param duration_bootloader: The number of seconds the bootloader took to initialize; seen in bootloader stop
        :param duration_os: This is the number of seconds the os was up; seen in os stop
        """
        self.desc = desc
        self.time = time
        self.context = context
        self.status = status
        self.index = index
        self.duration_down = duration_down
        self.duration_bootloader = duration_bootloader
        self.duration_os = duration_os

    def __repr__(self):
        """
        Easier to develop with this, it prints nicely the objects
        """
        from pprint import pformat
        return pformat(vars(self), indent=4, width=1000)

    def __iter__(self):
        return self.index


def main():
    global lastcontext
    global events
    global now
    global root_path
    global exitCode
    global errorMsg
    global rebootList
    global RC_OKAY
    global RC_FAILED
    global RC_SKIPPED

    if os.path.isfile(root_path + "/etc/redhat-release") is False:
        exitcitellus(code=RC_SKIPPED, msg="Non Red Hat system, skipping")
    if "Red Hat Enterprise Linux Server release 7" not in open(root_path + "/etc/redhat-release").read():
        exitcitellus(code=RC_SKIPPED, msg="Only works on Red Hat Enterprise Linux 7 or greater, skipping")

    # Syslog parsing starts here
    f = open(root_path + "/var/log/messages", "r")
    for line in f:
        # chomp
        line = line.rstrip()
        # canary: journald is stopped
        if re.match(".* Journal stopped$", line):
            ts = gettime(line)
            events.append(Event("stop", ts))
            """
            if we are in the bootloader context,
            we need to tag the event
            """
            if lastcontext == "bootloader":
                setcontext("bootloader")
                lastcontext = None
        # canary: journald is started
        elif re.match(".* Journal started$", line) and lastcontext != "bootloader":
            ts = gettime(line)
            events.append(Event("start", ts))
        # canary: we are in the bootloader init
        elif re.match(".* kernel: Command line: .*", line):
            lastcontext = "bootloader"
            ts = gettime(line)
            events.append(Event("start", ts, "bootloader"))

    f.close()
    if len(events) == 0:
        exitcitellus(code=RC_SKIPPED, msg="No reboot found")

    """
    File parsing is completed,
    we need sort and keep index for each event
    We also need to define os context on all other events
    """
    events.sort(key=lambda x: x.time, reverse=False)
    for i, e in enumerate(events):
        e.index = i
        if e.context is None:
            e.context = "os"
        events[i] = e

    """
    We can now analyze all the events and find unclean reboots
    """
    for i, e in enumerate(events):
        # Next Event: used for a os.stop, helps determine if reboot was clean
        ne = events[i + 1] if i + 1 < len(events) else None
        # Previous Event: used for bootloader.stop, helps determine the duration of bootloader process
        pe = events[i - 1] if i - 1 >= 0 else None

        # When we have an os event, we can't just blindly take the next event
        # We need to find and match with findevent
        if e.context == "os":
            lookup_desc = "start" if e.desc == "stop" else "stop"
            # Matched Previous Event: previous event that matches these criteria
            mpe = findevent("os", lookup_desc, i, True)
            # Matched Next Event: next event that matches these criteria
            mne = findevent("os", lookup_desc, i, False)
        else:
            mpe = None
            mne = None

        if e.context == "os" and e.desc == "stop":
            # sets a clean reboot if the system was stopped in the previous 5 minutes
            if ne.desc == "start" and ne is not None:
                duration = (ne.time - e.time).total_seconds()
                if duration < 300:
                    ne.status = "clean"
                ne.duration_down = duration
            # calculates the duration that the os was up
            if mpe is not None and mpe.desc == "start":
                e.duration_os = (e.time - mpe.time).total_seconds()
        # calculate the duration of the bootloader sequence
        elif e.context == "bootloader" and e.desc == "stop" and pe.context == "bootloader" and pe.desc == "start":
            e.duration_bootloader = (e.time - pe.time).total_seconds()
        # calculates the duration of the downtime
        elif e.context == "os" and e.desc == "start":
            # So we have found a mpe, we need to find the downtime
            if mpe is not None:
                e.duration_down = (e.time - mpe.time).total_seconds()
            # When we are unable to find the stop event OR
            # the first stop event dates from more than 300s, we have possibly a hard reboot
            if mpe is None or (mpe is not None and (e.time - mpe.time).total_seconds() > 300):
                e.status = "hard"

        # Now we save the events
        events[i] = e
        if pe is not None:
            events[i - 1] = pe
        if i + 1 < len(events):
            events[i + 1] = ne
        if mpe is not None:
            events[mpe.index] = mpe
        if mne is not None:
            events[mne.index] = mne

    format_rebootlist_ev = '{:%Y-%m-%d %H:%M:%S} {:10.10} {:15.15} {:6.6} {:4.0f} {:3.0f} {:5.0f}\n'
    format_rebootlist_hd = '{:19.19} {:10.10} {:15.15} {:6.6} {:>4.4} {:>3.3} {:>5.5}\n'
    numErrors = 0
    # Here we print the results
    for i, e in enumerate(events):
        if e.status == "hard":
            exitCode = RC_FAILED
            errorMsg += "- Hard reboot found"
            numErrors += 1
        if e.duration_bootloader > 20:
            exitCode = RC_FAILED
            errorMsg += "- Bootloader took more than 20s to init"
            numErrors += 1
        if e.duration_down > 600:
            exitCode = RC_FAILED
            errorMsg += "- System was down for more than 10m"
            numErrors += 1
        rebootList += format_rebootlist_ev.format(e.time, e.context, e.desc, e.status, e.duration_bootloader, e.duration_os, e.duration_down)
    out = str(numErrors) + " problem(s) found\n" + errorMsg + "\nEvents:\n" + format_rebootlist_hd.format('Time', 'Context', 'Description', 'Status', 'Boot', 'OS', 'Down') + rebootList
    exitcitellus(code=exitCode, msg=out)


if __name__ == "__main__":
    main()