# Robustness Tester

Simple iterate over a list of processes (randomized order) and send SIGKILL or
SIGTERM to the processes. Which signal is send is configured and must be decided
by the user. Not every application react properly to SIGTERM. Other applications
are required to do so. If compiled with `-fsanitize=leak` and SIGTERM frees all memory
after this 'Robustness Tester' should catch such errors.

# Usage

## Define application list on top of robustness-tester.py

```
$ $EDITOR ./robustness-tester.py
```

## Start the Robustness Tester:

```
$ sudo systemd-run ./robustness-tester.py
Running as unit: run-r6736d845ae3b414899f47fdbecd08824.service

# check if running correctly:
$ sudo systemctl status run-r6736d845ae3b414899f47fdbecd08824.service
```

Why via `systemd-run`? Because the output of all other applications will be in
the journal - in one journal and you can correlate them easily.

## Follow Journal - Spot Suspicious Log Entries

```
$ sudo journalctl -f -n 100
```


## Finally - Stop Robustness Tester

```
$ sudo systemctl stop run-r6736d845ae3b414899f47fdbecd08824.service
```



