"""Generated media for tests that require neither bank data nor model weights."""
import cv2
import numpy as np
import pytest


@pytest.fixture
def synthetic_video(tmp_path):
    path = tmp_path / "synthetic.mov"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (96, 64))
    assert writer.isOpened(), "OpenCV needs a working mp4v encoder for these tests"
    try:
        for i in range(20):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[:, :, 0] = np.arange(96, dtype=np.uint8)
            frame[:, :, 1] = 40 + i * 8
            frame[8:24, i * 3:i * 3 + 16, 2] = 220
            writer.write(frame)
    finally:
        writer.release()
    return path
