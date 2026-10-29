#ifdef _WIN32
#define BDSP_WIN32_FILES_IMPLEMENTATION
#include "win32_files.h"
#include <errno.h>
#include <direct.h>
#include <limits.h>
#include <stdarg.h>
#include <stdlib.h>

static void file_error(DWORD error) {
    switch (error) {
    case ERROR_FILE_NOT_FOUND: case ERROR_PATH_NOT_FOUND: errno = ENOENT; break;
    case ERROR_ACCESS_DENIED: case ERROR_SHARING_VIOLATION: errno = EACCES; break;
    case ERROR_FILE_EXISTS: case ERROR_ALREADY_EXISTS: errno = EEXIST; break;
    case ERROR_DIRECTORY: errno = ENOTDIR; break;
    case ERROR_DIR_NOT_EMPTY: errno = ENOTEMPTY; break;
    case ERROR_DISK_FULL: errno = ENOSPC; break;
    case ERROR_INVALID_HANDLE: errno = EBADF; break;
    case ERROR_INVALID_PARAMETER: errno = EINVAL; break;
    case ERROR_NOT_ENOUGH_MEMORY: case ERROR_OUTOFMEMORY: errno = ENOMEM; break;
    default: errno = EIO; break;
    }
}

BdspDirectory *bdsp_win32_opendir(const char *path) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return NULL;
    BdspDirectory *directory = calloc(1, sizeof *directory);
    if (!directory) { free(wide); errno = ENOMEM; return NULL; }
    DWORD attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        DWORD error = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : ERROR_DIRECTORY;
        free(wide); free(directory); file_error(error); return NULL;
    }
    size_t length = wcslen(wide);
    wchar_t *pattern = malloc((length + 3) * sizeof *pattern);
    if (!pattern) { free(wide); free(directory); errno = ENOMEM; return NULL; }
    memcpy(pattern, wide, length * sizeof *pattern);
    memcpy(pattern + length, L"\\*", 3 * sizeof *pattern);
    directory->native = FindFirstFileW(pattern, &directory->found);
    DWORD error = GetLastError();
    free(pattern);
    free(wide);
    if (directory->native == INVALID_HANDLE_VALUE) {
        free(directory); file_error(error); return NULL;
    }
    directory->first = true;
    return directory;
}

struct BdspDirectoryEntry *bdsp_win32_readdir(BdspDirectory *directory) {
    if (!directory->first && !FindNextFileW(directory->native, &directory->found)) {
        DWORD error = GetLastError();
        if (error == ERROR_NO_MORE_FILES) errno = 0; else file_error(error);
        return NULL;
    }
    directory->first = false;
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, directory->found.cFileName, -1,
                            directory->entry.d_name, sizeof directory->entry.d_name, NULL, NULL)) {
        errno = EILSEQ;
        return NULL;
    }
    directory->entry.d_type = directory->found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY ? DT_DIR : DT_REG;
    return &directory->entry;
}

int bdsp_win32_closedir(BdspDirectory *directory) {
    BOOL success = FindClose(directory->native);
    DWORD error = GetLastError();
    free(directory);
    if (!success) { file_error(error); return -1; }
    return 0;
}

int bdsp_win32_open(const char *path, int flags, ...) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return -1;
    int mode = 0;
    if (flags & O_CREAT) {
        va_list arguments;
        va_start(arguments, flags);
        mode = va_arg(arguments, int);
        va_end(arguments);
    }
    int result = _wopen(wide, flags | O_BINARY, mode), error = errno;
    free(wide);
    errno = error;
    return result;
}

int bdsp_win32_stat(const char *path, BdspFileInfo *info) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return -1;
    int result = _wstat64(wide, info), error = errno;
    free(wide); errno = error;
    return result;
}

int bdsp_win32_mkdir(const char *path) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return -1;
    int result = _wmkdir(wide), error = errno;
    free(wide); errno = error;
    return result;
}
int bdsp_win32_unlink(const char *path) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return -1;
    int result = _wunlink(wide), error = errno;
    free(wide); errno = error;
    return result;
}
int bdsp_win32_rmdir(const char *path) {
    wchar_t *wide = bdsp_win32_widen(path);
    if (!wide) return -1;
    int result = _wrmdir(wide), error = errno;
    free(wide); errno = error;
    return result;
}
int bdsp_win32_rename(const char *source, const char *destination) {
    wchar_t *from = bdsp_win32_widen(source), *to = bdsp_win32_widen(destination);
    if (!from || !to) { free(from); free(to); return -1; }
    // Replace an existing safety backup atomically on the same volume.
    BOOL success = MoveFileExW(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    DWORD error = GetLastError();
    free(from); free(to);
    if (success) return 0;
    file_error(error);
    return -1;
}

static ssize_t positional_io(int fd, void *data, size_t size, int64_t offset, bool write) {
    if (offset < 0 || size > INT_MAX || size > (uint64_t)(INT64_MAX - offset)) {
        errno = EINVAL;
        return -1;
    }
    if (!write && !bdsp_win32_prepare_write(data, size)) { errno = EFAULT; return -1; }
    HANDLE original = (HANDLE)_get_osfhandle(fd);
    if (original == INVALID_HANDLE_VALUE) { errno = EBADF; return -1; }
    // An independent overlapped file object preserves the CRT descriptor's position.
    HANDLE file = ReOpenFile(original, write ? GENERIC_WRITE : GENERIC_READ,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_FLAG_OVERLAPPED);
    if (file == INVALID_HANDLE_VALUE) { file_error(GetLastError()); return -1; }
    OVERLAPPED operation = {0};
    operation.Offset = (DWORD)(uint64_t)offset;
    operation.OffsetHigh = (DWORD)((uint64_t)offset >> 32);
    operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!operation.hEvent) {
        DWORD error = GetLastError(); CloseHandle(file); file_error(error); return -1;
    }
    DWORD transferred = 0;
    BOOL success = write ? WriteFile(file, data, (DWORD)size, &transferred, &operation) :
                           ReadFile(file, data, (DWORD)size, &transferred, &operation);
    DWORD error = success ? ERROR_SUCCESS : GetLastError();
    if (!success && error == ERROR_IO_PENDING) {
        success = GetOverlappedResult(file, &operation, &transferred, TRUE);
        error = success ? ERROR_SUCCESS : GetLastError();
    }
    CloseHandle(operation.hEvent);
    CloseHandle(file);
    if (!success && error != ERROR_HANDLE_EOF) { file_error(error); return -1; }
    return (ssize_t)transferred;
}
ssize_t bdsp_win32_pread(int fd, void *data, size_t size, int64_t offset) {
    return positional_io(fd, data, size, offset, false);
}
ssize_t bdsp_win32_pwrite(int fd, const void *data, size_t size, int64_t offset) {
    return positional_io(fd, (void *)data, size, offset, true);
}
int bdsp_win32_truncate(int fd, int64_t size) {
    if (size < 0) { errno = EINVAL; return -1; }
    errno_t result = _chsize_s(fd, size);
    if (result) { errno = result; return -1; }
    return 0;
}
#endif
