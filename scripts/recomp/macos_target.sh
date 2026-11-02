# Minimum macOS of the BDSP app. The one place for the deployment target.
# Sourced by the build scripts (runtime, NVN layer, guest objects, shader libraries, app bundle); icon_composer.py reads the
# value as text. Changing it rebuilds objects and Metal libraries (their stamps include this file or the flags derived from it).
BDSP_MACOS_MIN=14.0
