#ifndef BDSP_SAVE_SNAPSHOT_H
#define BDSP_SAVE_SNAPSHOT_H
#include <stddef.h>
// Call with guest save writes quiesced. Publishes only a fully copied, flushed
// and byte-verified tree. Never removes or changes source files.
int bdsp_save_snapshot(const char *source, const char *directory, char *published, size_t capacity);
int bdsp_save_flush(const char *source);
int bdsp_save_flush_directory(const char *directory);
#endif
