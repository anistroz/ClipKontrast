"""Faces, so a clip filled to the screen follows the person instead of cutting them off at the side.

A 16:9 picture filled into a 9:16 short keeps only the middle third of it. When the streamer sits off-centre, or
moves around (an IRL stream, a podcast, "just chatting"), the middle third can miss them. Here the face is found
twice a second with YuNet (OpenCV's small face detector: about 230 KB, MIT licence, run with onnxruntime), and a
calm "camera" follows it: it holds still while the face stays near the middle, and glides across only when the face
moves away, so the clip never shakes.

Downloaded once, by itself, at start. Without it (or onnxruntime), clips are filled to the screen from the middle,
as before."""
import subprocess
import threading

import numpy as np

from . import config

URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
MODEL = config.MODELS_DIR / "faces" / "yunet.onnx"
SIZE = 640                 # the model's own input: 640 x 640
RATE = 2                   # faces looked for twice a second
MIN_SCORE = 0.7
NO_WINDOW = 0x08000000 if __import__("os").name == "nt" else 0
_lock = threading.Lock()
_sess = {"s": None, "failed": False}
state = {"error": ""}


def ready() -> bool:
    if not MODEL.is_file() or MODEL.stat().st_size < 100_000:
        return False
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure() -> bool:
    if MODEL.is_file() and MODEL.stat().st_size >= 100_000:
        return True
    if config.env("CLIPKONTRAST_FETCH_MODEL", "1") == "0":
        return False
    from . import fetch_model
    with _lock:
        tmp = MODEL.with_suffix(".part")
        try:
            MODEL.parent.mkdir(parents=True, exist_ok=True)
            fetch_model._download(URL, tmp, (0, 100), progress={"percent": 0})
            if tmp.stat().st_size < 100_000 or tmp.read_bytes()[:4] == b"vers":      # a Git LFS pointer, not the model
                raise RuntimeError("The face model didn't download properly.")
            tmp.replace(MODEL)
            return True
        except Exception as e:  # noqa: BLE001 - only a bonus: tried again next start
            state["error"] = str(e)[:200]
            tmp.unlink(missing_ok=True)
            return False


def _session():
    if _sess["s"] is not None or _sess["failed"]:
        return _sess["s"]
    with _lock:
        if _sess["s"] is None and not _sess["failed"]:
            try:
                import onnxruntime as ort
                o = ort.SessionOptions()
                o.intra_op_num_threads = 2
                _sess["s"] = ort.InferenceSession(str(MODEL), o, providers=["CPUExecutionProvider"])
            except Exception as e:  # noqa: BLE001
                _sess["failed"] = True
                state["error"] = str(e)[:200]
    return _sess["s"]


def detect(rgb: np.ndarray) -> list:
    """The faces in one picture (H x W x 3, RGB, 0-255): [(score, cx, cy, w, h)] in its own pixels, best first."""
    s = _session()
    if s is None:
        return []
    h0, w0 = rgb.shape[:2]
    k = SIZE / max(h0, w0)
    w, h = max(1, int(w0 * k)), max(1, int(h0 * k))
    if (w, h) != (w0, h0):
        from PIL import Image
        rgb = np.asarray(Image.fromarray(rgb.astype(np.uint8)).resize((w, h)))
    x = np.zeros((SIZE, SIZE, 3), np.float32)
    x[:h, :w] = rgb[:, :, ::-1]                       # the model reads BGR
    outs = dict(zip([o.name for o in s.get_outputs()], s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})))
    found = []
    for st in (8, 16, 32):
        cols = SIZE // st
        sc = np.sqrt(np.clip(outs[f"cls_{st}"][0, :, 0], 0, 1) * np.clip(outs[f"obj_{st}"][0, :, 0], 0, 1))
        bb = outs[f"bbox_{st}"][0]
        for i in np.where(sc >= MIN_SCORE)[0]:
            r, c = divmod(int(i), cols)
            found.append((float(sc[i]), (c + bb[i, 0]) * st / k, (r + bb[i, 1]) * st / k, np.exp(bb[i, 2]) * st / k, np.exp(bb[i, 3]) * st / k))
    found.sort(key=lambda f: -f[0])
    kept = []                                          # one box per face: drop boxes that mostly cover a kept one
    for f in found:
        if all(_iou(f, g) < 0.3 for g in kept):
            kept.append(f)
    return [tuple(float(v) for v in f) for f in kept]


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a[1] - a[3] / 2, a[2] - a[4] / 2, a[1] + a[3] / 2, a[2] + a[4] / 2
    bx0, by0, bx1, by1 = b[1] - b[3] / 2, b[2] - b[4] / 2, b[1] + b[3] / 2, b[2] + b[4] / 2
    iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    return inter / max(1e-6, a[3] * a[4] + b[3] * b[4] - inter)


