"""Installs VB-Audio Virtual Cable (VB-CABLE) for Music to Mic, then tidies Windows sound settings.

VB-CABLE is donationware by VB-Audio Software (https://vb-audio.com/Cable/), not part of this project.
This script downloads the official, unmodified package from vb-audio.com, checks its digital signature,
installs it silently (one admin prompt), hides the extra "CABLE In 16ch" device and puts your default
speaker and mic back. Please support VB-Audio if you find it useful.

Run: python setup_cable.py
"""
import ctypes, io, os, re, subprocess, sys, tempfile, time, urllib.request, uuid, zipfile

PAGE = "https://vb-audio.com/Cable/"
FALLBACK = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack46.zip"
SIGNER = "BUREL VINCENT"  # VB-Audio's code-signing name

ole = ctypes.OleDLL("ole32")
PP = ctypes.POINTER(ctypes.c_void_p)


def guid(s):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def fn(obj, idx, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    f = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[idx])
    return lambda *a: f(obj, *a)


def create(clsid, iid):
    p = ctypes.c_void_p()
    ole.CoCreateInstance(ctypes.byref(guid(clsid)), None, 1, ctypes.byref(guid(iid)), ctypes.byref(p))
    return p


def defaults():
    """Current default endpoint ids: {(flow, role): id}. flow 0 = speakers, 1 = mics."""
    en = create("BCDE0395-E52F-467C-8E3D-C4579291692E", "A95664D2-9614-4F35-A746-DE8DB63617E6")
    free = ctypes.windll.ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    out = {}
    for flow in (0, 1):
        for role in (0, 1, 2):
            dev, sid = ctypes.c_void_p(), ctypes.c_wchar_p()
            try:
                fn(en, 4, ctypes.c_int, ctypes.c_int, PP)(flow, role, ctypes.byref(dev))
                fn(dev, 5, ctypes.POINTER(ctypes.c_wchar_p))(ctypes.byref(sid))
                out[(flow, role)] = sid.value
                free(sid)
            except OSError:
                pass  # no device of that kind
    return out


def policy():
    return create("870af99c-171d-4f9e-af0d-e63df40c2bc9", "f8679f50-850a-41cf-9c72-430f290290c8")


def set_defaults(saved):
    pc = policy()
    for (flow, role), dev in saved.items():
        if "CABLE" not in endpoint_name(dev):
            fn(pc, 13, ctypes.c_wchar_p, ctypes.c_int)(dev, role)


def endpoints():
    """{endpoint id: friendly name} for audio endpoints, via PnP."""
    ps = ("Get-PnpDevice -Class AudioEndpoint -PresentOnly | ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName }")
    lines = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.splitlines()
    return {l.split("|", 1)[0].split("\\")[-1]: l.split("|", 1)[1] for l in lines if "|" in l}


def endpoint_name(dev_id):
    return next((n for d, n in endpoints().items() if d.lower() == dev_id.lower()), "")


def cable_installed():
    return any("VB-Audio Virtual Cable" in n for n in endpoints().values())


def download():
    url = FALLBACK
    try:
        html = urllib.request.urlopen(PAGE, timeout=20).read().decode("utf-8", "ignore")
        links = re.findall(r'https?://download\.vb-audio\.com/Download_CABLE/VBCABLE_Driver_Pack\d+\.zip', html)
        url = links[0] if links else url
    except OSError:
        pass
    print(f"Downloading VB-CABLE from {url}")
    data = urllib.request.urlopen(url, timeout=60).read()
    folder = tempfile.mkdtemp(prefix="vbcable-")
    zipfile.ZipFile(io.BytesIO(data)).extractall(folder)
    return folder


def signed_by_vbaudio(exe):
    ps = f"(Get-AuthenticodeSignature -LiteralPath '{exe}') | ForEach-Object {{ $_.Status.ToString() + '|' + $_.SignerCertificate.Subject }}"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    return out.startswith("Valid|") and SIGNER in out


def run_installer(exe):
    ps = f"Start-Process -FilePath '{exe}' -ArgumentList '-i','-h' -WorkingDirectory '{os.path.dirname(exe)}' -Verb RunAs -Wait"
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps]).returncode == 0


def hide_extra_cable():
    pc = policy()
    for dev, name in endpoints().items():
        if "CABLE In 16" in name:
            fn(pc, 14, ctypes.c_wchar_p, ctypes.c_int)(dev, 0)
            print(f"Hid extra device: {name}")


def main():
    ole.CoInitialize(None)
    print("VB-CABLE (VB-Audio Software, https://vb-audio.com/Cable/) is donationware.")
    print("Please support VB-Audio if you find it useful.\n")
    if cable_installed():
        print("VB-CABLE is already installed.")
        hide_extra_cable()
        return 0
    saved = defaults()
    exe = os.path.join(download(), "VBCABLE_Setup_x64.exe")
    if not os.path.exists(exe) or not signed_by_vbaudio(exe):
        print("The downloaded installer is not signed by VB-Audio. Stopping for safety.")
        return 1
    print("Installing VB-CABLE. Click Yes on the Windows admin prompt...")
    if not run_installer(exe):
        print("Install was cancelled.")
        return 1
    for _ in range(30):
        if cable_installed():
            break
        time.sleep(1)
    else:
        print("VB-CABLE did not show up yet. Restart your PC, then run install.bat again.")
        return 1
    time.sleep(2)
    hide_extra_cable()
    set_defaults(saved)
    print("VB-CABLE installed. Your default speaker and mic were kept.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
