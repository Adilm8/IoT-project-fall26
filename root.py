# root.py - root (ID 0). Set MODE below to "dv" or "flood". Single file; needs keys.py on the board.
import struct
import time
import _thread
import urandom
import network
import espnow
import cryptolib
from binascii import crc32
from keys import keychain

# ---- config ----
# Task.md section II: "Provide configuration parameters for device ID, root/non-root
# role, routing mode (DV or flooding), enabled sensor types, advertisement interval,
# data interval, RSS threshold, and initial TTL". The values are the ones the team
# agreed on in README.md. All times are in milliseconds.
MODE = "dv"              # "dv" or "flood" - must be the same on root and node

CHANNEL = 1
TX_POWER_DBM = 2         # max transmit power. Default is 19.5 dBm; 2 is the lowest the driver accepts
                         # (below 2 raises an error) and it reads back as about 1 dBm (hardware steps)
VERSION = 1
KEY_ID = 1
RUN_ID = 1               # +1 per run, must be identical on all boards

ADV_INTERVAL_MS = 5000   # + 0-10% jitter
DATA_INTERVAL_MS = 10000  # + 0-10% jitter
WARMUP_S = 60            # nodes send no data for this long after boot
RUN_S = 300              # then nodes generate data for this long (measured run)
DRAIN_S = 60             # then the root waits this long for packets still in flight
NEIGHBOR_TIMEOUT_MS = 15000
RSS_THRESHOLD = -85      # dBm
RSS_ALPHA = 0.3          # EMA smoothing of RSSI
RSS_MARGIN = 5           # dB, same-hop parent switch margin
TTL_INIT = 10
DUP_LIFETIME_MS = 60000
DUP_MAX = 200
FLOOD_DELAY_MS = (50, 150)
FWD_QUEUE_MAX = 20

# ---- shared code ----
# ---- constants fixed by Task.md ----
# Section II: every transmission is an ESP-NOW broadcast (BCAST), device ID 255 means
# "everyone", the root is always ID 0. Packet types: 0 = advertisement, 2 = data (section V).
BCAST = b"\xff" * 6
BROADCAST_ID = 255
ROOT_ID = 0
PT_ADV = 0
PT_DATA = 2

# Section V.A outer packet: version | key_id | sender_id | run_id | tx_counter | ciphertext.
# Widths and byte order (big-endian) are the team choice from README.md: 1+1+1+2+4 = 9 bytes.
# CRC_LEN is the 4-byte CRC-32 that is appended to the inner packet before encryption.
# MAX_LEN is the ESP-NOW payload limit the task asks us to stay under.
HDR_FMT = ">BBBHI"          # version | key_id | sender_id | run_id | tx_counter
HDR_LEN = 9
CRC_LEN = 4
MAX_LEN = 250
# Section V data inner header, 7 bytes: ptype | dest_id | origin_id | seq(2) | ttl | sensor_code.
DATA_HDR_FMT = ">BBBHBB"    # ptype | dest | origin | seq | ttl | sensor_code
DATA_HDR_LEN = 7
# Section V sensor codes and the exact payload length each one must have:
# 1 DHT11 (2 x float32), 2 DS18 (float32), 3 GPS (2 x float32), 4 smoke (1 byte), 5 accel (float32).
# Codes 0 and 6-255 are reserved: a packet that uses them is rejected (see check_data).
SENSORS = {1: ("DHT11", 8), 2: ("DS18", 4), 3: ("GPS", 8), 4: ("SMOKE", 1), 5: ("ACCEL", 4)}
# Section V.A: the tx counter must survive reboots so counter blocks are never reused.
CTR_FILE = "ctr.txt"


def ticks():
    return time.ticks_ms()


def elapsed(since):
    return time.ticks_diff(time.ticks_ms(), since)


# Section VI: counters are shared between threads, so every update takes a lock.
# Section VIII needs them to compute PDR and overhead (sent / dropped / delivered).
class Counters:
    def __init__(self):
        self.lock = _thread.allocate_lock()
        self.d = {}

    def bump(self, name):
        with self.lock:
            self.d[name] = self.d.get(name, 0) + 1

    def snapshot(self):
        with self.lock:
            return dict(self.d)


