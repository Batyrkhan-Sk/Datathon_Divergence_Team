"""Evidence clip extraction: a short MP4 or GIF centred on a violation timecode.

GET /ui/api/jobs/{job_id}/clip?t=12.5&fmt=mp4   (default)
GET /ui/api/jobs/{job_id}/clip?t=12.5&fmt=gif

The clip is CLIP_SEC seconds long, starting LEAD_SEC before the timecode.
Extracted on the fly; no clip files are stored on disk.
"""
import io
import struct
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

CLIP_SEC = 6.0      # total clip duration
LEAD_SEC = 1.5      # start this many seconds before the timecode
GIF_FPS = 8         # GIF frame rate (keeps file small)
MP4_FPS = 12        # MP4 frame rate
SCALE_W = 480       # output width (preserves aspect ratio)


def _frames(video_path: str, t_start: float, duration: float):
    """Yield BGR frames from [t_start, t_start+duration]."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = max(0, int(t_start * fps))
    end_frame = min(n_frames, int((t_start + duration) * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    out_h = max(1, round(SCALE_W * height / max(width, 1)))
    for _ in range(start_frame, end_frame):
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (SCALE_W, out_h), interpolation=cv2.INTER_AREA)
        yield frame
    cap.release()


def _to_mp4(video_path: str, t_start: float) -> bytes:
    buf = io.BytesIO()
    writer = None
    for frame in _frames(video_path, t_start, CLIP_SEC):
        h, w = frame.shape[:2]
        if writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter()
            writer.open(
                "pipe:1",  # ffmpeg-style; OpenCV ignores it for in-memory
                fourcc, MP4_FPS, (w, h),
            )
            # Fall back to a temp file approach since OpenCV can't write to BytesIO
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp_path = tmp.name
            tmp.close()
            writer.release()
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(tmp_path, fourcc, MP4_FPS, (w, h))
        writer.write(frame)
    if writer is not None:
        writer.release()
        with open(tmp_path, "rb") as f:
            data = f.read()
        os.unlink(tmp_path)
        return data
    return b""


# --- minimal GIF encoder (no external deps) ---

def _write_gif(frames_rgb: list, fps: int) -> bytes:
    """Write a looping GIF from a list of RGB uint8 arrays."""
    delay_cs = max(1, round(100 / fps))  # centiseconds per frame
    out = io.BytesIO()

    def write(b: bytes) -> None:
        out.write(b)

    def quantize(img_rgb: np.ndarray) -> tuple[np.ndarray, bytes]:
        """Reduce to 256 colours via uniform quantization and return (indexed, palette)."""
        h, w = img_rgb.shape[:2]
        # 6-6-6 cube = 216 colours, pad to 256
        r = (img_rgb[:, :, 0] // 43).astype(np.uint8)
        g = (img_rgb[:, :, 1] // 43).astype(np.uint8)
        b = (img_rgb[:, :, 2] // 43).astype(np.uint8)
        idx = (r * 36 + g * 6 + b).astype(np.uint8)
        pal = bytearray(256 * 3)
        for ri in range(6):
            for gi in range(6):
                for bi in range(6):
                    n = ri * 36 + gi * 6 + bi
                    pal[n * 3] = ri * 51
                    pal[n * 3 + 1] = gi * 51
                    pal[n * 3 + 2] = bi * 51
        return idx.flatten(), bytes(pal)

    if not frames_rgb:
        return b""

    h, w = frames_rgb[0].shape[:2]
    # GIF header
    write(b"GIF89a")
    write(struct.pack("<HHBbB", w, h, 0xF7, 0, 0))  # logical screen
    # Global colour table: 256 colours (8-bit)
    _, pal = quantize(frames_rgb[0])
    write(pal)
    # Netscape loop extension
    write(b"\x21\xFF\x0B" + b"NETSCAPE2.0" + b"\x03\x01\x00\x00\x00")
    for frame_rgb in frames_rgb:
        idx, _ = quantize(frame_rgb)
        # Graphic Control Extension (delay)
        write(b"\x21\xF9\x04\x00" + struct.pack("<H", delay_cs) + b"\x00\x00")
        # Image descriptor
        write(b"\x2C" + struct.pack("<HHHHB", 0, 0, w, h, 0))
        # LZW-compressed image data (minimum code size = 8)
        lzw = _lzw_compress(idx, 8)
        write(bytes([8]))
        # Break into sub-blocks of 255 bytes
        for i in range(0, len(lzw), 255):
            chunk = lzw[i:i + 255]
            write(bytes([len(chunk)]) + chunk)
        write(b"\x00")
    write(b"\x3B")  # trailer
    return out.getvalue()


def _lzw_compress(data: bytes, min_code_size: int) -> bytes:
    """Minimal GIF LZW compressor (no external libs)."""
    clear_code = 1 << min_code_size
    eoi_code = clear_code + 1
    table: dict = {bytes([i]): i for i in range(clear_code)}
    code_size = min_code_size + 1
    next_code = eoi_code + 1
    out_bits: list[int] = []
    buf = b""

    def emit(code: int) -> None:
        out_bits.extend([(code >> i) & 1 for i in range(code_size)])

    emit(clear_code)
    for byte in data:
        candidate = buf + bytes([byte])
        if candidate in table:
            buf = candidate
        else:
            emit(table[buf])
            if next_code < 4096:
                table[candidate] = next_code
                next_code += 1
                if next_code > (1 << code_size) and code_size < 12:
                    code_size += 1
            else:
                emit(clear_code)
                table = {bytes([i]): i for i in range(clear_code)}
                code_size = min_code_size + 1
                next_code = eoi_code + 1
            buf = bytes([byte])
    if buf:
        emit(table[buf])
    emit(eoi_code)
    # Pack bits into bytes (little-endian)
    result = bytearray()
    for i in range(0, len(out_bits), 8):
        b = 0
        for j, bit in enumerate(out_bits[i:i + 8]):
            b |= bit << j
        result.append(b)
    return bytes(result)


def make_clip_router(store) -> APIRouter:
    router = APIRouter()

    @router.get("/ui/api/jobs/{job_id}/clip")
    def get_clip(
        job_id: str,
        t: float = Query(..., description="Violation timecode in seconds"),
        fmt: str = Query("mp4", pattern="^(mp4|gif)$"),
    ):
        job = store.get(job_id)
        if job is None or job.source != "ui":
            raise HTTPException(404, "job not found")
        if job.status != "done":
            raise HTTPException(409, "job not finished yet")
        vpath = job.video_path
        if not Path(vpath).is_file():
            raise HTTPException(404, "video file not found")

        t_start = max(0.0, t - LEAD_SEC)

        if fmt == "gif":
            frames_rgb = []
            step = max(1, round(30 / GIF_FPS))
            raw_frames = list(_frames(vpath, t_start, CLIP_SEC))
            for i, frame in enumerate(raw_frames):
                if i % step == 0:
                    frames_rgb.append(frame[:, :, ::-1])  # BGR -> RGB
            data = _write_gif(frames_rgb, GIF_FPS)
            return Response(content=data, media_type="image/gif",
                            headers={"Content-Disposition": f'attachment; filename="clip_{job_id}_{int(t)}.gif"'})
        else:
            data = _to_mp4(vpath, t_start)
            return Response(content=data, media_type="video/mp4",
                            headers={"Content-Disposition": f'attachment; filename="clip_{job_id}_{int(t)}.mp4"'})

    return router
