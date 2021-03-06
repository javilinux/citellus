#!/usr/bin/env python
# encoding: utf-8
#
# Description: Hook for procesing profile definitions and appending results formated to json
# Author: Pablo Iranzo Gomez (Pablo.Iranzo@gmail.com)

from __future__ import print_function

import os
import re

try:
    import citellusclient.shell as citellus
except:
    import shell as citellus

# Load i18n settings from citellus
_ = citellus._

extension = "profiles"
pluginsdir = os.path.join(citellus.citellusdir, 'plugins', extension)


def init():
    """
    Initializes module
    :return: List of triggers for extension
    """
    return []


def plugidsforprofile(profile, plugins):
    """
    Gets plugin id's related with profile includes/excludes
    :param profile: profile file to open
    :param plugins: plugins in citellus exection
    :return: array of id's
    """
    # Open Profile definition for read and fill filters for plugins
    include = []
    exclude = []
    with open(profile, 'r') as f:
        for line in f:
            if re.match('\A\+.*', line):
                include.append(line[1:].strip())
            if re.match('\A\-.*', line):
                exclude.append(line[1:].strip())
    ids = citellus.getids(plugins=plugins, include=include, exclude=exclude)

    return ids


def run(data, quiet=False):  # do not edit this line
    """
    Executes plugin
    :param quiet: be more silent on returned information
    :param data: data to process
    :return: returncode, out, err
    """

    # prefill plugins we had used:
    plugins = []
    for item in data:
        plugin = {'plugin': data[item]['plugin'],
                  'id': data[item]['id']}
        plugins.append(plugin)

    # Find available profile definitions
    profiles = citellus.findplugins(folders=[pluginsdir], executables=False, fileextension='.txt')
    for item in profiles:
        uid = citellus.getids(plugins=[item])[0]
        profile = item['plugin']

        plugin = dict(item)

        # Precreate storage for this profile
        name = "Profiles: %s" % os.path.basename(os.path.splitext(profile.replace(pluginsdir, ''))[0])
        subcategory = ''
        category = name

        data[uid] = {"category": category,
                     "hash": item['hash'],
                     "plugin": item['plugin'],
                     "name": name,
                     "result": {"rc": int(os.environ['RC_OKAY']),
                                "err": "",
                                "out": ""},
                     "time": 0,
                     "backend": "profile",
                     "id": uid,
                     "subcategory": subcategory}

        metadata = {'description': citellus.regexpfile(filename=plugin['plugin'], regexp='\A# description:')[14:].strip(),
                    'long_name': citellus.regexpfile(filename=plugin['plugin'], regexp='\A# long_name:')[12:].strip(),
                    'bugzilla': citellus.regexpfile(filename=plugin['plugin'], regexp='\A# bugzilla:')[11:].strip(),
                    'priority': int(citellus.regexpfile(filename=plugin['plugin'], regexp='\A# priority:')[11:].strip() or 0)}
        data[uid].update(metadata)

        # Start asembling data for the plugins relevant for profile
        data[uid]['result']['err'] = ''
        ids = plugidsforprofile(profile=profile, plugins=plugins)
        for id in ids:
            data[uid]['result']['err'] = data[uid]['result']['err'] + "\n" + "%s" % {'plugin': data[id]['plugin'].replace(os.path.join(citellus.citellusdir, 'plugins'), ''), 'err': data[id]['result']['err'].strip(), 'rc': data[id]['result']['rc']}

        data[uid]['components'] = ids

    return data


def help():  # do not edit this line
    """
    Returns help for plugin
    :return: help text
    """

    commandtext = _("This hook proceses Citellus profiles and assembles data for each one to be appended to results json")
    return commandtext
