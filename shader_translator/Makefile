ifeq ($(origin CC),default)
CC := clang
endif
CFLAGS  ?= -O2
WARN    := -Wall -Wextra -Wno-unused-parameter -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable -Wno-deprecated-declarations
CFLAGS  += -std=gnu11 $(WARN)
BUILD   := build
SRC     := translate.c container.c
BIN     := $(BUILD)/maxwell2msl

.PHONY: all test clean asan
all: $(BIN)

$(BIN): main.c $(SRC) shader.h container.h | $(BUILD)
	$(CC) $(CFLAGS) -o $@ main.c $(SRC) -lm

$(BUILD):
	mkdir -p $(BUILD)

# Unit tests (C, synthetic shaders) and CLI tests (Python, synthetic files); no game data needed.
$(BUILD)/test_translate: tests/test_translate.c $(SRC) shader.h container.h | $(BUILD)
	$(CC) $(CFLAGS) -I. -o $@ tests/test_translate.c $(SRC) -lm

test: $(BIN) $(BUILD)/test_translate
	$(BUILD)/test_translate
	python3 tests/test_cli.py
	python3 tests/test_report.py

# Same binary with AddressSanitizer/UBSan, for running the survey over a large corpus.
asan: main.c $(SRC) shader.h container.h | $(BUILD)
	$(CC) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -std=gnu11 $(WARN) -o $(BUILD)/maxwell2msl-asan main.c $(SRC) -lm

clean:
	rm -rf $(BUILD)
