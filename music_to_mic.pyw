"""Music to Mic - send one app's sound (e.g. Brave) plus your mic into a virtual cable.
Set your call app's microphone to "CABLE Output" and callers hear both. Needs VB-Audio Virtual Cable.
A quality-of-life project by Mondcrest Automations. MIT licence.
Uses Windows per-process loopback capture (Win10 2004+), so call audio is never re-sent.
"""
import ctypes, ctypes.wintypes as wt, threading, uuid, os, json, secrets, subprocess, webbrowser, time
import sessions
import numpy as np, sounddevice as sd
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

RATE, CH, BLOCK = 48000, 2, 480
BROWSERS = ("brave.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole = ctypes.OleDLL("ole32")
mmdev = ctypes.WinDLL("Mmdevapi")
mmdev.ActivateAudioInterfaceAsync.restype = ctypes.HRESULT


# ---------- running processes ----------
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]

k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CreateEventW.restype = wt.HANDLE
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]


def processes():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    out, ok = {}, k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.szExeFile, e.th32ParentProcessID)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


UI_PID = [None]  # our own Edge window process


def root_pid(exe):
    """Top process of an app (browsers play audio from a child process; capture covers the tree)."""
    procs, exe = processes(), exe.lower()
    for pid, (name, ppid) in procs.items():
        if name.lower() == exe and procs.get(ppid, ("",))[0].lower() != exe and pid != UI_PID[0]:
            return pid  # skips our own Edge window, so Edge works as a music source


# ---------- raw COM: per-process loopback ----------
class GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]

def guid(s):
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)

IID_IAudioClient = guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2")
IID_IAudioCaptureClient = guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317")
HANDLER_IIDS = {bytes(guid(s)) for s in ("00000000-0000-0000-C000-000000000046",   # IUnknown
                                         "94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90",   # IAgileObject
                                         "41D949AB-9862-444A-80F6-C261334DA5EB")}  # completion handler


def com(obj, idx, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[idx])
    return lambda *a: fn(obj, *a)


def release(obj):
    if obj:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(obj)


QI_T = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
REF_T = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
DONE_T = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)


class Handler:
    """Minimal IActivateAudioInterfaceCompletionHandler (kept alive by Python, so refcount is fake)."""
    def __init__(self):
        self.done = threading.Event()

        def qi(this, riid, ppv):
            ok = bytes(riid.contents) in HANDLER_IIDS
            ppv[0] = this if ok else None
            return 0 if ok else -2147467262  # E_NOINTERFACE

        def completed(this, op):
            self.done.set()
            return 0

        self._fns = (QI_T(qi), REF_T(lambda t: 1), REF_T(lambda t: 1), DONE_T(completed))
        self._vtbl = (ctypes.c_void_p * 4)(*[ctypes.cast(f, ctypes.c_void_p).value for f in self._fns])
        self._obj = ctypes.c_void_p(ctypes.addressof(self._vtbl))
        self.ptr = ctypes.c_void_p(ctypes.addressof(self._obj))


class PROPVARIANT(ctypes.Structure):  # VT_BLOB layout
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("cb", ctypes.c_ulong), ("p", ctypes.c_void_p)]

class ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("pid", wt.DWORD), ("mode", ctypes.c_int)]

class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("tag", wt.WORD), ("ch", wt.WORD), ("rate", wt.DWORD), ("bps", wt.DWORD),
                ("align", wt.WORD), ("bits", wt.WORD), ("cb", wt.WORD)]


