#!/usr/bin/env python3
"""
pen_logger.py — NeoSmartpen BLE dot logger
Compatible with: Moleskine Smart Pen NWP-F130 and all NeoSmartpen devices.

Protocol reverse-engineered from NeoSmartpen/WEB-SDK2.0 (TypeScript source).

Packet framing
--------------
  [STX=0xC0] [CMD] [RESULT?] [LEN_LE:2] [PAYLOAD] [ETX=0xC1]

- All multi-byte fields: little-endian.
- If CMD high-nibble == 0x6 (online events) → no RESULT byte.
- Payload bytes equal to STX/ETX/DLE are escaped as [DLE, byte XOR 0x20].

Handshake sequence
------------------
  Connect → VERSION_REQUEST → VERSION_RESPONSE
          → SETTING_INFO_REQUEST → SETTING_INFO_RESPONSE
             [if locked] → PASSWORD_REQUEST → PASSWORD_RESPONSE
          → ONLINE_DATA_REQUEST → ONLINE_DATA_RESPONSE
          → (dot events stream in)

Usage
-----
  pip install bleak
  python pen_logger.py [--password XXXX]

Output
------
  pen_log_YYYYMMDD_HHMMSS.csv — one row per dot
  Columns: timestamp, x, y, pressure, dot_type, tilt_x, tilt_y,
           section, owner, note, page
"""

import asyncio
import csv
import signal
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak is required:  pip install bleak")


# ── GATT UUIDs (from src/PenCotroller/PenHelper.ts) ──────────────────────────
SVC_128  = "4f99f138-9d53-5bfa-9e50-b147491afe68"
NOTI_128 = "64cd86b1-2256-5aeb-9f04-2caf6c60ae57"
WRIT_128 = "8bc8cc7d-88ca-56b0-af9a-9bf514d0d61a"
SVC_16   = 0x19F1
NOTI_16  = 0x2BA1
WRIT_16  = 0x2BA0

def _uuid16(n: int) -> str:
    return f"0000{n:04x}-0000-1000-8000-00805f9b34fb"


# ── Protocol constants (from Const.ts and CMD.ts) ─────────────────────────────
STX = 0xC0
ETX = 0xC1
DLE = 0x7D

# Commands
CMD_VER_REQ  = 0x01;  CMD_VER_RSP  = 0x81
CMD_PASS_REQ = 0x02;  CMD_PASS_RSP = 0x82
CMD_SET_REQ  = 0x04;  CMD_SET_RSP  = 0x84
CMD_ONL_REQ  = 0x11;  CMD_ONL_RSP  = 0x91

# Online events (high nibble 0x6 = no RESULT byte in response)
CMD_UPDOWN_OLD = 0x63  # old firmware: combined pen-down / pen-up
CMD_PAPER_OLD  = 0x64  # old firmware: paper info
CMD_DOT_OLD    = 0x65  # old firmware: dot
CMD_NEW_DOWN   = 0x69  # new firmware: pen-down
CMD_NEW_UP     = 0x6A  # new firmware: pen-up
CMD_NEW_PAPER  = 0x6B  # new firmware: paper info
CMD_NEW_DOT    = 0x6C  # new firmware: dot
CMD_HOVER      = 0x6F  # hover dot

# Dot types (from Dot.ts)
DOT_DOWN  = 0
DOT_MOVE  = 1
DOT_UP    = 2
DOT_HOVER = 3
LABEL = {DOT_DOWN: "PEN_DOWN", DOT_MOVE: "PEN_MOVE",
         DOT_UP:   "PEN_UP",   DOT_HOVER: "PEN_HOVER"}
PEN_FIELDNAMES = [
    "local_ts", "local_ts_ms",
    "timestamp", "x", "y", "pressure", "dot_type",
    "tilt_x", "tilt_y", "section", "owner", "note", "page",
]


# ── Packet builder ────────────────────────────────────────────────────────────

def _esc_byte(b: int) -> bytes:
    return bytes([DLE, b ^ 0x20]) if b in (STX, ETX, DLE) else bytes([b])

def _escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        out.extend(_esc_byte(b))
    return bytes(out)

