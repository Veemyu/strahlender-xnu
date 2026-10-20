# Gemeinsame Compiler-Flags der NVN-Schicht (per source eingebunden von build_nvn.sh und ios/build_rt32.sh).
# Plattformspezifische Defines (BDSP_IOS, BDSP_REBASE32, BDSP_STUB) stehen im jeweiligen Skript.
BDSP_OPT="-O1 -g"
BDSP_NOWARN="-w"
BDSP_WARN_GLUE="-Wall -Wextra -Wno-unused-parameter"
