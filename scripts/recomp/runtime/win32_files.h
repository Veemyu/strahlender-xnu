#pragma once
#ifdef _WIN32
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include "win32_host.h"

typedef struct _stat64 BdspFileInfo;
typedef struct {
    HANDLE native;
    WIN32_FIND_DATAW found;
    bool first;
    struct BdspDirectoryEntry {
        char d_name[1024];
        unsigned char d_type;
    } entry;
} BdspDirectory;
#define DT_DIR 4
#define DT_REG 8
BdspDirectory *bdsp_win32_opendir(const char *path);
struct BdspDirectoryEntry *bdsp_win32_readdir(BdspDirectory *directory);
int bdsp_win32_closedir(BdspDirectory *directory);
int bdsp_win32_open(const char *path, int flags, ...);
int bdsp_win32_stat(const char *path, BdspFileInfo *info);
int bdsp_win32_mkdir(const char *path);
int bdsp_win32_unlink(const char *path);
int bdsp_win32_rmdir(const char *path);
int bdsp_win32_rename(const char *source, const char *destination);
ssize_t bdsp_win32_pread(int fd, void *data, size_t size, int64_t offset);
ssize_t bdsp_win32_pwrite(int fd, const void *data, size_t size, int64_t offset);
int bdsp_win32_truncate(int fd, int64_t size);

#ifndef BDSP_WIN32_FILES_IMPLEMENTATION
#define DIR BdspDirectory
#define dirent BdspDirectoryEntry
#define opendir bdsp_win32_opendir
#define readdir bdsp_win32_readdir
#define closedir bdsp_win32_closedir
#define open bdsp_win32_open
#define stat(path, info) bdsp_win32_stat(path, info)
#define fstat _fstat64
#define mkdir(path, mode) bdsp_win32_mkdir(path)
#define unlink bdsp_win32_unlink
#define rmdir bdsp_win32_rmdir
#define rename bdsp_win32_rename
#define fopen bdsp_win32_fopen
#define pread bdsp_win32_pread
#define pwrite bdsp_win32_pwrite
#define lseek _lseeki64
#define fsync _commit
#define ftruncate bdsp_win32_truncate
#endif
#else
#include <sys/stat.h>
typedef struct stat BdspFileInfo;
#endif
