#!/usr/bin/python3

import os
import sys
import time
import signal
import subprocess
import datetime
import random
import argparse
import systemd
import ctypes
import systemd.journal

from typing import List
from typing import Dict
from typing import Optional

# this can raise an error of your libc path differs!
# If it crashes here, please adjust the path to your
# glibc (hint: use "ldd /usr/bin/python3" to locate
# your path
libc = ctypes.CDLL('/lib/x86_64-linux-gnu/libc.so.6')
libc.ptrace.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p]
libc.ptrace.restype = ctypes.c_uint64

PTRACE_ATTACH = 16
PTRACE_DETACH = 17


# Differantiate between Python applications a C applications
# The former does not test memory leaks and how to react to
# SIGTERM
APPLICATIONS = {
        # Python application checked for SIGKILL and the
        # proper handling of thereof. Or third party applications
        # like avahi
        "sigkill" : [
            "foo",
            "bar"
        ],
        # C lang applications are memory checked
        # and SIGTERM MUST be implemented.
        "sigterm" : [
            "foo",
            "bar"
        ],

        # ok, ptrace(ATTACH, ...) to the application, wait
        # until the application is really stop (must be runable
        # before it can be stopped) and block the application.
        # Wait until n seconds. After this, ptrace(DETACH, ...)
        # is called. Normally, the detach does not matter, because
        # SystemD watchdog will kill the process during stop (attach)
        # state and restart the application.
        # If no process is listed in the ptrace-stop list, all processes
        # are stopped enfored (ptrace), except pid 1
        'ptrace-stop' : [
            "runner"
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


def pid_alive(pid: int) -> bool:
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
    for application in applications_shuffled('sigterm'):
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
    applications = applications_shuffled('sigkill') + \
                   applications_shuffled('sigterm')
    for application in applications:
        log('Next checked application: "{}"'.format(application))
        pids = pids_by_process_name(application)
        if not pids:
            msg = 'Error, process "{}" should be there, but cannot find it'
            log(msg.format(application))
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
            msg = "Now sleeping {} seconds for process shutdown & restarting"
            log(msg.format(SLEEP_SIGTERM_SAFE_SHUTDOWN_TIME))
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
        msg = "Robustness-Tester will now pause for {} seconds"
        log(msg.format(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST))
        time.sleep(SLEEP_BETWEEN_C_APPLICATION_SIGNAL_TEST)


def proc_status_get(pid: int) -> Dict:
    data = dict()
    with open(os.path.join('/proc/', str(pid), 'status'), 'r') as fd:
        lines = fd.readlines()
        for line in lines:
            l = line.strip()
            key, vals = l.split(':', 1)
            data[key.strip().lower()] = vals.strip()
    return data


def is_process_debugged_no_zombie(pid: int):
    """ Ok we need this: if debugged, it is alive, normally
    it will be killed and systemd will "reap dead childs', but
    for simulation mode it may happen that it is shell controlled
    and now reaped, therefore we acceped zombie applications too
    """
    try:
        data = proc_status_get(pid)
    except (IOError, OSError, Failure):
        return False
    if int(data['tracerpid']) == 0:
        return False
    if "zombie" in data['state']:
        return False
    return True


def ptrace_stop_wait_until_killed(application: str, pid: int) -> bool:
    """ Wait until a maximum time until the debugger (we) are not
    attached anymore or the process is not available anymore
    Return true if application is not debugged or false if still debuged
    """
    iterations = 10
    sleeptime = 5
    msg = "Wait {} seconds until application is restarted"
    log(msg.format(iterations * sleeptime))
    for probe in range(iterations):
        if not pid_alive(pid):
            msg = 'Application "{}" with pid:{} not alive - seems to be restarted'
            log(msg.format(application, pid))
            return True
        if not is_process_debugged_no_zombie(pid):
            msg = 'Application "{}" with pid:{} not debugged (anymore)'
            log(msg.format(application, pid))
            return True
        msg = 'Application "{}" with pid:{} still alive and ptrace attached stopped!'
        log(msg.format(application, pid))
        msg = 'Wait additional {} seconds'
        log(msg.format((iterations * sleeptime) - (probe * sleeptime)))
        # we check every 5 seconds, just to avoid flooding the journal
        time.sleep(sleeptime)
    return False


def check_ptrace_stop() -> None:
    """ Iterate over all C Programms and attach via ptrace(ATTACH, ...)
    """
    log('Test Suite: Ptrace Stop Checks')
    applications = applications_shuffled('ptrace-stop')
    if len(applications) <= 0:
        # FIXME
        # no list given, get full process list minus pid 1
        raise Exception("not implemented yet, populate process list")
    for application in applications:
        pids = pids_by_process_name(application)
        if not pids:
            log('Error, process "{}" should be there, but cannot find it'.format(application))
            continue
        for pid in pids:
            log('Stop "{}" [pid: {}] now with ptrace(ATTACH, pid, ...)'.format(application, pid))
            libc.ptrace(PTRACE_ATTACH, pid, None, None)
            stat = os.waitpid(pid, 0)
            if os.WIFSTOPPED(stat[1]):
                if os.WSTOPSIG(stat[1]) == 19:
                    log("Application {} [pid: {}] stopped!".format(application, pid))
                else:
                    log("Application {} [pid: {}] stopped with unusal status!".format(application, pid))
            else:
                log("Application stopped for some other signal: {}", os.WSTOPSIG(stat[1]))
            # now wait until systemd, watchdoged the application. Systemd will kill
            # the applicatin and restart the application if no sd_send() notifcation
            # is received within the user defined time.
            restarted = ptrace_stop_wait_until_killed(application, pid)
            if not restarted:
                log('Noes, application still stopped and not restarted!')
                log('Will detach the application now!')
            else:
                log('Application IS restarted or at least not stopped anymore - fine!')
            # detaching is always kind, yes we assume that no
            # application within the system is activly debugged
            libc.ptrace(PTRACE_DETACH, pid, None, None)



def print_agenda():
    log('Robustness-Tester started')
    log('Test order: 1) sigterm check suite, 2) sigkill check suite')
    sigterm_apps = ', '.join(APPLICATIONS['sigterm'])
    log('Sigterm applications (order randomized): {}'.format(sigterm_apps))
    sigkill_apps = ', '.join(APPLICATIONS['sigkill'] + APPLICATIONS['sigterm'])
    log('Sigkill applications (order randomized, inkludes sigterm apps): {}'.format(sigkill_apps))
    ptrace_stop_apps = ', '.join(APPLICATIONS['ptrace-stop'])
    log('Ptrace-stop applications (order randomized): {}'.format(ptrace_stop_apps))

def main(args):
    print_agenda()
    while (True):
        if not args.disable_sigterm:
            check_sigterm()
        if not args.disable_sigkill:
            check_sigkill()
        if not args.disable_ptrace_stop:
            check_ptrace_stop()
        log("Sleeping for {} seconds until the next major test run".format(SLEEP_CHECK_INTERVAL))
        time.sleep(SLEEP_CHECK_INTERVAL)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--disable-sigterm",
                   action="store_true",
                   help="disable sigterm checks")
    p.add_argument("--disable-sigkill",
                   action="store_true",
                   help="disable sigkill checks")
    p.add_argument("--disable-ptrace-stop",
                   action="store_true",
                   help="disable ptrace stop checks")
    args = p.parse_args()
    main(args)


