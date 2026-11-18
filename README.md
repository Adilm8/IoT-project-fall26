# IoT-project-fall26

## Overview

This is a group project aimed at creating an IoT network using routing and flooding and comparing them. The assignment is in [Task.md](Task.md) (also as [Task.pdf](Task.pdf)); the packet formats we use are in [PACKETS.md](PACKETS.md) and the log format every team uses is in [LOGGING.md](LOGGING.md).

- [Hardware and software](#hardware-and-software)
- [Team agreements](#team-agreements)
- [Sensors and teams](#sensors-and-teams)
- [Code](#code)

## Hardware and software

We all have ESP-WROOM-32 (Wi-Fi, Bluetooth). We use Thonny and MicroPython for the development.

## Team agreements

[Task.md](Task.md) leaves some items open-ended. Here is what we somewhat agreed on. The packet layouts that follow from these choices are in [PACKETS.md](PACKETS.md).

### AES key

AES-128, 16 bytes, CTR mode. The PSK is pre-shared, so we pre-share it: the keychain dictionary `key_id => key` lives in a separate `keys.py` (see [shared PSK and keychain](#shared-psk-and-keychain)). Task.md asks for this in [section V.A](Task.md#va-mandatory-aes-ctr-encryption-and-integrity-checks).

### Integrity check

CRC-32, 4 bytes (`from binascii import crc32`), computed over outer header + plaintext inner packet, appended big-endian to the inner packet, and then both are encrypted together. See [Task.md, integrity value](Task.md#integrity-value) and [PACKETS.md, encryption and integrity](PACKETS.md#encryption-and-integrity).

### Outer header field widths

All big-endian, 9 bytes in total:

`version(1) | key_id(1) | sender_id(1) | run_id(2) | tx_counter(4) | ciphertext`

4 bytes for the run ID seems too much: 65536 run IDs from 2 bytes is more than enough. Layout details: [PACKETS.md, outer header](PACKETS.md#outer-header).

### Counter block layout

16 bytes:

`run_id(2) | sender_id(1) | tx_counter(4) | block_counter(9)`

The block counter starts at 0 and goes up by 1 for every 16-byte block, big-endian, incremented from the last byte. This is how MicroPython's `cryptolib` CTR mode 6 does it, so the block counter goes at the end, not in the middle. The maximum packet is 250 bytes (the ESP-NOW maximum), which is 16 blocks, so only the last byte ever changes.

Heads up: on our firmware (MicroPython v1.27.0, generic ESP32) `cryptolib.aes(key, 6, iv)` raises `ValueError: mode`, so mode 6 does not exist there. Only ECB (1) and CBC (2) work. The code builds CTR on top of ECB with the same counter block layout and the same increment rule, so the packets are identical to what mode 6 would give. It reproduces the NIST SP 800-38A AES-128 CTR test vector on the board. The code is in [PACKETS.md, encryption and integrity](PACKETS.md#encryption-and-integrity).

### Shared PSK and keychain

We use a keychain, so we can later switch the key in use without changing anything else (this is how most routing protocols do it in practice). The keys are pregenerated randomly and shared here:

```python
keychain = {
    1: bytes.fromhex("86d365dd9a3afe64003b2a4e9b141a10"),
    2: bytes.fromhex("e596ad6a68df0a37d10eaa885cf230ff"),
    3: bytes.fromhex("496655eb7d9e86073163200a4bae2c1f"),
    4: bytes.fromhex("5f02074c35682a4a753b3c03c9dcb8b2")
}
```

`key_id` = 1 is the one in use.

### Run ID

`run_id` is hardcoded. It counts our attempts: each attempt we add 1 manually. It must be the same on all boards, so someone announces it before every run (if your `run_id` differs, all your packets get dropped). Don't delete `ctr.txt` on your board: it keeps `tx_counter` between reboots so counter blocks never repeat ([Task.md, run identifier and transmission counter](Task.md#run-identifier-and-transmission-counter)).

### Intervals and thresholds

Task.md suggests starting values in [section II](Task.md#ii-equipment-and-configuration); ours:

- Advertisement: 5 s + 0–10% jitter (root too). The instructor mentioned 10 s for the root, but we use 5 s for everyone.
- Data: 10 s + 0–10% jitter.
- Run schedule (DV): after boot a node sends no data of its own for 60 s (`WARMUP_MS`), then generates data for exactly 5 minutes (`RUN_MS`), then stops. Advertisements and relaying carry on the whole time, so DV can form routes and in-flight packets are forwarded. The root waits 60 s more (`DRAIN_S`) and then writes the summary. Total 60 + 300 + 60 = 420 s counted from the root boot. The longer warm-up gives DV time to form routes before the measured run (in the test set, routes took 40 to 51 s to settle).
- Neighbor timeout: 15 s, checked every 1 s.
- RSS threshold: −85 dBm, EMA with $\alpha = 0.3$ (see [Task.md section III](Task.md#iii-task-1-neighbor-discovery)).
- Parent switch margin: 5 dB (same hop only, see [section IV](Task.md#iv-task-2-parent-selection)).
- TTL: 10, decremented before sending, so own packets go out with 9.
- Duplicate cache: `(origin_id, seq)`, 60 s / 200 entries. The cache size is up to the team; the lifetime of an entry must be long enough to outlive the oldest packet, so 60 s seems fine.
- Flooding relay delay: random 50–150 ms. This is also up to the team ([Task.md section VII](Task.md#vii-task-5-flooding-baseline)).

### Other settings

- Same Wi-Fi channel for everyone: channel 1 for now.
- Version = 1. Root is ID 0, teams use IDs 1–254.
- Every node advertises even with no route (hop 255, parent 255). The root has hop 0. Task.md says the root's parent is 255, but we agreed the root advertises parent 0, and the code does that.
- Everyone uses the same mode when testing (DV or flood).
- No extra smoothing of the RSSI estimate beyond the EMA above.
- We measure only PDR, PDR per device and startup convergence time (DV), see [Task.md section VIII](Task.md#viii-task-6-experimental-comparison).
- One lock (mutex) for the neighbor table handled by ESP-NOW. We use 1 rx thread and 1 tx thread, so no lock is needed for the radio: only rx calls `recv` and only tx calls `send`. Even though the radio is half-duplex, ESP-NOW handles it, so the board just doesn't hear anything while it sends, so tx has priority. See [Task.md section VI](Task.md#vi-task-4-threaded-operation).
- Everybody has to tell the instructor their payload length. The lengths are in [PACKETS.md, sensor codes and payloads](PACKETS.md#sensor-codes-and-payloads).

## Sensors and teams

The sensors we have are:

- MPU-6050 (3x)
- GPS (2x)
- DS18B20 (2x)
- CO (2x)
- DHT11 (2x)

The team number is also the device ID. Sensor codes and payloads for each type are in [PACKETS.md](PACKETS.md#sensor-codes-and-payloads).

### Teams

| No  | Team member 1       | Team member 2         | Team member 3       | Team member 4        | Sensor   |
| --- | ------------------- | --------------------- | ------------------- | -------------------- | -------- |
| 1   | Amina Aidyn         | Aisana Abdrayeva      | Diana Sovetova      |                      | MPU-6050 |
| 2   | Nurkhan Berikboluly | Zhandaulet Kuan       | Bibol Assetbek      | Yernur Kenzhaly      | GPS      |
| 3   | Kamila Nurzhanova   | Siti Nur Dania        | Marjona Meliboyeva  |                      | DS18B20  |
| 4   | Amir Sakhipkereyev  | Anuar Akimbekov       | Miras Nametov       |                      | MPU-6050 |
| 5   | Bakhtiyar Yesbolsyn | Ruslan Nagimov        | Aitzhan Kadyrov     | Gulnur Meirimkhanova | CO       |
| 6   | Turar Turakbay      | Arlan Nauryzgali      | Kamila Tokubayeva   | Islam Mukhambetkali  | DHT11    |
| 7   | Adil Molzhigitov    | Yerassyl Gaziz        | Yeradil Tleugazyyev | Alen Kazhymukan      | GPS      |
| 8   | Sultan Yershuak     | Bekzat Torekhan       | Miras Tuleubayev    |                      | MPU-6050 |
| 9   | Dauren Nabi         | Ayan Saparali         |                     |                      | DS18B20  |
| 12  | Adil Tatiyev        | Alua Dosbergenova     |                     |                      | CO       |
| 13  | Tagir Zamaletdinov  | Botakoz Toleugaliyeva | Korkemay Oserbay    |                      | DHT11    |

## Code

Two programs, one per board, each a single file with a `MODE` constant at the top ("dv" or "flood", see [Task.md section VII](Task.md#vii-task-5-flooding-baseline)):

- `root.py`: the root, ID 0. In `"dv"` mode it advertises hop 0 with parent 0 and logs every unique data packet it receives. In `"flood"` mode it only receives.
- `Team-5-CO/node.py`: a non-root device with the CO sensor. It advertises, picks a parent, forwards for others and sends its own samples. `DEVICE_ID` and `MODE` are set at the top (our team ID is 5).
- `keys.py`: the keychain from [above](#shared-psk-and-keychain), copied to every board next to the program.
- `summarize.py`: runs on the computer, not on a board. Reads the logs of one experiment set and computes the [Task.md section VIII](Task.md#viii-task-6-experimental-comparison) numbers, see [Summarizing a set of logs](#summarizing-a-set-of-logs).

Transmit power is set by `TX_POWER_DBM` at the top of both programs (currently 2 dBm; the ESP32 default is 19.5 dBm). 2 dBm is the lowest value the driver accepts, and the radio rounds to hardware steps, so on our boards it reads back as about 1 dBm. Each program prints the value it read back when it starts.

Both programs have comments that point to the Task.md section each part implements. `MODE` and `RUN_ID` must be identical on all boards. Both use the rx thread for receiving and one worker thread for sending, so the radio never has two callers ([Task.md section VI](Task.md#vi-task-4-threaded-operation)).

### Reading the root output

```
[  83s] DELIVERED  node 5   seq 12    SMOKE (code 4)  smoke=0 (not detected)  [via node 5, RSSI -42 dBm]
[  90s] STATS      delivered=9 (node 5: 9) | adverts heard=18 sent=18 | dropped: none
[  90s] LINKS      last RSSI heard from: node 5: -42 dBm
```

`DELIVERED` appears once per unique packet that passed decryption, the CRC check and validation ([Task.md, reception](Task.md#reception)). It shows the origin node, its sequence number, the sensor and the decoded reading with units, as the task asks for the root log ([required delivery behavior](Task.md#required-delivery-behavior)). The first number in brackets is seconds since the root started. The last bracket on a `DELIVERED` line is the transmitter the root heard and its RSSI. That is the last hop: it is the origin only when the packet arrived directly, otherwise it is the relay. `LINKS` lists the most recent RSSI per neighbor the root hears. `STATS` is printed every 10 s: unique packets per node, advertisements received and sent, and every drop reason that is not zero (`crc`, `dup`, `dest`, `code`, `payload`, `run`, ...).

### Log file and metrics

All teams use the same files, described in [LOGGING.md](LOGGING.md): per device and run a `summary` (key=value, written once at the end) and an `events` CSV (one line per delivered packet, route change or generated sample). The root writes:

- `root_summary_<MODE>_run<RUN_ID>.txt`: schedule and all root counters.
- `root_events_<MODE>_run<RUN_ID>.csv`: an `rx` line per unique delivered packet and a `route` line per route change it hears advertised.
- `root_console_<MODE>_run<RUN_ID>.txt`: everything the root prints (the `DELIVERED`, `STATS`, ... lines below), for humans only.

Boot truncates the events and console files, so a restart cannot mix two attempts in one file: change `RUN_ID` for every attempt. Copy the files off with Thonny's file browser (View, Files) before you delete or reflash.

Run schedule, counted from the root boot: 0 to 60 s warm-up, 60 to 360 s measured run, 360 to 420 s drain, then the root writes the summary and logs `SUMMARY written`. The log marks each step with a `PHASE` line. Nodes must be powered on within a few seconds after the root: each node starts its own 60 s + 5 min clock at its boot, so a node that starts later also stops later and has less drain time. Each node does the same with `node<ID>_summary_<MODE>_run<RUN_ID>.txt` and `node<ID>_events_<MODE>_run<RUN_ID>.csv` (`generated`, `acq_fail`, no-route drops, own and relayed data sends, adverts sent, final route).


Every 10 s the root also logs the [Task.md section VIII](Task.md#viii-task-6-experimental-comparison) numbers:

```
[ 120s] PDR        overall 18/20 = 90.0% | node 5: 9/10 = 90.0%, node 6: 9/10 = 90.0%
[ 120s] CONVERGE   converged: 2 node(s) have a route, last change at 14 s  <== STARTUP CONVERGENCE TIME
```

- **PDR** is unique packets delivered divided by packets generated. The root cannot see a packet that never arrived, so it takes the generated count to be the highest sequence number seen plus 1. That works because a node numbers its samples from 0 at boot and every sample, including one dropped for "no route", uses a number. Packets lost at the very end are not visible, so check the final count against the node's own `generated` counter. Reset (reboot) the nodes at the start of each run so that numbering starts from 0.
- **Per-source PDR** is the same ratio for each origin, listed after the overall figure.
- **Startup convergence time** (DV) is measured from the root's boot (t = 0, the documented common start, so power the nodes on right after the root). It is the time of the last route change, reported once every node the root knows has a route and none has changed hop or parent for 3 advertisement intervals (15 s). The root learns routes from the advertisements it hears, plus a node's first delivered packet if its adverts are out of range, so a node that is never heard is not counted. `ROUTE` lines in the log show each change (`hop 255->1 parent 255->0`).
- Transmission overhead needs the send counters of every node, so it comes from the node summaries, not the root. Use `generated` from the node summary as the exact PDR denominator instead of the root's estimate (`summarize.py` does).

### Summarizing a set of logs

Logs go in `logs/<NN>/` (two-digit experiment set, `00` is our unstructured test set and is not used), one folder per device and mode as in [LOGGING.md](LOGGING.md#folder-and-file-names):

```
logs/02/root/dv/root_summary_dv_run2.txt, root_events_dv_run2.csv
logs/02/team-5-CO/dv/node5_summary_dv_run2.txt, node5_events_dv_run2.csv
```

```
python3 summarize.py 02
```

It needs only Python 3 (plots need `matplotlib`, and are skipped without it). It prints a Markdown report and saves it as `logs/02/results/summary.md` together with `runs.csv` and `per_source.csv` (the underlying results table) and, if matplotlib is installed, `plot_per_source_pdr.png` and `plot_overhead.png`. The report has warnings first (missing node summaries, wrong run IDs, fewer than three runs), then per-run results, mean ± sd per mode, per-source PDR, DV convergence, topology (last route and RSSI per node) and a short answer per metric. `--expect 1,3,4,...` warns when a source is silent in a run. `--assume-full 5` treats a listed source whose node summary is missing as having generated exactly what the root received (PDR 100%), and says so in the warnings.

How the numbers are computed:

- **PDR**: unique `(origin, seq)` at the root with `seq < generated`, divided by `generated` from the source's node summary (the root's highest seq + 1 is the fallback, flagged).
- **Overhead**: (own + relayed data + adverts over all node summaries, plus root adverts) divided by unique packets delivered.
- **Startup convergence (DV)**: from the root's `route` lines, the earliest time at which every connected device has a valid route and no device changes route for 3 advertisement intervals (15 s). This is the same rule as the root's `CONVERGE` line, evaluated on the log. The report also gives the number of route changes after the warm-up, which shows flapping.

The result for the test set is written by hand in [logs/00/SUMMARY.md](logs/00/SUMMARY.md).

### Putting it on a board

1. Stop whatever is running (Ctrl-C in Thonny). If the board has an old lab `main.py` that connects to Wi-Fi, rename it, otherwise it blocks the REPL and fights ESP-NOW for the radio.
2. Save `keys.py` on the board.
3. Save `root.py` or `node.py` on the board as `main.py`.
4. Press RST. The program starts by itself on every reset or power-up.

Don't delete `ctr.txt`, it keeps the tx counter across reboots ([run ID](#run-id)).

### CO sensor (FC-22, MQ-9)

Sensor code 4 ([PACKETS.md, sensor codes](PACKETS.md#sensor-codes-and-payloads)). The module has four pins: VCC to VIN (5 V), GND to GND, DO to GPIO 14. AO is not used, so leave it unconnected. The heater smells a bit and gets hot for the first few minutes, that is normal.

DO is pulled up to the module supply, so on 5 V it can be above the 3.3 V the ESP32 pin is rated for. Measure it with no gas present, and if it reads about 5 V put a divider in (10k from DO to the pin, 20k from the pin to GND).

DO goes low when CO is above the level set by the potentiometer. Low is reported as `smoke=1`, high as `smoke=0`. This is our digital-output interpretation, which [Task.md section II](Task.md#ii-equipment-and-configuration) asks us to document.

### Tested so far

Test set `00` ([logs/00/SUMMARY.md](logs/00/SUMMARY.md)): 1 root and 9 sources, DV runs 2 to 4 and flooding runs 1 to 3. Flooding delivered about 98%, DV 71 to 85%; two-hop and longer paths, parent switching and neighbor expiry were exercised (and parents kept flapping). The other four sensor types are sent by the other teams' nodes and decode at the root. The new log files ([LOGGING.md](LOGGING.md)) and `summarize.py` are not yet exercised with real boards: they were checked on generated logs only.
