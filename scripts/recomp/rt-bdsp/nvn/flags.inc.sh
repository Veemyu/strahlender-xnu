# Shared compiler flags of the NVN layer (sourced by build_nvn.sh and ios/build_rt32.sh).
# Platform-specific defines (BDSP_IOS, BDSP_REBASE32, BDSP_STUB) are in the respective script.
BDSP_OPT="-O1 -g"
BDSP_PATHMAP="-ffile-prefix-map=$PWD=."
BDSP_NOWARN="-w"
BDSP_WARN_GLUE="-Wall -Wextra -Wno-unused-parameter"
