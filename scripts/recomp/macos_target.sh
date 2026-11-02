# Minimum macOS and iOS of the BDSP app. The one place for the deployment targets.
# Sourced by the build scripts (runtime, NVN layer, guest objects, shader libraries, app bundle, iOS objects, FFmpeg, availability check);
# icon_composer.py reads the values as text. The Xcode project of the iOS app and the inline test projects keep the number as a literal;
# scripts/tests/test_deployment_target.py fails when one of them differs. Changing it rebuilds objects and Metal libraries (their stamps include this file or the flags derived from it).
BDSP_MACOS_MIN=14.0
BDSP_IOS_MIN=17.0
