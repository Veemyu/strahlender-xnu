"""Testhilfe: schreibt synthetische UnityFS-Bundles (v7). Keine Spieldaten."""
import struct

try:
    import lz4.block as lz4block
except ImportError:  # pragma: no cover
    lz4block = None


def make_bundle(path, files, block_size=64, compress=True, platform_nodes=None):
    """UnityFS v7: files = [(Name, Bytes)]; Blockinfo und Blöcke LZ4 (oder unkomprimiert)."""
    stream = b"".join(data for _, data in files)
    nodes, off = [], 0
    for name, data in files:
        nodes.append((off, len(data), 4, name))
        off += len(data)
    blocks, parts = [], []
    for i in range(0, len(stream), block_size):
        chunk = stream[i:i + block_size]
        if compress:
            comp = lz4block.compress(chunk, mode="high_compression", store_size=False)
            if len(comp) < len(chunk):
                blocks.append((len(chunk), len(comp), 3)); parts.append(comp); continue
        blocks.append((len(chunk), len(chunk), 0)); parts.append(chunk)
    info = bytes(16) + struct.pack(">i", len(blocks))
    for u, c, fl in blocks:
        info += struct.pack(">IIH", u, c, fl)
    info += struct.pack(">i", len(nodes))
    for o, s, fl, name in nodes:
        info += struct.pack(">QQI", o, s, fl) + name.encode() + b"\0"
    cinfo = lz4block.compress(info, mode="high_compression", store_size=False) if compress else info
    head = b"UnityFS\0" + struct.pack(">I", 7) + b"5.x.x\0" + b"2019.4.27f1\0"
    size_pos = len(head)
    head += struct.pack(">QIII", 0, len(cinfo), len(info), 0x43 if compress else 0x40)
    head += b"\0" * ((-len(head)) % 16)
    data = b"".join(parts)
    head = head[:size_pos] + struct.pack(">Q", len(head) + len(cinfo) + len(data)) + head[size_pos + 8:]
    with open(path, "wb") as f:
        f.write(head + cinfo + data)