def _pkt(cmd: int, payload: bytes = b"") -> bytes:
    """Frame: STX escape(CMD LEN_LE PAYLOAD) ETX  (STX/ETX themselves not escaped)."""
    hdr = bytes([cmd]) + struct.pack("<H", len(payload))
    return bytes([STX]) + _escape(hdr) + _escape(payload) + bytes([ETX])

def pkt_version() -> bytes:
    """
    VERSION_REQUEST (0x01)  —  first packet, sent 500 ms after connection.
    Payload (42 bytes): 16×0x00  [0xF0 0x01]  appVer[16]  protoVer[8]
    """
    app   = b"0.0.0.0" + b"\x00" * 9   # 16 bytes
    proto = b"2.18"    + b"\x00" * 4   # 8 bytes
    payload = b"\x00" * 16 + bytes([0xF0, 0x01]) + app + proto
    assert len(payload) == 42
    return _pkt(CMD_VER_REQ, payload)

def pkt_setting() -> bytes:
    """SETTING_INFO_REQUEST (0x04) — no payload."""
    return _pkt(CMD_SET_REQ)

def pkt_online() -> bytes:
    """
    ONLINE_DATA_REQUEST (0x11) — enable real-time streaming.
    Payload [0xFF 0xFF] means "accept all note IDs".
    """
    return _pkt(CMD_ONL_REQ, bytes([0xFF, 0xFF]))

def pkt_password(pw: str) -> bytes:
    """PASSWORD_REQUEST (0x02) — 16-byte UTF-8 password (zero-padded)."""
    encoded = pw.encode("utf-8")[:16]
    return _pkt(CMD_PASS_REQ, encoded + b"\x00" * (16 - len(encoded)))


# ── Little-endian reader ──────────────────────────────────────────────────────

class _R:
    __slots__ = ("_d", "_p")

    def __init__(self, data: bytes):
        self._d = data
        self._p = 0

    def u8(self) -> int:
        v = self._d[self._p]; self._p += 1; return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self._d, self._p)[0]; self._p += 2; return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self._d, self._p)[0]; self._p += 4; return v

    def u64(self) -> int:
        # SDK byteArrayToLong: lo = bytes[0..3], hi = bytes[4..7], result = lo + hi * 2^32
        lo = struct.unpack_from("<I", self._d, self._p)[0]
        hi = struct.unpack_from("<I", self._d, self._p + 4)[0]
        self._p += 8
        return lo + hi * 4_294_967_296

    def raw(self, n: int) -> bytes:
        v = self._d[self._p:self._p + n]; self._p += n; return v


# ── Protocol parser ───────────────────────────────────────────────────────────

