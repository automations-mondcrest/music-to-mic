"""Read/set an app's own speaker volume (Windows audio sessions) on every active output device."""
import ctypes, uuid

ole = ctypes.OleDLL("ole32")
PP = ctypes.POINTER(ctypes.c_void_p)
_free = ctypes.windll.ole32.CoTaskMemFree  # returns void, so not via OleDLL
_free.restype, _free.argtypes = None, [ctypes.c_void_p]


def _guid(s):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


def _fn(obj, idx, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    f = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[idx])
    return lambda *a: f(obj, *a)


def release(obj):
    if obj:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(obj)


CLSID_Enum = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_Enum = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_SessMgr2 = _guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_Ctl2 = _guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d")
IID_Vol = _guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")


def com_init():
    try:
        ole.CoInitializeEx(None, 0)
    except OSError:
        pass


def list_sessions(pids):
    """[(session instance id, ISimpleAudioVolume ptr)] for sessions owned by `pids`. Caller must release() each ptr."""
    out, held = [], []
    en, coll = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        ole.CoCreateInstance(ctypes.byref(CLSID_Enum), None, 1, ctypes.byref(IID_Enum), ctypes.byref(en))
        _fn(en, 3, ctypes.c_int, ctypes.c_ulong, PP)(0, 1, ctypes.byref(coll))  # render, ACTIVE
        n = ctypes.c_uint()
        _fn(coll, 3, ctypes.POINTER(ctypes.c_uint))(ctypes.byref(n))
        for i in range(n.value):
            dev, mgr, sen = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
            held += [dev, mgr, sen]
            _fn(coll, 4, ctypes.c_uint, PP)(i, ctypes.byref(dev))
            _fn(dev, 3, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, PP)(ctypes.addressof(IID_SessMgr2), 23, None, ctypes.byref(mgr))
            _fn(mgr, 5, PP)(ctypes.byref(sen))
            count = ctypes.c_int()
            _fn(sen, 3, ctypes.POINTER(ctypes.c_int))(ctypes.byref(count))
            for j in range(count.value):
                ctl, ctl2 = ctypes.c_void_p(), ctypes.c_void_p()
                held += [ctl, ctl2]
                _fn(sen, 4, ctypes.c_int, PP)(j, ctypes.byref(ctl))
                _fn(ctl, 0, ctypes.c_void_p, PP)(ctypes.addressof(IID_Ctl2), ctypes.byref(ctl2))
                pid = ctypes.c_ulong()
                try:
                    _fn(ctl2, 14, ctypes.POINTER(ctypes.c_ulong))(ctypes.byref(pid))
                except OSError:
                    continue  # multi-process session: not ours
                if pid.value not in pids:
                    continue
                sid = ctypes.c_wchar_p()
                _fn(ctl2, 13, ctypes.POINTER(ctypes.c_wchar_p))(ctypes.byref(sid))
                key = sid.value
                _free(sid)
                vol = ctypes.c_void_p()
                _fn(ctl, 0, ctypes.c_void_p, PP)(ctypes.addressof(IID_Vol), ctypes.byref(vol))
                out.append((key, vol))
    finally:
        for o in reversed(held + [coll, en]):
            release(o.value)
    return out


def get_volume(vol):
    v = ctypes.c_float()
    _fn(vol, 4, ctypes.POINTER(ctypes.c_float))(ctypes.byref(v))
    return v.value


def set_volume(vol, level):
    _fn(vol, 3, ctypes.c_float, ctypes.c_void_p)(level, None)
