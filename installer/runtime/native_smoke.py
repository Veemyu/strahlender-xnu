"""Check shipped native assets without importing the removed generator bindings."""
import ctypes
import importlib.util
from pathlib import Path
import sys
import lz4.block
from PIL import Image


def main():
    payload = b"native runtime smoke test" * 8
    assert lz4.block.decompress(lz4.block.compress(payload)) == payload
    spec = importlib.util.find_spec("unicorn")
    assert spec and spec.submodule_search_locations
    root = Path(next(iter(spec.submodule_search_locations)))
    assert (root / "include/unicorn/unicorn.h").is_file()
    filenames = ("unicorn.dll", "libunicorn.dll") if sys.platform == "win32" else ("libunicorn.2.dylib",) if sys.platform == "darwin" else ("libunicorn.so.2",)
    filename = next(name for name in filenames if (root / "lib" / name).is_file())
    library = ctypes.CDLL(str(root / "lib" / filename))
    library.uc_version.argtypes = [ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    library.uc_version.restype = ctypes.c_uint
    major, minor = ctypes.c_uint(), ctypes.c_uint()
    version = library.uc_version(ctypes.byref(major), ctypes.byref(minor))
    assert (major.value, minor.value, (version >> 8) & 255) == (2, 1, 4)
    library.uc_open.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    library.uc_open.restype = ctypes.c_int
    library.uc_close.argtypes = [ctypes.c_void_p]
    library.uc_close.restype = ctypes.c_int
    engine = ctypes.c_void_p()
    assert library.uc_open(2, 0, ctypes.byref(engine)) == 0  # UC_ARCH_ARM64, UC_MODE_ARM
    assert library.uc_close(engine) == 0
    icon = Image.new("RGB", (2, 2), (17, 23, 31))
    assert icon.getpixel((1, 1)) == (17, 23, 31)
    print("Native assets: LZ4, Unicorn 2.1.4 C engine/headers and Pillow OK")


if __name__ == "__main__":
    main()