def track(src, start: float, end: float):
    """Where the main face is across [start, end] of a video: [(seconds from start, x as a share of the width)],
    twice a second, None where no face was seen. [] when faces can't be looked for."""
    if not ready() or end - start < 1:
        return []
    w = 640
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(src),
           "-vf", f"fps={RATE},scale={w}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", str(src)], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        sw, sh = (int(v) for v in probe.stdout.strip().split(",")[:2])
        h = int(round(w * sh / sw / 2)) * 2
        p = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    size = w * h * 3
    n = len(p.stdout) // size if size else 0
    out, prev = [], None
    for i in range(n):
        frame = np.frombuffer(p.stdout[i * size:(i + 1) * size], np.uint8).reshape(h, w, 3)
        fs = detect(frame)
        if not fs:
            out.append((i / RATE, None))
            continue
        # the main face: big and sure, and the same person as before rather than someone passing behind
        def rank(f):
            r = f[0] * f[3] * f[4]
            return r * (1.0 - 0.6 * min(1.0, abs(f[1] / w - prev))) if prev is not None else r
        best = max(fs, key=rank)
        prev = best[1] / w
        out.append((i / RATE, prev))
    return out


def camera(points, crop_share: float, dead: float = 0.07, speed: float = 0.35):
    """A calm camera over the face's path: [(seconds, x of the crop's centre as a share of the width)], only where it
    moves. crop_share is how much of the width the crop keeps (0.32 for 16:9 into 9:16). It holds still while the face
    stays within `dead` of the centre of the crop, then glides at most `speed` of the width per second."""
    seen = [x for _, x in points if x is not None]
    if not points or len(seen) < max(2, len(points) // 4):
        return []                                      # too few faces to follow: the middle, as before
    xs, last = [], None
    for _, x in points:                                # gaps keep the last place (or the first face seen)
        last = x if x is not None else (last if last is not None else seen[0])
        xs.append(last)
    xs = np.array(xs, dtype=np.float32)
    if len(xs) >= 5:                                   # a stray detection doesn't move the camera
        pad = np.pad(xs, 2, mode="edge")
        xs = np.array([np.median(pad[i:i + 5]) for i in range(len(xs))], dtype=np.float32)
    lo, hi = crop_share / 2, 1 - crop_share / 2
    cam = float(np.clip(xs[0], lo, hi))
    dt = points[1][0] - points[0][0] if len(points) > 1 else 1 / RATE
    keys = [(0.0, cam)]
    for (t, _), x in zip(points[1:], xs[1:]):
        want = float(np.clip(x, lo, hi))
        if abs(want - cam) > dead:
            step = min(abs(want - cam) - dead * 0.5, speed * dt)
            cam += step if want > cam else -step
            keys.append((t, cam))
        elif keys[-1][0] < t - dt * 1.5 and keys[-1][1] != cam:
            keys.append((t, cam))
    keys.append((points[-1][0] + dt, cam))
    simple = [keys[0]]                                 # straight stretches as one line
    for i in range(1, len(keys) - 1):
        (t0, x0), (t1, x1), (t2, x2) = simple[-1], keys[i], keys[i + 1]
        if abs((x0 + (x2 - x0) * (t1 - t0) / max(1e-6, t2 - t0)) - x1) > 0.004:
            simple.append(keys[i])
    simple.append(keys[-1])
    return [(round(t, 2), round(x, 4)) for t, x in simple]


def crop_x(keys) -> str:
    """ffmpeg's crop x for the camera keys (in the clip's own seconds): straight lines between them, the crop's centre
    as a share of the picture's width, kept inside the picture. "" for none (the middle)."""
    if not keys:
        return ""
    f = f"{keys[-1][1]:.4f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        seg = f"{x0:.4f}" if abs(x1 - x0) < 1e-4 else f"({x0:.4f}+({x1 - x0:.4f})*(t-{t0:.2f})/{max(0.01, t1 - t0):.2f})"
        f = f"if(lt(t\\,{t1:.2f})\\,{seg}\\,{f})"
    return f"max(0\\,min(iw-ow\\,({f})*iw-ow/2))"
