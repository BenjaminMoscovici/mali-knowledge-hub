"""Convert the pinned Apache-licensed StaticEmbedding weights to a compact CPU model."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np


def convert(weights, target, expected_sha256):
    with weights.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise ValueError("Original model checksum mismatch")
        stream.seek(0)
        size, = struct.unpack("<Q", stream.read(8))
        spec = json.loads(stream.read(size))["embedding.weight"]
    if spec["shape"] != [105879, 1024] or spec["dtype"] != "F32":
        raise ValueError("Unexpected model architecture")
    raw = np.memmap(weights, dtype="<f4", mode="r", offset=8 + size, shape=tuple(spec["shape"]))
    data = raw[:, :128]
    scales = np.maximum(np.max(np.abs(data), axis=1), 1e-12) / 127
    np.savez_compressed(target, weights=np.rint(data / scales[:, None]).astype("int8"), scales=scales)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("weights", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("expected_sha256")
    args = parser.parse_args()
    convert(**vars(args))
