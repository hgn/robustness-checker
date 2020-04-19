#!/usr/bin/python3

import os
import sys
import time
import signal
import subprocess
import datetime
import random
import systemd
import systemd.journal

from typing import List
from typing import Optional


# Differantiate between Python applications a C applications
# The former does not test memory leaks and how to react to
# SIGTERM
APPLICATIONS = {
        # Python application checked for SIGKILL and the
        # proper handling of thereof. Or third party applications
        # like avahi
        "sigkill-able" : [
            "foo",
            "bar"
        ],
        # C lang applications are memory checked
        # and SIGTERM MUST be implemented.
        "sigterm-able" : [
            "foo",
            "bar"
        ]
}


# check interval between runs we redo this every 10 minutes, not once Just to
# trigger an error by doing it a little bit differnt. Thus the randomiyed
# applciation ordering
SLEEP_CHECK_INTERVAL = 60 * 10


# time between C programms checks. This time is 5 minutes, just to see if
# restarting was really successfully and IPC is working properly again. It his
# time is to small we will probably suspect the wrong (subsequent) application.
# So take time that failures can arise now.
SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST = 60 * 5


# time, waiting until SIGTERM is processed and process should be shutdowned
# savely
SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME = 5


def applications_shuffled(bucket: str) -> Optional[List[str]]:
    """ Return list of randomized applications based on the
    applcation list entries sigkill-anle or sigterm-able
    """
    # shuffle works in-place, so make a copy of it
    apps = APPLICATIONS[bucket][:]
    random.shuffle(apps)
    return apps


def log(msg: str) -> None:
    """ Print the string to stderr and append UTC time
    """
    dt = datetime.datetime.utcnow()
    time = dt.strftime('%H:%M:%S.%f')[:-3]
    print("{} - {}".format(time, str(msg)))
    systemd.journal.send(msg)


def pids_by_process_name(name: str) -> Optional[List[int]]:
    """ Returns all pids associated with a given process name
    """
    try:
        return list(map(int, subprocess.check_output(["pidof", name]).split()))
    except subprocess.CalledProcessError:
        return None


def process_alive(name: str) -> Optional[bool]:
    """ check if a proces is alive and running.
    If not this function returns false.
    Note: if several instances (several pids) are
    available, it  just returns true
    """
    try:
        subprocess.check_output(["pidof", name])
        return True
    except subprocess.CalledProcessError:
        return None


def pid_alive(pid: str) -> bool:
    """ Similar to process_alive() but by pid,
    not name
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def check_sigterm() -> None:
    """ Iterate over all C Programms and send SIGTERM
    Process should terminate and free all memory, leak sanitizer
    should not show up
    """
    log('Test Suite: Sigterm Checks')
    for application in applications_shuffled('sigterm-able'):
        log('next checked application: "{}"'.format(application))
        pids = pids_by_process_name(application)
        if not pids:
            log('Error, process "{}" should be there, but cannot find it'.format(application))
            continue
        for pid in pids:
            # normally only one process per application name should be
            # available, but we never know -> kill every process
            # with this name
            log("Send process {} [pid: {}] SIGTERM signal".format(application, pid))
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception as e:
                log("catched exception during SIGTERM signal: {}".format(str(e)))
            log("Now sleeping {} seconds for process shutdown & restarting".format(SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME))
            time.sleep(SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME)
            # now check that the given application is correctly restarted by
            # systemd and alive
            new_pids = pids_by_process_name(application)
            if new_pids:
                log('Application "{}" is alive, please check that it was properly'.format(application))
                log("finalized (no memory leaks, closing all resources, ...) and")
                log("successfully restart by systemd (please take a look in the journal)")
                if new_pids.sort() == pids.sort():
                    log("Warning: new PID and old PIDs are identical - that is legal and to")
                    log("some degree expected! But please make sure the process was *really*")
                    log("restarted after sending SIGTERM")
                pids_str = ', '.join(str(x) for x in pids)
                new_pids_str = ', '.join(str(x) for x in pids)
                log("Previous PID: {}, New PID: {}".format(pids_str, new_pids_str))
            else:
                log('application "{}" is not detectable! Please check'.format(application) + 
                    ' journal for application specific entries')
        log("Please check now if overall system is working properly again (IPC, ...)")
        log("Robustness-Tester will now pause for {} seconds".format(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST))
        time.sleep(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST)


def check_sigkill() -> None:
    """ Iterate over all C Programms and send SIGKILL
    """
    log('Test Suite: Sigkill Checks')
    for application in applications_shuffled('sigkill-able') + applications_shuffled('sigterm-able'):
        log('Next checked application: "{}"'.format(application))
        pids = pids_by_process_name(application)
        if not pids:
            log('Error, process "{}" should be there, but cannot find it'.format(application))
            continue
        for pid in pids:
            # normally only one process per name should be
            # available, but we never know -> kill every process
            # with this name
            log("Send process {} [pid: {}] SIGKILL signal".format(application, pid))
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception as e:
                log("Catched exception during kill signal: {}".format(str(e)))
            log("Now sleeping {} seconds for process shutdown & restarting".format(SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME))
            time.sleep(SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME)
            # now check that the given application is correctly restarted by
            # systemd and alive
            new_pids = pids_by_process_name(application)
            if new_pids:
                log('Application "{}" was successfully respawed!'.format(application))
            else:
                log('Error: application "{}" is not detectable! Please check'.format(application) + 
                    ' journal for application specific entries')
        log("Please check now if overall system is working properly again (IPC, ...)")
        log("Robustness-Tester will now pause for {} seconds".format(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST))
        time.sleep(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST)


def print_agenda():
    log('Robustness-Tester started')
    log('Test order: 1) sigterm check suite, 2) sigkill check suite')
    sigterm_apps = ', '.join(APPLICATIONS['sigterm-able'])
    log('Sigterm applications (order randomized): {}'.format(sigterm_apps))
    sigkill_apps = ', '.join(APPLICATIONS['sigkill-able'] + APPLICATIONS['sigterm-able'])
    log('Sigkill applications (order randomized, inkludes sigterm apps): {}'.format(sigkill_apps))

def main():
    print_agenda()
    while (True):
        check_sigterm()
        check_sigkill()
        log("Sleeping for {} seconds until the next major test run".format(SLEEP_CHECK_INTERVAL))
        time.sleep(SLEEP_CHECK_INTERVAL)


if __name__ == "__main__":
    main()


