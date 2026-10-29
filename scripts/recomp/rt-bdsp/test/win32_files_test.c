#include <assert.h>
#include <errno.h>
#include <string.h>
#include "win32_files.h"
#include <winioctl.h>

int main(void) {
    const char *directory = "files-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e";
    const char *source = "files-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\\source.bin";
    const char *target = "files-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\\target.bin";
    assert(mkdir(directory, 0700) == 0);
    int file = open(source, O_CREAT | O_EXCL | O_RDWR, 0600);
    assert(file >= 0);
    const unsigned char bytes[] = {0x0a, 0x0d, 0x1a, 0xff};
    assert(write(file, bytes, sizeof bytes) == sizeof bytes);
    assert(lseek(file, 2, SEEK_SET) == 2);
    unsigned char buffer[4];
    assert(pread(file, buffer, sizeof buffer, 0) == sizeof buffer);
    assert(!memcmp(buffer, bytes, sizeof bytes));
    assert(lseek(file, 0, SEEK_CUR) == 2);
    void *guest = NULL;
    assert(bdsp_win32_reserve(NULL, 0x20000, 0x10000, &guest));
    unsigned char *guest_buffer = (unsigned char *)guest + 0x10000;
    assert(pread(file, guest_buffer, sizeof buffer, 0) == sizeof buffer);
    assert(!memcmp(guest_buffer, bytes, sizeof bytes));
    assert(pread(file, guest, sizeof buffer, 0) == -1 && errno == EFAULT);
    assert(bdsp_win32_release());
    assert(pread(file, buffer, sizeof buffer, 100) == 0);
    assert(pread(file, buffer, 1, -1) == -1 && errno == EINVAL);
    assert(pwrite(file, bytes, sizeof bytes, INT64_MAX - 1) == -1 && errno == EINVAL);
    DWORD returned;
    assert(DeviceIoControl((HANDLE)_get_osfhandle(file), FSCTL_SET_SPARSE,
                           NULL, 0, NULL, 0, &returned, NULL));
    const int64_t large = INT64_C(0x100000010);
    assert(pwrite(file, bytes, sizeof bytes, large) == sizeof bytes);
    assert(lseek(file, 0, SEEK_CUR) == 2);
    assert(pread(file, buffer, sizeof buffer, large) == sizeof buffer);
    assert(!memcmp(buffer, bytes, sizeof bytes));
    BdspFileInfo info;
    assert(fstat(file, &info) == 0 && info.st_size == large + sizeof bytes);
    assert(stat(source, &info) == 0 && info.st_size == large + sizeof bytes);
    assert(ftruncate(file, 4) == 0);
    assert(fsync(file) == 0);
    assert(close(file) == 0);
    file = open(target, O_CREAT | O_EXCL | O_WRONLY, 0600);
    assert(file >= 0 && close(file) == 0);
    assert(rename(source, target) == 0);
    assert(stat(target, &info) == 0 && info.st_size == sizeof bytes);
    assert(stat("\xff", &info) == -1 && errno == EILSEQ);
    DIR *dir = opendir(".");
    assert(dir);
    bool found = false;
    struct dirent *entry;
    while ((entry = readdir(dir)))
        if (!strcmp(entry->d_name, directory)) { assert(entry->d_type == DT_DIR); found = true; }
    assert(found && closedir(dir) == 0);
    assert(unlink(target) == 0 && rmdir(directory) == 0);
    puts("UTF-8 files, binary I/O, 64-bit offsets and atomic replacement passed");
    return 0;
}
