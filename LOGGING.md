# Log format (all teams)

One format for every team, so `summarize.py` can compute the [Task.md section VIII](Task.md#viii-task-6-experimental-comparison) numbers from everybody's logs without editing anything by hand.

Each device writes **two files per run**: a `summary` (key=value text, written once at the end) and an `events` file (CSV, one line per event, written during the run). Plain text on purpose: it is trivial to write from MicroPython, readable in any editor, and trivial to parse. Markdown tables are fragile to parse and JSON needs a library and RAM on the board, so we use neither.

- [What we measure](#what-we-measure)
- [Folder and file names](#folder-and-file-names)
- [Summary file](#summary-file)
- [Events file](#events-file)
- [Example files](#example-files)
- [MicroPython snippet](#micropython-snippet)
- [Checklist before you upload](#checklist-before-you-upload)

## What we measure

| Metric ([Task.md VIII](Task.md#viii-task-6-experimental-comparison)) | comes from |
| --- | --- |
| PDR, per-source PDR | node `summary`: `generated`; root `events`: unique `rx` rows (origin, seq) |
| Transmission overhead (data, relayed, adverts) | `summary` of **every** device (including the root's `adv_tx`) |
| Startup convergence (DV) | root `events`: `route` rows |
| Failure recovery, reception gap | root `events`: `rx` and `route` rows, `failure_*` keys of the root `summary` |
| Link RSS, hop counts for the topology figure | root `events`: `rssi` of `rx` rows, last `route` row of each node |

Missing one device's `summary` means the overhead for that run is only a lower bound, and PDR for that source falls back to the root's estimate. The script says so, but please upload everything.

## Folder and file names

```
logs/<NN>/root/<mode>/root_summary_<mode>_run<R>.txt
logs/<NN>/root/<mode>/root_events_<mode>_run<R>.csv
logs/<NN>/team-<N>-<SENSOR>/<mode>/node<N>_summary_<mode>_run<R>.txt
logs/<NN>/team-<N>-<SENSOR>/<mode>/node<N>_events_<mode>_run<R>.csv
```

- `<NN>`: the experiment set, two digits (`01`, `02`, ...). One set is one topology with fixed device positions and radio settings. `00` is our unstructured test set and is not used.
- `<mode>`: `dv` or `flood`. `<R>`: the `RUN_ID` of that run. Within one set, a `(mode, run_id)` pair is used once, so do not reuse a run ID.
- `<N>`: team number (= device ID), `<SENSOR>`: `CO`, `GPS`, `DHT11`, `DS18B20` or `MPU6050`. Example folder: `team-7-GPS`.
- Anything else you want to keep (raw console output, your own debug logs) goes next to these as `node<N>_console_<mode>_run<R>.txt`. The script ignores it.

## Summary file

`key=value`, one per line, no spaces around `=`, no quotes. Lines starting with `#` are comments. Keys not listed here are allowed and ignored. All times are in seconds. Write it once, at the end of the drain interval.

Required in every summary (root and node):

| key | value |
| --- | --- |
| `format` | `1` |
| `device` | `root` or `node` |
| `device_id` | 0 for the root, otherwise your ID |
| `sensor` | `CO`, `GPS`, ... (empty for the root) |
| `mode` | `dv` or `flood` |
| `run_id` | the `RUN_ID` |
| `scenario` | `stable` or `failure` ([Task.md VIII](Task.md#viii-task-6-experimental-comparison), scenarios 1 and 2) |
| `warmup_s`, `run_s`, `drain_s` | schedule, `30` / `300` / `30` |
| `adv_interval_s`, `data_interval_s` | `5` / `10` |
| `tx_power_dbm` | what the radio reads back |

Required in a **node** summary (these are exactly our `cnt` counters, no extra work):

| key | meaning |
| --- | --- |
| `generated` | samples generated, including ones dropped for no route, not including acquisition failures |
| `acq_fail` | failed sensor reads (not in the PDR denominator) |
| `drop_noroute` | generated but dropped because there was no route (0 in flooding) |
| `data_tx_own` | own data packets sent |
| `data_tx_relay` | data packets forwarded for others |
| `adv_tx` | advertisements sent (0 in flooding) |
| `final_hop`, `final_parent` | route at the end of the run (DV; `255` for none, empty in flooding) |

Required in the **root** summary:

| key | meaning |
| --- | --- |
| `adv_tx` | root advertisements sent (0 in flooding). It counts in the overhead. |
| `delivered` | unique packets delivered |
| `failure_node`, `failure_at_s` | only for `scenario=failure`: the relay you switch off and when, in seconds on the root clock (t = 0 at root boot). Set them in the config **before** the run. The relay switches itself off, see [Failure scenario](#failure-scenario). |

Any other counter you keep (`drop_dup`, `drop_dest`, `drop_run`, `rx_total`, `adv_rx`, ...) goes in as another `key=value` line, the more the merrier for the report.

## Events file

CSV with a header row and these nine columns, always in this order. Leave a column empty if it does not apply. **No commas inside a field.**

```
t_ms,event,node,seq,via,rssi,hop,parent,info
```

`t_ms` is milliseconds since this device booted (`time.ticks_ms()`). The root's boot is the common start, so switch the nodes on right after the root, as before. Do not compare `t_ms` of two nodes, only the root's `t_ms` is used for cross-device timing ([Task.md VIII](Task.md#viii-task-6-experimental-comparison): no one-way latency from unsynchronized clocks).

| `event` | written by | columns used | meaning |
| --- | --- | --- | --- |
| `rx` | root | `node` = origin, `seq`, `via` = transmitter heard, `rssi` of that transmitter, `info` = `SENSOR;decoded value` | one **unique** packet delivered (after decryption, CRC, validation, de-duplication) |
| `route` | root and nodes | `node`, `hop`, `parent` (the new values), `info` = reason | root: a change in what a node advertises, including the first time it is heard (hop 255 parent 255 is fine). Node: own route change (`node` = own ID). Not used in flooding. |
| `gen` | nodes | `node` = own ID, `seq`, `info` = sensor code | one sample generated (same set as `generated`) |
| `noroute` | nodes | `node`, `seq` | that sample was dropped for no route |
| `acqfail` | nodes | `node` | failed sensor read, no `seq` used |
| `fail` | the relay that is switched off | `node`, `info` = `shutdown` | the relay went silent (failure scenario) |

The root needs only `rx` and `route`; a node needs only `gen`, and `route` / `noroute` in DV. A node that cannot log `route` still works, the script uses the root's view.

## Failure scenario

[Task.md VIII](Task.md#viii-task-6-experimental-comparison), scenario 2: a relay is switched off during the measured run, same surviving sources and same timing in both modes. Do it in software so the timing is repeatable:

- Exactly one relay is switched off per failure run. Agree on which one (`FAILED_NODE`) and when (`FAIL_AT_S`) before the runs, and use the same two values in DV and flooding.
- **Every other board** (root and all other nodes) only sets `SCENARIO = "failure"`, so its summary is labelled correctly. It needs no extra code.
- **The relay's team** adds the shutdown: `FAIL_AT_S` seconds after its own boot the node stops sending, writes its summary (counters up to then) and a `fail` event, and turns ESP-NOW off. Copy `should_fail()` / `shut_down()` from [Team-5-CO/node.py](Team-5-CO/node.py).
- Optional: if you include that code in every node with the same `FAILED_NODE`, only the board whose `DEVICE_ID` matches acts, so the relay can be changed by editing one number without reflashing anyone.
- The root writes `failure_node` and `failure_at_s` into its summary. Nodes boot a few seconds after the root, so the real failure is a few seconds later on the root clock; use the same value in both modes.
- The failed node is not a source in the failure scenario (its PDR is not counted), but its summary still counts in the overhead.

## Example files

Root, DV, failure scenario (`logs/02/root/dv/root_summary_dv_run5.txt`):

```
# iot-log format 1
format=1
device=root
device_id=0
sensor=
mode=dv
run_id=5
scenario=failure
warmup_s=30
run_s=300
drain_s=30
adv_interval_s=5
data_interval_s=10
tx_power_dbm=0.75
failure_node=3
failure_at_s=150
adv_tx=69
delivered=216
adv_rx=522
drop_dest=308
drop_dup=0
drop_run=0
```

Root events (`root_events_dv_run5.csv`):

```
t_ms,event,node,seq,via,rssi,hop,parent,info
3040,route,3,,,,255,255,first_heard
7150,route,5,,,,1,0,first_heard
8210,route,3,,,,2,5,parent_change
32004,rx,5,0,5,-66,,,SMOKE;smoke=0 (not detected)
33410,rx,7,1,3,-81,,,GPS;lon=-122.419400 deg lat=37.774900 deg
```

Node 5 summary (`logs/02/team-5-CO/dv/node5_summary_dv_run5.txt`):

```
# iot-log format 1
format=1
device=node
device_id=5
sensor=CO
mode=dv
run_id=5
scenario=failure
warmup_s=30
run_s=300
drain_s=30
adv_interval_s=5
data_interval_s=10
tx_power_dbm=0.75
generated=29
acq_fail=0
drop_noroute=0
data_tx_own=29
data_tx_relay=110
adv_tx=68
final_hop=1
final_parent=0
```

Node 5 events (`node5_events_dv_run5.csv`):

```
t_ms,event,node,seq,via,rssi,hop,parent,info
6900,route,5,,,,1,0,first_route
30210,gen,5,0,,,,,4
40890,gen,5,1,,,,,4
```

## MicroPython snippet

Drop-in helper, one line per event, file opened and closed each time so a power cut keeps what was written. **Open the events file with `"w"` once at boot** (it writes the header), so a restart does not mix two attempts in one file, and **increase `RUN_ID`** for every attempt.

```python
EVENTS_FILE = "node%d_events_%s_run%d.csv" % (DEVICE_ID, MODE, RUN_ID)
with open(EVENTS_FILE, "w") as f:
    f.write("t_ms,event,node,seq,via,rssi,hop,parent,info\n")

def ev(event, node="", seq="", via="", rssi="", hop="", parent="", info=""):
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write("%d,%s,%s,%s,%s,%s,%s,%s,%s\n"
                    % (time.ticks_ms(), event, node, seq, via, rssi, hop, parent,
                       str(info).replace(",", ";")))
    except OSError:
        pass

# examples
ev("gen", node=DEVICE_ID, seq=seq, info=4)                        # in generate()
ev("route", node=DEVICE_ID, hop=h, parent=p, info="first_route")  # when your parent changes
```

The summary is the same idea: build a `lines` list of `key=value` strings and write it to `node<N>_summary_<mode>_run<R>.txt` at the end of the drain. See `write_run_summary()` in [Team-5-CO/node.py](Team-5-CO/node.py) and `write_summary()` in [root.py](root.py).

## Checklist before you upload

1. Same `MODE`, `RUN_ID`, `scenario`, schedule on all boards, and root powered first.
2. Both files for every run, for **both** modes, at least three runs per mode and scenario.
3. Files named as above, in `logs/<NN>/team-<N>-<SENSOR>/<mode>/`. Do not edit the files.
4. Run `python3 summarize.py <NN>` and look at the warnings at the top of the output. A missing file or a wrong `run_id` shows up there.