class Parser:
    """
    Stateful byte-stream parser for NeoSmartpen V2 protocol.
    Pushes ("dot", dict) and ("event", str) onto an asyncio.Queue.
    """

    def __init__(self, queue: asyncio.Queue):
        self._q   = queue
        self._buf = bytearray()
        self._in  = False
        self._esc = False
        # Running paper / timing state
        self._ts   = -1
        self._sec  = -1
        self._own  = -1
        self._note = -1
        self._page = -1

    # ── byte-level framing ────────────────────────────────────────────────────

    def feed(self, data: bytes) -> None:
        for b in data:
            self._byte(b)

    def _byte(self, b: int) -> None:
        if b == STX:
            self._buf = bytearray(); self._in = True; self._esc = False; return
        if not self._in:
            return
        if b == ETX:
            self._in = False
            self._parse(bytes(self._buf))
            self._buf = bytearray()
            return
        if b == DLE and not self._esc:
            self._esc = True; return
        if self._esc:
            self._buf.append(b ^ 0x20); self._esc = False; return
        self._buf.append(b)

    # ── packet dispatch ───────────────────────────────────────────────────────

    def _parse(self, raw: bytes) -> None:
        if len(raw) < 3:
            return
        i = 0
        cmd = raw[i]; i += 1

        # Online-event commands (0x6X) carry no RESULT byte
        is_event = (cmd >> 4) == 0x6 or cmd in (0x73, 0x24, 0x32)
        if not is_event:
            if i >= len(raw):
                return
            result = raw[i]; i += 1
            if result != 0:
                return  # non-zero result = error response, skip
        i += 2          # skip 2-byte length field
        self._cmd(cmd, raw[i:])

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ev(self, name: str) -> None:
        try:
            self._q.put_nowait(("event", name))
        except asyncio.QueueFull:
            pass

    def _dot(self, dtype: int, ts: int, x: float, y: float,
             pressure: int, tx: int, ty: int) -> None:
        try:
            self._q.put_nowait(("dot", {
                "dot_type": dtype, "timestamp": ts,
                "x": x, "y": y, "pressure": pressure,
                "tilt_x": tx, "tilt_y": ty,
                "section": self._sec, "owner": self._own,
                "note": self._note, "page": self._page,
            }))
        except asyncio.QueueFull:
            pass

    # ── command handlers ──────────────────────────────────────────────────────

    def _cmd(self, cmd: int, data: bytes) -> None:
        try:
            r = _R(data)

            # Handshake responses
            if cmd == CMD_VER_RSP:
                self._ev("version_ok")

            elif cmd == CMD_PASS_RSP:
                status = r.u8()
                self._ev("auth_ok" if status == 1 else "auth_fail")

            elif cmd == CMD_SET_RSP:
                # SETTING_INFO_RESPONSE layout (from Response.ts SettingInfo):
                #   Locked[1] RetryCount[1] ResetCount[1] Timestamp[8] ...
                locked = bool(data[0]) if data else False
                self._ev("setting_locked" if locked else "setting_ok")

            elif cmd == CMD_ONL_RSP:
                self._ev("online_ok")

            # ── New-firmware pen-down (0x69) ───────────────────────────────
            elif cmd == CMD_NEW_DOWN:
                r.u8()            # event counter
                ts = r.u64()
                r.u8(); r.u32()   # tip type, tip color
                self._ts = ts
                self._dot(DOT_DOWN, ts, -1, -1, 0, 0, 0)

            # ── Old-firmware combined up/down (0x63) ───────────────────────
            elif cmd == CMD_UPDOWN_OLD:
                is_down = r.u8() == 0x00
                ts = r.u64()
                r.u8(); r.u32()   # tip type, color
                if is_down:
                    self._ts = ts
                    self._dot(DOT_DOWN, ts, -1, -1, 0, 0, 0)
                else:
                    self._ts = -1
                    self._dot(DOT_UP, ts, -1, -1, 0, 0, 0)

            # ── New-firmware pen-up (0x6A) ─────────────────────────────────
            elif cmd == CMD_NEW_UP:
                r.u8()            # event counter
                ts = r.u64()
                self._ts = -1
                self._dot(DOT_UP, ts, -1, -1, 0, 0, 0)

            # ── Paper info (0x6B / 0x64) ───────────────────────────────────
            elif cmd in (CMD_NEW_PAPER, CMD_PAPER_OLD):
                if cmd == CMD_NEW_PAPER:
                    r.u8()        # event counter
                rb = r.raw(4)
                # section = rb[3], owner = rb[0] + rb[1]*256 + rb[2]*65536
                self._sec  = rb[3] & 0xFF
                self._own  = rb[0] + rb[1] * 256 + rb[2] * 65536
                self._note = r.u32()
                self._page = r.u32()
                print(f"  [PAPER]  section={self._sec}  owner={self._own}  "
                      f"note={self._note}  page={self._page}")

            # ── Dot events (0x6C / 0x65) ───────────────────────────────────
            elif cmd in (CMD_NEW_DOT, CMD_DOT_OLD):
                if cmd == CMD_NEW_DOT:
                    r.u8()        # event counter
                td    = r.u8()   # time delta (ms since pen-down timestamp)
                if self._ts >= 0:
                    self._ts += td
                force = r.u16()
                xi    = r.u16();  yi = r.u16()
                fx    = r.u8();   fy = r.u8()   # sub-pixel (hundredths)
                tx    = r.u8();   ty = r.u8()   # tilt angles
                r.u16()           # twist (parsed but not written to CSV)
                self._dot(DOT_MOVE, self._ts,
                          round(xi + fx * 0.01, 2),
                          round(yi + fy * 0.01, 2),
                          force, tx, ty)

            # ── Hover event (0x6F) ─────────────────────────────────────────
            elif cmd == CMD_HOVER:
                td = r.u8()
                if self._ts >= 0:
                    self._ts += td
                xi = r.u16();  yi = r.u16()
                fx = r.u8();   fy = r.u8()
                self._dot(DOT_HOVER, self._ts,
                          round(xi + fx * 0.01, 2),
                          round(yi + fy * 0.01, 2),
                          0, 0, 0)

        except (IndexError, struct.error):
            pass   # truncated / malformed packet — silently discard


