# Guest base address of each module (memory model A). Sourced by gen_all.sh, rt-bdsp/mkimages.sh and
# linux/local/common.sh: the generated C and the memory images must use the same addresses.
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; subsdk1) echo 0x7005708000;; *) return 2;; esac; }