def capture_app(pid, ring, stop):
    """Blocking: push float32 stereo frames of process `pid` (and children) into ring until stop."""
    ole.CoInitializeEx(None, 0)
    params = ACTIVATION_PARAMS(1, pid, 0)  # PROCESS_LOOPBACK, include process tree
    pv = PROPVARIANT(vt=65, cb=ctypes.sizeof(params), p=ctypes.addressof(params))
    h, op = Handler(), ctypes.c_void_p()
    client, cap = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        mmdev.ActivateAudioInterfaceAsync("VAD\\Process_Loopback", ctypes.byref(IID_IAudioClient),
                                          ctypes.byref(pv), h.ptr, ctypes.byref(op))
        if not h.done.wait(5):
            raise OSError("Windows did not answer the capture request")
        hr = ctypes.c_long()
        com(op, 3, ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(hr), ctypes.byref(client))
        if hr.value < 0:
            raise OSError(f"App capture failed (0x{hr.value & 0xFFFFFFFF:08X})")

        fmt = WAVEFORMATEX(3, CH, RATE, RATE * CH * 4, CH * 4, 32, 0)  # float32 stereo 48k
        flags = 0x00020000 | 0x00040000 | 0x80000000 | 0x08000000  # loopback|event|autoconvert|src quality
        com(client, 3, ctypes.c_int, wt.DWORD, ctypes.c_longlong, ctypes.c_longlong,
            ctypes.POINTER(WAVEFORMATEX), ctypes.c_void_p)(0, flags, 1_000_000, 0, ctypes.byref(fmt), None)
        event = k32.CreateEventW(None, False, False, None)
        com(client, 13, wt.HANDLE)(event)
        com(client, 14, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(IID_IAudioCaptureClient), ctypes.byref(cap))

        get_buf = com(cap, 3, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
                      ctypes.POINTER(wt.DWORD), ctypes.c_void_p, ctypes.c_void_p)
        rel_buf = com(cap, 4, ctypes.c_uint32)
        next_size = com(cap, 5, ctypes.POINTER(ctypes.c_uint32))
        n, data, fl = ctypes.c_uint32(), ctypes.c_void_p(), wt.DWORD()

        com(client, 10)()  # Start
        while not stop.is_set():
            k32.WaitForSingleObject(event, 100)
            next_size(ctypes.byref(n))
            while n.value:
                get_buf(ctypes.byref(data), ctypes.byref(n), ctypes.byref(fl), None, None)
                frames = n.value
                if fl.value & 2 or not data.value:  # AUDCLNT_BUFFERFLAGS_SILENT
                    chunk = np.zeros((frames, CH), np.float32)
                else:
                    chunk = np.ctypeslib.as_array(ctypes.cast(data, ctypes.POINTER(ctypes.c_float)),
                                                  (frames * CH,)).reshape(frames, CH).copy()
                rel_buf(frames)
                ring.write(chunk)
                next_size(ctypes.byref(n))
        com(client, 11)()  # Stop
        k32.CloseHandle(event)
    finally:
        for o in (cap, client, op):
            release(o.value)
        ole.CoUninitialize()