# ── BLE scanner ───────────────────────────────────────────────────────────────

async def find_pen(timeout: float = 20.0):
    """
    Scan for a NeoSmartpen by service UUID or device name.
    Returns a BLEDevice or None.
    """
    svc128 = SVC_128.lower()
    svc16  = _uuid16(SVC_16)
    hints  = ("neo", "nwp", "nsp", "moleskine", "pen")

    print(f"Scanning for NeoSmartpen ({timeout:.0f}s) — switch the pen on now…")
    scanner = BleakScanner()
    await scanner.start()

    deadline = asyncio.get_event_loop().time() + timeout
    found = None
    while asyncio.get_event_loop().time() < deadline:
        for dev, adv in scanner.discovered_devices_and_advertisement_data.values():
            uuids = [u.lower() for u in adv.service_uuids]
            if svc128 in uuids or svc16 in uuids:
                found = dev; break
            if dev.name and any(k in dev.name.lower() for k in hints):
                found = dev; break
        if found:
            break
        await asyncio.sleep(0.25)

    await scanner.stop()
    return found


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _prepare_csv(path: str):
    """
    Append safely so reconnecting the pen during one server session does not
    overwrite already recorded dots. Legacy CSVs are migrated with blank local
    receive-time columns.
    """
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if csv_path.exists() and csv_path.stat().st_size > 0:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            existing = reader.fieldnames or []
            rows = list(reader)
        if existing != PEN_FIELDNAMES:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PEN_FIELDNAMES)
                writer.writeheader()
                for row in rows:
                    writer.writerow({name: row.get(name, "") for name in PEN_FIELDNAMES})
    else:
        with open(csv_path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=PEN_FIELDNAMES).writeheader()

    csvf = open(csv_path, "a", newline="")
    return csvf, csv.DictWriter(csvf, fieldnames=PEN_FIELDNAMES)


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(password: str = "0000", output_path: str | None = None) -> None:
    # CSV output
    if output_path:
        fname = output_path
    else:
        fname = f"pen_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    csvf, wr = _prepare_csv(fname)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    signal.signal(signal.SIGINT,
                  lambda *_: stop.done() or loop.call_soon_threadsafe(stop.set_result, None))

    # ── Scan ──────────────────────────────────────────────────────────────────
    device = await find_pen()
    if device is None:
        print("No pen found. Is it switched on and in range?")
        csvf.close(); return

    print(f"Found: {device.name!r}  [{device.address}]")

    # ── Connect ───────────────────────────────────────────────────────────────
    q: asyncio.Queue = asyncio.Queue(maxsize=4000)
    parser = Parser(q)

    def _on_notify(_, data: bytearray) -> None:
        parser.feed(bytes(data))

    connected = True

    def _on_disconnect(_) -> None:
        nonlocal connected
        connected = False
        print("\n[BLE] Disconnected")
        if not stop.done():
            loop.call_soon_threadsafe(stop.set_result, None)

    print(f"Connecting to {device.address}…")
    async with BleakClient(device, disconnected_callback=_on_disconnect) as client:
        print("Connected!")

        # Resolve which UUIDs are actually present on this pen
        noti_ch, writ_ch = NOTI_128, WRIT_128
        for svc in client.services:
            sl = svc.uuid.lower()
            if sl in (SVC_128.lower(), _uuid16(SVC_16)):
                for c in svc.characteristics:
                    cl = c.uuid.lower()
                    if cl in (NOTI_128.lower(), _uuid16(NOTI_16)):
                        noti_ch = c.uuid
                    elif cl in (WRIT_128.lower(), _uuid16(WRIT_16)):
                        writ_ch = c.uuid

        # Print all characteristics for diagnostics
        for svc in client.services:
            for c in svc.characteristics:
                print(f"  char {c.uuid}  props={list(c.properties)}")
        print(f"  notify → {noti_ch}")
        print(f"  write  → {writ_ch}")

        await client.start_notify(noti_ch, _on_notify)

        # Detect whether the write characteristic needs response=True or False
        _write_with_response = True
        for svc in client.services:
            for c in svc.characteristics:
                if c.uuid.lower() in (WRIT_128.lower(), _uuid16(WRIT_16)):
                    props = [p.lower() for p in c.properties]
                    if "write-without-response" in props and "write" not in props:
                        _write_with_response = False
                    break

        print(f"  write-response={_write_with_response}")

        async def send(pkt: bytes) -> None:
            if not connected:
                return
            try:
                await client.write_gatt_char(writ_ch, pkt, response=_write_with_response)
            except Exception as e:
                # Retry with the opposite mode once
                try:
                    await client.write_gatt_char(writ_ch, pkt, response=not _write_with_response)
                except Exception as e2:
                    print(f"  [WARN] write failed: {e2}")

        # ── Handshake (mirrors PenController.OnConnected / PenHelper.handleMessage) ──
        print("→ VERSION_REQUEST (waiting 500 ms first…)")
        await asyncio.sleep(0.5)
        await send(pkt_version())

        authorized = False
        ready      = False
        dot_count  = 0

        while not stop.done():
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if kind == "event":
                ev = payload

                if ev == "version_ok":
                    print("← VERSION_RESPONSE  →  SETTING_INFO_REQUEST")
                    await send(pkt_setting())

                elif ev == "setting_ok":
                    authorized = True
                    print("← SETTING_INFO (unlocked)  →  ONLINE_DATA_REQUEST")
                    await send(pkt_online())

                elif ev == "setting_locked":
                    print(f"← SETTING_INFO (locked)  →  PASSWORD_REQUEST ({password!r})")
                    await send(pkt_password(password))

                elif ev == "auth_ok":
                    authorized = True
                    print("← PASSWORD accepted  →  ONLINE_DATA_REQUEST")
                    await send(pkt_online())

                elif ev == "auth_fail":
                    print("! Password rejected. "
                          "Use --password to specify the correct pen password.")
                    if not stop.done():
                        loop.call_soon_threadsafe(stop.set_result, None)

                elif ev == "online_ok":
                    ready = True
                    print("← ONLINE active — start writing!  (Ctrl+C to stop)\n")

            elif kind == "dot" and ready:
                dot   = payload
                dtype = dot["dot_type"]
                lbl   = LABEL.get(dtype, str(dtype))

                if dtype == DOT_DOWN:
                    dot_count = 0
                    print(f"\n▼  PEN_DOWN   ts={dot['timestamp']}")
                elif dtype == DOT_UP:
                    print(f"▲  PEN_UP     ({dot_count} dots)\n")
                    dot_count = 0
                else:
                    dot_count += 1
                    suffix = ""
                    if dtype == DOT_HOVER:
                        suffix = "  [hover]"
                    print(f"   x={dot['x']:8.2f}  y={dot['y']:8.2f}  "
                          f"p={dot['pressure']:5d}  tx={dot['tilt_x']:3d}  "
                          f"ty={dot['tilt_y']:3d}{suffix}", end="\r")

                # CSV (raw Ncode values)
                local_ts_ms = _now_ms()
                wr.writerow({
                    "local_ts": datetime.fromtimestamp(
                        local_ts_ms / 1000,
                        tz=timezone.utc,
                    ).isoformat(),
                    "local_ts_ms": local_ts_ms,
                    "timestamp": dot["timestamp"],
                    "x": dot["x"],
                    "y": dot["y"],
                    "pressure": dot["pressure"],
                    "dot_type": lbl,
                    "tilt_x": dot["tilt_x"],
                    "tilt_y": dot["tilt_y"],
                    "section": dot["section"],
                    "owner": dot["owner"],
                    "note": dot["note"],
                    "page": dot["page"],
                })
                csvf.flush()

        if connected:
            try:
                await client.stop_notify(noti_ch)
            except Exception:
                pass

    csvf.close()
    print(f"\nSaved → {fname}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="NeoSmartpen BLE dot logger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--password", default="0000",
                    help="Pen password (default: '0000' = no password)")
    ap.add_argument("--session", default=None,
                    help="Session ID (e.g. S001); output goes to data/raw/pen/{session}_pen.csv")
    args = ap.parse_args()

    output_path = None
    if args.session:
        output_path = str(Path(__file__).parent / "data" / "raw" / "pen" / f"{args.session}_pen.csv")

    asyncio.run(run(password=args.password, output_path=output_path))


if __name__ == "__main__":
    main()
