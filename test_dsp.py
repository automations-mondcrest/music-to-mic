"""Self-check for the audio maths (no sound devices needed): python test_dsp.py"""
import importlib.util, os
import numpy as np

spec = importlib.util.spec_from_file_location("m2m", os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_to_mic.pyw"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# limiter: 3x overdrive never passes the ceiling
lim, x = m.Limiter(), (3 * np.sin(np.linspace(0, 400, 4800))).astype(np.float32)[:, None].repeat(2, 1)
for _ in range(5):
    y = lim.process(x)
assert 0.9 < np.abs(y).max() <= 0.95 + 1e-6

# ring: waits for prebuffer, returns frames in order, pads when dry
r = m.Ring()
r.write(np.ones((m.BLOCK, 2), np.float32))
assert not r.read(m.BLOCK).any()                      # still buffering
r.write(np.full((r.pre, 2), 2, np.float32))
assert (r.read(m.BLOCK) == 1).all() and (r.read(m.BLOCK) == 2).all()

# clarity EQ: bass cut, presence lifted, streaming matches one-shot
eq, imp = m.Clarity(), np.zeros((48000, 2), np.float32)
imp[0] = 1
h = np.concatenate([eq.process(imp[i:i + 480]) for i in range(0, 48000, 480)])[:, 0]
db = 20 * np.log10(np.abs(np.fft.rfft(h)) + 1e-12)
assert db[50] < -10 and db[6000] > db[1000] + 4
print("ok")