# ---------- mixing ----------
class Ring:
    """Thread-safe FIFO of stereo frames.
    Waits for 60 ms before playing; if it ever backs up past 250 ms (clock drift), it trims once to 60 ms.
    ponytail: drift fix is a rare single skip, not resampling."""
    def __init__(self, prebuffer=RATE * 6 // 100, max_frames=RATE // 4):
        self.buf, self.lock, self.ready = np.zeros((0, CH), np.float32), threading.Lock(), False
        self.pre, self.max = prebuffer, max_frames

    def write(self, x):
        with self.lock:
            self.buf = np.concatenate([self.buf, x])
            if len(self.buf) > self.max:
                self.buf = self.buf[-self.pre:]

    def read(self, n):
        with self.lock:
            if not self.ready and len(self.buf) >= self.pre:
                self.ready = True
            if not self.ready:
                return np.zeros((n, CH), np.float32)
            out, self.buf = self.buf[:n], self.buf[n:]
            if len(out) < n:  # ran dry: pad, then rebuffer
                self.ready = False
                out = np.concatenate([out, np.zeros((n - len(out), CH), np.float32)])
            return out


class Limiter:
    """Peak limiter: lets you push volume up without hard-clip distortion. Instant attack, ~0.5 s release."""
    def __init__(self, ceiling=0.95):
        self.ceiling, self.g, self.rel = ceiling, 1.0, np.exp(-1 / (0.5 * RATE))

    def process(self, x):
        peak = float(np.abs(x).max())
        target = min(1.0, self.ceiling / peak) if peak > 0 else 1.0
        new = target if target < self.g else self.g + (target - self.g) * (1 - self.rel ** len(x))
        y = x * np.linspace(self.g, new, len(x), dtype=np.float32)[:, None]
        self.g = new
        return np.clip(y, -self.ceiling, self.ceiling)


class Clarity:
    """Linear-phase FIR EQ via FFT overlap-add (~11 ms delay). WhatsApp's voice codec and noise suppression
    dull music: cut the boomy lows that eat its bitrate, lift presence/air so the music stays crisp."""
    TAPS = 1023
    F = [0, 40, 80, 140, 300, 800, 2000, 3500, 6000, 9000, 14000, 24000]
    DB = [-24, -18, -6, -1, -2, 0, 2, 5, 6, 5, 2, 0]

    def __init__(self):
        n = 8192
        mag = 10 ** (np.interp(np.fft.rfftfreq(n, 1 / RATE), self.F, self.DB) / 20)
        h = np.roll(np.fft.irfft(mag, n), self.TAPS // 2)[: self.TAPS] * np.hanning(self.TAPS)
        self.h, self.ffts = h * 10 ** (-3 / 20), {}  # -3 dB headroom for the boosts
        self.tail = np.zeros((self.TAPS - 1, CH), np.float32)

    def process(self, x):
        n = len(x)
        N = 1 << int(np.ceil(np.log2(n + self.TAPS - 1)))
        if N not in self.ffts:
            self.ffts[N] = np.fft.rfft(self.h, N)[:, None]
        y = np.fft.irfft(np.fft.rfft(x, N, axis=0) * self.ffts[N], N, axis=0)[: n + self.TAPS - 1].astype(np.float32)
        y[: self.TAPS - 1] += self.tail
        self.tail = y[n:].copy()
        return y[:n]


def wasapi_devices(kind):
    api = next(i for i, h in enumerate(sd.query_hostapis()) if "WASAPI" in h["name"])
    return [(d["name"], i, d[f"max_{kind}_channels"]) for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == api and d[f"max_{kind}_channels"] > 0]


def tree_pids(root):
    procs, pids = processes(), {root}
    grew = True
    while grew:
        new = {p for p, (_, pp) in procs.items() if pp in pids} - pids
        pids |= new
        grew = bool(new)
    return pids


RESTORE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "MusicToMic", "restore.json")


class Ducker:
    """Preview without hearing the music twice: turn the app's own speaker volume down to 2% and boost
    the capture 50x to match (float path, so no quality loss) - callers hear no change.
    Ramps over ~0.75 s so the few ms of capture lag can't cause a jump. Saves originals to RESTORE in case of crash."""
    FLOOR, STEP, TICK = 0.02, 1.17, 0.03  # 1.17**25 ~= 50

    def __init__(self, mixer, exe, root):
        self.mixer, self.exe, self.root = mixer, exe, root
        self.f, self.comp, self.orig = 1.0, 1.0, {}
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        sessions.com_init()
        self.restore_after_crash()
        pids, last_pids = tree_pids(self.root), time.monotonic()
        try:
            while not self.mixer.stop.is_set():
                if time.monotonic() - last_pids > 2:
                    pids, last_pids = tree_pids(self.root), time.monotonic()
                found = sessions.list_sessions(pids)
                try:
                    target = self.FLOOR if self.mixer.preview and found else 1.0
                    f = min(target, self.f * self.STEP) if target > self.f else max(target, self.f / self.STEP)
                    for sid, vol in found:
                        if sid not in self.orig:
                            self.orig[sid] = sessions.get_volume(vol) / self.f if self.f == 1.0 else 1.0
                        want = self.orig[sid] * f
                        if abs(sessions.get_volume(vol) - want) > 1e-4:
                            sessions.set_volume(vol, want)
                    self.comp = 1.0 / self.f  # audio arriving now was rendered ~1 tick ago, at the old level
                    self.f = f
                    self.save()
                finally:
                    for _, vol in found:
                        sessions.release(vol.value)
                time.sleep(self.TICK if f != target or self.comp != 1.0 / f else 0.3)
        finally:
            self.put_back(pids)

    def put_back(self, pids):
        for sid, vol in sessions.list_sessions(pids):
            if sid in self.orig:
                sessions.set_volume(vol, self.orig[sid])
            sessions.release(vol.value)
        self.f, self.comp = 1.0, 1.0
        self.save()

    def save(self):
        try:
            if self.f < 1.0:
                os.makedirs(os.path.dirname(RESTORE), exist_ok=True)
                with open(RESTORE, "w") as fh:
                    json.dump({"exe": self.exe, "volume": max(self.orig.values(), default=1.0)}, fh)
            elif os.path.exists(RESTORE):
                os.remove(RESTORE)
        except OSError:
            pass

    def restore_after_crash(self):
        try:
            with open(RESTORE) as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return
        if saved.get("exe", "").lower() == self.exe.lower():
            for _, vol in sessions.list_sessions(tree_pids(self.root)):
                sessions.set_volume(vol, float(saved.get("volume", 1.0)))
                sessions.release(vol.value)
        try:
            os.remove(RESTORE)
        except OSError:
            pass


class Mixer:
    def __init__(self, app_exe, mic, out, preview_out, status):
        self.music, self.voice, self.monitor = Ring(), Ring(), Ring()
        self.music_gain, self.mic_gain, self.preview, self.clarity = 1.0, 1.0, False, True
        self.limiter, self.voice_limiter, self.eq, self.peak = Limiter(), Limiter(0.9), Clarity(), 0.0
        self.stop = threading.Event()
        pid = root_pid(app_exe)
        if not pid:
            raise RuntimeError(f"{app_exe} is not running - open it first")
        wasapi = sd.WasapiSettings(auto_convert=True)
        mic_idx, mic_ch = mic

        def on_mic(indata, frames, t, s):
            self.voice.write(np.repeat(indata, 2, axis=1) if mic_ch == 1 else indata.copy())

        def on_out(outdata, frames, t, s):
            voice = self.voice_limiter.process(self.voice.read(frames) * self.mic_gain)  # big boost, no clipping
            music = self.music.read(frames)
            eq = self.eq.process(music)  # always run so its state stays warm when toggled
            mix = (eq if self.clarity else music) * self.music_gain + voice
            mix = self.limiter.process(mix)
            self.peak = max(self.peak, float(np.abs(mix).max()))
            outdata[:] = mix
            if self.preview:
                self.monitor.write(mix)

        def on_preview(outdata, frames, t, s):
            outdata[:] = self.monitor.read(frames) if self.preview else 0

        class Compensated:  # undo the Ducker's speaker cut at capture time, so timing lines up
            write = lambda _, x: self.music.write(x * self.ducker.comp)

        def run_capture():
            try:
                capture_app(pid, Compensated(), self.stop)
            except Exception as e:
                status(f"Music capture stopped: {e}")

        common = dict(samplerate=RATE, dtype="float32", blocksize=BLOCK, latency="high", extra_settings=wasapi)
        self.streams = [sd.InputStream(device=mic_idx, channels=min(mic_ch, 2), callback=on_mic, **common),
                        sd.OutputStream(device=out, channels=CH, callback=on_out, **common)]
        if preview_out is not None:
            self.streams.append(sd.OutputStream(device=preview_out, channels=CH, callback=on_preview, **common))
        try:
            for s in self.streams:
                s.start()
        except Exception:
            self.close()
            raise
        self.ducker = Ducker(self, app_exe, pid)
        threading.Thread(target=run_capture, daemon=True).start()

    def take_peak(self):
        p, self.peak = self.peak, 0.0
        return p

    def close(self):
        self.stop.set()
        if getattr(self, "ducker", None):
            self.ducker.thread.join(2)  # puts the app's speaker volume back
        for s in self.streams:
            try:
                s.stop(); s.close()
            except sd.PortAudioError:
                pass


# ---------- web window (localhost only) ----------
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = secrets.token_urlsafe(16)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class App:
    def __init__(self):
        self.mixer, self.status = None, "Ready. Press Start, then play music."
        self.settings = dict(music=150, mic=250, preview=False, clarity=True)
        self.lock = threading.Lock()

    def devices(self, refresh=False):
        if refresh and not self.mixer:
            sd._terminate(); sd._initialize()
        apps = sorted({n for n, _ in processes().values() if n.lower().endswith(".exe")}, key=str.lower)
        mics, outs = [m[0] for m in wasapi_devices("input")], [o[0] for o in wasapi_devices("output")]
        speakers = [o for o in outs if "CABLE" not in o]
        low = {a.lower(): a for a in apps}
        return dict(apps=apps, mics=mics, outs=outs, speakers=speakers, defaults=dict(
            app=next((low[b] for b in BROWSERS if b in low), apps[0] if apps else ""),
            mic=next((m for m in mics if "CABLE" not in m), ""),
            out=next((o for o in outs if "CABLE Input" in o), ""),
            preview_out=speakers[0] if speakers else ""))

    def start(self, d):
        with self.lock:
            if self.mixer:
                return
            mics, outs = wasapi_devices("input"), wasapi_devices("output")
            mic = next(((i, ch) for n, i, ch in mics if n == d.get("mic")), None)
            out = next((i for n, i, _ in outs if n == d.get("out")), None)
            if mic is None or out is None:
                raise RuntimeError("Pick your mic and the 'CABLE Input' device under Devices.")
            prev = next((i for n, i, _ in outs if n == d.get("preview_out") and "CABLE" not in n), None)
            self.mixer = Mixer(d.get("app", ""), mic, out, prev, self.set_status)
            self.apply()
            self.status = f"Live: {d.get('app')} and your mic are going into the call."

    def stop(self):
        with self.lock:
            if self.mixer:
                self.mixer.close()
                self.mixer = None
                self.status = "Stopped."

    def set_status(self, msg):
        self.status = msg

    def apply(self):
        m, s = self.mixer, self.settings
        if m:
            m.music_gain, m.mic_gain = s["music"] / 100, s["mic"] / 100
            m.preview, m.clarity = bool(s["preview"]), bool(s["clarity"])

    def state(self):
        m = self.mixer
        peak = m.take_peak() if m else 0.0
        return dict(running=bool(m), peak=peak, limiting=bool(m and m.limiter.g < 0.8), status=self.status)


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authed(self):
            if self.headers.get("X-Token") == TOKEN:
                return True
            self.send(403, {"error": "forbidden"})

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                with open(os.path.join(HERE, "ui.html"), "rb") as fh:
                    return self.send(200, fh.read(), "text/html; charset=utf-8")
            if path == "/icon.svg":
                with open(os.path.join(HERE, "icon.svg"), "rb") as fh:
                    return self.send(200, fh.read(), "image/svg+xml")
            if not self.authed():
                return
            if path == "/api/devices":
                return self.send(200, app.devices("refresh" in self.path))
            if path == "/api/state":
                return self.send(200, app.state())
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.authed():
                return
            try:
                ole.CoInitializeEx(None, 0)  # PortAudio's WASAPI streams fail to start on a thread without COM
            except OSError:
                pass
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                if self.path == "/api/start":
                    app.start(body)
                elif self.path == "/api/stop":
                    app.stop()
                elif self.path == "/api/open-settings":
                    os.startfile("ms-settings:apps-volume")  # Volume mixer: per-app input device
                elif self.path == "/api/set":
                    app.settings.update({k: body[k] for k in app.settings if k in body})
                    app.apply()
                else:
                    return self.send(404, {"error": "not found"})
                self.send(200, {"ok": True})
            except Exception as e:
                self.send(200, {"ok": False, "error": str(e)})
    return H


def main():
    app = App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={TOKEN}"
    if os.path.exists(EDGE):
        profile = os.path.join(os.environ["LOCALAPPDATA"], "MusicToMic", "edge")
        ui = subprocess.Popen([EDGE, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                               "--no-default-browser-check", "--window-size=460,800"])
        UI_PID[0] = ui.pid
        ui.wait()  # own profile: exits when window closes
    else:
        webbrowser.open(url)
        threading.Event().wait()  # ponytail: no Edge -> runs until killed; add a Quit button if that ever matters
    app.stop()
    srv.shutdown()


if __name__ == "__main__":
    main()