# Section II: broadcast-only ESP-NOW on one channel. The only peer ever registered is
# the broadcast address, no per-neighbor MAC table. Section VI: one thread calls recv(),
# one thread calls send(), so the radio itself needs no lock.
# recv() also looks up the RSSI of the sender in peers_table (section III), which is the
# only place a MAC address is used.
class Radio:
    """Broadcast-only ESP-NOW. Only the rx thread calls recv, only the tx thread calls send."""

    def __init__(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.config(channel=CHANNEL)
        wlan.config(txpower=TX_POWER_DBM)   # lower power shortens range (helps build multi-hop topologies)
        self.wlan = wlan
        self.e = espnow.ESPNow()
        self.e.active(True)
        self.e.add_peer(BCAST)

    def send(self, data):
        self.e.send(BCAST, data)

    def recv(self, timeout_ms):
        """Return (rssi, msg) or (None, None) on timeout."""
        mac, msg = self.e.recv(timeout_ms)
        if msg is None:
            return None, None
        try:
            rssi = self.e.peers_table[mac][0]
        except KeyError:
            rssi = None
        return rssi, bytes(msg)


# Section V.A: mandatory AES-CTR. cryptolib mode 6 is missing on our firmware, so CTR is
# built from AES-ECB: encrypt the counter block, XOR with the data, add 1 to the counter
# (big-endian, from the last byte). Same output as real CTR (checked against NIST SP 800-38A).
def aes_ctr(key, iv, data):
    """AES-128-CTR built on ECB: this firmware's cryptolib has no mode 6.
    Counter block = iv; incremented as a big-endian integer from the last byte."""
    ecb = cryptolib.aes(key, 1)
    out = bytearray(len(data))
    ctr = bytearray(iv)
    for off in range(0, len(data), 16):
        ks = ecb.encrypt(bytes(ctr))
        chunk = data[off:off + 16]
        for i in range(len(chunk)):
            out[off + i] = chunk[i] ^ ks[i]
        j = 15
        while j >= 0:
            ctr[j] = (ctr[j] + 1) & 0xFF
            if ctr[j]:
                break
            j -= 1
    return bytes(out)


# Section V.A: the encryption envelope used for every packet, advertisements included.
# seal() builds an outer packet, open() checks and decrypts one.
class Envelope:
    def __init__(self):
        self.key = keychain[KEY_ID]
        self.lock = _thread.allocate_lock()
        try:
            with open(CTR_FILE) as f:
                self.ctr = int(f.read().strip())
        except (OSError, ValueError):
            self.ctr = 0

    # Section V.A: one tx_counter per encryption (adverts, own data, relayed data). It is
    # written to ctr.txt every time, so a reboot never repeats a counter block.
    def _next_ctr(self):
        with self.lock:
            if self.ctr >= 0xFFFFFFFF:
                raise RuntimeError("tx_counter exhausted")
            self.ctr += 1
            with open(CTR_FILE, "w") as f:
                f.write(str(self.ctr))
            return self.ctr

    # Section V.A counter block (16 bytes): run_id(2) | sender_id(1) | tx_counter(4) | block
    # counter(9). The block counter starts at 0 and is the part aes_ctr increments.
    @staticmethod
    def _iv(run_id, sender, txc):
        # run_id(2) | sender_id(1) | tx_counter(4) | block_counter(9), starts at 0
        return struct.pack(">HBI", run_id, sender, txc) + bytes(9)

    # Section V.A sending side: CRC-32 over (outer header + plaintext inner packet), append it
    # big-endian to the inner packet, then encrypt both together. Header stays in clear.
    def seal(self, sender, inner):
        txc = self._next_ctr()
        hdr = struct.pack(HDR_FMT, VERSION, KEY_ID, sender, RUN_ID, txc)
        crc = struct.pack(">I", crc32(hdr + inner) & 0xFFFFFFFF)
        enc = aes_ctr(self.key, self._iv(RUN_ID, sender, txc), inner + crc)
        return hdr + enc

    # Section V.A receiving side, in the order the task gives: check length, version, key ID and
    # run ID BEFORE decrypting, then decrypt, split off the CRC, recompute it over header +
    # plaintext and compare. Any failure returns a counter name and the caller drops the packet,
    # so nothing touches routing state, the duplicate cache or the delivered log.
    def open(self, msg):
        """Return (sender, inner) or (None, counter_name)."""
        if len(msg) < HDR_LEN + CRC_LEN + 5 or len(msg) > MAX_LEN:
            return None, "drop_len"
        ver, key_id, sender, run_id, txc = struct.unpack(HDR_FMT, msg[:HDR_LEN])
        if ver != VERSION:
            return None, "drop_ver"
        key = keychain.get(key_id)
        if key is None:
            return None, "drop_key"
        if run_id != RUN_ID:
            return None, "drop_run"
        plain = aes_ctr(key, self._iv(run_id, sender, txc), msg[HDR_LEN:])
        inner, got = plain[:-CRC_LEN], plain[-CRC_LEN:]
        if got != struct.pack(">I", crc32(msg[:HDR_LEN] + inner) & 0xFFFFFFFF):
            return None, "drop_crc"
        return sender, inner


# Section V: bounded duplicate cache keyed by (origin_id, seq). Lifetime 60 s (longer than a
# packet can live), at most 200 entries; the oldest entry is evicted when full.
class DupCache:
    def __init__(self):
        self.lock = _thread.allocate_lock()
        self.d = {}

    def seen(self, key):
        """True if key is already cached; otherwise record it and return False."""
        now = ticks()
        with self.lock:
            t = self.d.get(key)
            if t is not None and time.ticks_diff(now, t) < DUP_LIFETIME_MS:
                return True
            if len(self.d) >= DUP_MAX:
                for k in [k for k, v in self.d.items() if time.ticks_diff(now, v) >= DUP_LIFETIME_MS]:
                    del self.d[k]
                if len(self.d) >= DUP_MAX:
                    del self.d[max(self.d, key=lambda k: time.ticks_diff(now, self.d[k]))]
            self.d[key] = now
            return False


def _finite(x):
    return x - x == 0


# Section V validation of the measurement itself: finite floats, humidity 0-100, longitude
# -180..180, latitude -90..90, smoke 0 or 1, acceleration >= 0. Returns text for the log or
# None if the value is not valid (the packet is then discarded and counted).
def decode_payload(code, p):
    """Printable measurement with units, or None if invalid."""
    if code == 1:
        t, h = struct.unpack(">ff", p)
        if _finite(t) and _finite(h) and 0 <= h <= 100:
            return "temp=%.2f C hum=%.1f %%" % (t, h)
    elif code == 2:
        (t,) = struct.unpack(">f", p)
        if _finite(t):
            return "temp=%.2f C" % t
    elif code == 3:
        lon, lat = struct.unpack(">ff", p)
        if _finite(lon) and _finite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            return "lon=%.6f deg lat=%.6f deg" % (lon, lat)
    elif code == 4:
        if p[0] in (0, 1):
            return "smoke=%d (%s)" % (p[0], "CO detected" if p[0] else "not detected")
    elif code == 5:
        (a,) = struct.unpack(">f", p)
        if _finite(a) and a >= 0:
            return "accel=%.3f m/s2" % a
    return None


# Section V: validate a decrypted data packet. Rejects reserved sensor codes (0, 6-255), a
# payload whose length does not match the sensor code, and invalid values.
def check_data(inner):
    """Return ((dest, origin, seq, ttl, code, payload), text) or (None, counter_name)."""
    if len(inner) < DATA_HDR_LEN:
        return None, "drop_inner"
    _, dest, origin, seq, ttl, code = struct.unpack(DATA_HDR_FMT, inner[:DATA_HDR_LEN])
    spec = SENSORS.get(code)
    if spec is None:
        return None, "drop_code"
    payload = inner[DATA_HDR_LEN:]
    if len(payload) != spec[1]:
        return None, "drop_payload"
    text = decode_payload(code, payload)
    if text is None:
        return None, "drop_payload"
    return (dest, origin, seq, ttl, code, payload), text


# Everything the root reports goes through log(): printed on the console and appended to a
# file on the board, one file per run ID. The file is opened and closed per line, so it
# survives a power cut. Only the main thread logs, so no lock is needed.
# File formats for all teams: LOGGING.md. The console log is free text for humans; the events
# CSV and the summary are what summarize.py reads. Boot truncates the console log and the
# events file, so a restart never mixes two attempts (raise RUN_ID for every attempt).
LOG_FILE = "root_console_%s_run%d.txt" % (MODE, RUN_ID)       # the mode is in the name, so dv and
EVENTS_FILE = "root_events_%s_run%d.csv" % (MODE, RUN_ID)     # flood runs never share a file
SUMMARY_FILE = "root_summary_%s_run%d.txt" % (MODE, RUN_ID)
EVENT_COLS = "t_ms,event,node,seq,via,rssi,hop,parent,info"

for _name, _head in ((LOG_FILE, ""), (EVENTS_FILE, EVENT_COLS + "\n")):
    with open(_name, "w") as _f:
        _f.write(_head)


# One CSV line per event (LOGGING.md, events file). Fields must not contain commas.
def ev(event, node="", seq="", via="", rssi="", hop="", parent="", info=""):
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write("%d,%s,%s,%s,%s,%s,%s,%s,%s\n"
                    % (ticks(), event, node, seq, via, rssi, hop, parent, str(info).replace(",", ";")))
    except OSError:
        pass


def log(line):
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# Section VIII metrics, all measured from what the root itself receives.
# PDR: each non-root device numbers its samples 0, 1, 2, ... from boot (seq +1 per sample,
# including samples dropped for "no route"), so highest seq seen + 1 is the number it
# generated, as far as the root can tell. Samples lost at the very end are not visible.
seq_max = {}   # origin -> highest sequence number delivered

# Startup convergence (DV): per node [first_heard_ms, route_ms, last_change_ms, hop, parent].
# route_ms is when the node first had a route (an advert with hop < 255, or its first
# delivered data if its adverts are out of the root's range). last_change_ms is the last
# time its (hop, parent) changed. The common start is the root boot (t = 0).
route_state = {}
conv_reported = False


def note_advert(nid, hop, parent):
    t = ticks()
    st = route_state.get(nid)
    if st is None:
        route_state[nid] = [t, t if hop < 255 else None, t, hop, parent]
        ev("route", node=nid, hop=hop, parent=parent, info="first_heard")
        log("[%4ds] ROUTE      node %d first heard: hop %d parent %d" % (t // 1000, nid, hop, parent))
    elif st[3] is None:   # seen so far only through delivered data, now its adverts are heard
        st[3], st[4] = hop, parent
        ev("route", node=nid, hop=hop, parent=parent, info="advert_heard")
        log("[%4ds] ROUTE      node %d advert heard: hop %d parent %d" % (t // 1000, nid, hop, parent))
    elif (hop, parent) != (st[3], st[4]):
        ev("route", node=nid, hop=hop, parent=parent, info="route_change")
        log("[%4ds] ROUTE      node %d hop %d->%d parent %d->%d"
            % (t // 1000, nid, st[3], hop, st[4], parent))
        st[3], st[4], st[2] = hop, parent, t
        if st[1] is None and hop < 255:
            st[1] = t


def note_delivery(origin):
    t = ticks()
    st = route_state.get(origin)
    if st is None:
        route_state[origin] = [t, t, t, None, None]
    elif st[1] is None:
        st[1], st[2] = t, t


# Last RSSI heard from each transmitting neighbor (dBm). Only the main (receive) thread
# reads and writes it, so it needs no lock. It is the RSSI of the LAST HOP (the outer
# sender_id), which is the origin only when the packet came straight from the origin.
link_rssi = {}


# Section V "At the root": the root only accepts data addressed to it (DV: dest = 0, flooding:
# dest = 255), ignores overheard DV data for other devices, drops duplicates, never forwards,
# and logs each unique packet once with origin, sequence, sensor and decoded value.
# Section V.A: nothing reaches the log unless decryption, CRC and validation all passed.
def root_process(msg, mode, env, cnt, dup, rssi=None):
    """Root receive path. Prints one line per unique delivered packet."""
    cnt.bump("rx_total")
    sender, inner = env.open(msg)
    if sender is None:
        cnt.bump(inner)
        return
    if rssi is not None:
        link_rssi[sender] = rssi   # section III: RSSI is tied to the (checked) sender ID
    if inner[0] == PT_ADV:
        if len(inner) != 5 or inner[2] != sender:
            cnt.bump("drop_inner")
        else:
            cnt.bump("adv_rx")
            note_advert(sender, inner[3], inner[4])
        return
    if inner[0] != PT_DATA:
        cnt.bump("drop_inner")
        return
    f, text = check_data(inner)
    if f is None:
        cnt.bump(text)
        return
    dest, origin, seq, ttl, code, payload = f
    if dest != (ROOT_ID if mode == "dv" else BROADCAST_ID):
        cnt.bump("drop_dest")      # overheard DV data for another device
        return
    if dup.seen((origin, seq)):    # ttl 0 is fine at the root
        cnt.bump("drop_dup")
        return
    cnt.bump("delivered")
    cnt.bump("node%d" % origin)    # per-source count, for per-source PDR (section VIII)
    if seq > seq_max.get(origin, -1):
        seq_max[origin] = seq
    note_delivery(origin)
    ev("rx", node=origin, seq=seq, via=sender, rssi="" if rssi is None else rssi,
       info="%s;%s" % (SENSORS[code][0], text))
    log("[%4ds] DELIVERED  node %-3d seq %-5d %-6s(code %d)  %s  [via node %d, RSSI %s]"
          % (ticks() // 1000, origin, seq, SENSORS[code][0], code, text, sender,
             "%d dBm" % rssi if rssi is not None else "n/a"))

# Section VIII: periodic summary, easier to read than a raw dict. Shows how many unique
# packets arrived per node, advertisements heard/sent, and every drop reason that is non-zero.
def print_stats(cnt, out=None):
    global conv_reported
    out = out or log
    now_s = ticks() // 1000
    c = cnt.snapshot()
    nodes = sorted((int(k[4:]), v) for k, v in c.items() if k.startswith("node"))
    drops = ", ".join("%s=%d" % (k[5:], v) for k, v in sorted(c.items()) if k.startswith("drop_"))
    out("[%4ds] STATS      delivered=%d (%s) | adverts heard=%d sent=%d | dropped: %s"
        % (now_s, c.get("delivered", 0),
           ", ".join("node %d: %d" % n for n in nodes) or "none yet",
           c.get("adv_rx", 0), c.get("adv_tx", 0), drops or "none"))
    out("[%4ds] LINKS      last RSSI heard from: %s"
        % (now_s,
           ", ".join("node %d: %d dBm" % kv for kv in sorted(link_rssi.items())) or "nobody yet"))
    # PDR = unique delivered / generated, overall and per source (section VIII).
    got = exp = 0
    parts = []
    for origin, n in nodes:
        e = seq_max.get(origin, -1) + 1
        got += n
        exp += e
        parts.append("node %d: %d/%d = %.1f%%" % (origin, n, e, 100.0 * n / e if e else 0.0))
    if exp:
        out("[%4ds] PDR        overall %d/%d = %.1f%% | %s"
            % (now_s, got, exp, 100.0 * got / exp, ", ".join(parts)))
    else:
        out("[%4ds] PDR        no data delivered yet" % now_s)
    if MODE != "dv":
        return
    # Startup convergence (section VIII): every known node has a route and none of them
    # changed (hop, parent) for 3 advertisement intervals.
    if not route_state:
        out("[%4ds] CONVERGE   no node heard yet" % now_s)
        return
    waiting = sorted(n for n, s in route_state.items() if s[1] is None)
    if waiting:
        out("[%4ds] CONVERGE   waiting for a route from node %s"
            % (now_s, ", ".join(str(n) for n in waiting)))
        return
    last_change = max(s[2] for s in route_state.values())
    if elapsed(last_change) >= 3 * ADV_INTERVAL_MS:
        out("[%4ds] CONVERGE   converged: %d node(s) have a route, last change at %d s%s"
            % (now_s, len(route_state), last_change // 1000,
               "" if conv_reported else "  <== STARTUP CONVERGENCE TIME"))
        conv_reported = True
    else:
        out("[%4ds] CONVERGE   all routes up, last change %d s ago, waiting for %d s of stability"
            % (now_s, elapsed(last_change) // 1000, 3 * ADV_INTERVAL_MS // 1000))


# Section VIII: final summary of the run, written once to its own file (and logged).
# SUMMARY_FILE is the key=value file from LOGGING.md that summarize.py reads. The console log
# gets the same STATS / LINKS / PDR / CONVERGE lines as the periodic output, and finally each
# node's last route and when it first had one.
def write_summary(cnt):
    c = cnt.snapshot()
    lines = ["# iot-log format 1", "format=1", "device=root", "device_id=%d" % ROOT_ID, "sensor=",
             "mode=" + MODE, "run_id=%d" % RUN_ID,
             "warmup_s=%d" % WARMUP_S, "run_s=%d" % RUN_S, "drain_s=%d" % DRAIN_S,
             "adv_interval_s=%d" % (ADV_INTERVAL_MS // 1000),
             "data_interval_s=%d" % (DATA_INTERVAL_MS // 1000),
             "tx_power_dbm=%s" % radio.wlan.config("txpower")]
    lines += ["%s=%s" % kv for kv in sorted(c.items()) if not kv[0].startswith("node")]
    for k in ("adv_tx", "adv_rx", "delivered"):
        if k not in c:
            lines.append(k + "=0")
    try:
        with open(SUMMARY_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        log("could not write " + SUMMARY_FILE)
    log("SUMMARY run_id=%d mode=%s tx_power=%s dBm"
        % (RUN_ID, MODE, radio.wlan.config("txpower")))
    log("schedule: warm-up %d s, measured run %d s, drain %d s (from root boot, t = 0)"
        % (WARMUP_S, RUN_S, DRAIN_S))
    print_stats(cnt)
    for nid in sorted(route_state):
        s = route_state[nid]
        log("node %d: first heard %d s, first route %s, last route change %d s, hop %s parent %s"
            % (nid, s[0] // 1000, "%d s" % (s[1] // 1000) if s[1] is not None else "never",
               s[2] // 1000, s[3], s[4]))
    log("PDR note: generated = highest seq seen + 1 per node (packets lost at the very end "
        "are invisible), compare with each node's own 'generated' count.")
    log("[%4ds] SUMMARY    written to %s" % (ticks() // 1000, SUMMARY_FILE))


# ---- program ----
# Section IV/VI: the main thread receives and processes; one worker thread sends.
# The root never selects a parent and never forwards data.
ROOT_HOP = 0
NO_PARENT = 0   # root advertises parent 0 (team agreement)

radio = Radio()
env = Envelope()
cnt = Counters()
dup = DupCache()


# Section III: the root also advertises, every ADV_INTERVAL_MS plus 0-10 % jitter (section II).
# It always says hop 0 and, by team agreement, parent 0 (the task text says 255, see README).
# Only this thread sends, so no transmit lock is needed (section VI).
def adv_worker():
    while True:
        inner = struct.pack(">BBBBB", PT_ADV, BROADCAST_ID, ROOT_ID, ROOT_HOP, NO_PARENT)
        radio.send(env.seal(ROOT_ID, inner))
        cnt.bump("adv_tx")
        time.sleep_ms(ADV_INTERVAL_MS + urandom.getrandbits(16) % (ADV_INTERVAL_MS // 10 + 1))


# Section VII: in flooding mode no routing advertisements are needed, so no worker thread.
if MODE == "dv":
    _thread.start_new_thread(adv_worker, ())

log("root started: mode=%s run_id=%d (all boards must use the same) tx_power=%s dBm, logging to %s, %s"
    % (MODE, RUN_ID, radio.wlan.config("txpower"), LOG_FILE, EVENTS_FILE))
# Section VI main/receive thread: the only consumer of ESP-NOW packets. recv() waits up to
# 500 ms, so the loop never spins. Every packet goes through root_process (decrypt, check,
# validate, de-duplicate, log).
last = start = ticks()
phase = 0   # 0 warm-up, 1 measured run, 2 drain, 3 summary written
while True:
    rssi, msg = radio.recv(500)
    if msg:
        root_process(msg, MODE, env, cnt, dup, rssi)
    if elapsed(last) >= 10000:
        last = ticks()
        print_stats(cnt)
    # Run schedule, counted from the root boot (the common start): warm-up, measured run,
    # drain, then the summary file. The log keeps going afterwards.
    e = elapsed(start) // 1000
    if phase == 0 and e >= WARMUP_S:
        phase = 1
        log("[%4ds] PHASE      warm-up over, measured run starts (%d s)" % (e, RUN_S))
    if phase == 1 and e >= WARMUP_S + RUN_S:
        phase = 2
        log("[%4ds] PHASE      nodes stop generating, draining for %d s" % (e, DRAIN_S))
    if phase == 2 and e >= WARMUP_S + RUN_S + DRAIN_S:
        phase = 3
        write_summary(cnt)
