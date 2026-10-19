// Messfunktionen für die Mess-App MemoryProbe (docs/ipad-messung-1.md). Eigener Code.
// Liest nur Systemzähler; keine Audio-, Display- oder Lautstärke-Zugriffe.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <UIKit/UIKit.h>
#import <os/proc.h>
#include <mach/mach.h>
#include <stdio.h>

// Verbleibender Speicher bis zum Limit des Prozesses (Bytes), 0 wenn nicht ermittelbar.
long long XnuProbe_AvailableMemory(void)
{
    return (long long)os_proc_available_memory();
}

// out[0] phys_footprint, [1] Spitzenwert des Footprints, [2] internal, [3] compressed,
// [4] resident_size, [5] limit_bytes_remaining, [6] virtual_size. Rückgabe 0 bei Erfolg.
int XnuProbe_VmInfo(long long *out)
{
    task_vm_info_data_t info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    kern_return_t kr = task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count);
    if (kr != KERN_SUCCESS) return (int)kr;
    out[0] = (long long)info.phys_footprint;
    out[1] = (long long)info.ledger_phys_footprint_peak;
    out[2] = (long long)info.internal;
    out[3] = (long long)info.compressed;
    out[4] = (long long)info.resident_size;
    out[5] = (long long)info.limit_bytes_remaining;
    out[6] = (long long)info.virtual_size;
    return 0;
}

// 0 nominal, 1 fair, 2 serious, 3 critical.
int XnuProbe_ThermalState(void)
{
    return (int)[NSProcessInfo processInfo].thermalState;
}

int XnuProbe_LowPowerMode(void)
{
    return [NSProcessInfo processInfo].lowPowerModeEnabled ? 1 : 0;
}

long long XnuProbe_PhysicalMemory(void)
{
    return (long long)[NSProcessInfo processInfo].physicalMemory;
}

int XnuProbe_MaxFramesPerSecond(void)
{
    return (int)[UIScreen mainScreen].maximumFramesPerSecond;
}

// Wert von CADisableMinimumFrameDurationOnPhone in der Info.plist: 1 wahr, 0 falsch, -1 fehlt.
int XnuProbe_DisableMinFrameDuration(void)
{
    id v = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"CADisableMinimumFrameDurationOnPhone"];
    if (v == nil) return -1;
    return [v boolValue] ? 1 : 0;
}

// out[0] recommendedMaxWorkingSetSize, [1] currentAllocatedSize, [2] hasUnifiedMemory.
int XnuProbe_MetalInfo(long long *out)
{
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    if (dev == nil) return -1;
    out[0] = (long long)dev.recommendedMaxWorkingSetSize;
    out[1] = (long long)dev.currentAllocatedSize;
    out[2] = dev.hasUnifiedMemory ? 1 : 0;
    return 0;
}

// Zeile für `devicectl --console` (stderr).
void XnuProbe_Log(const char *line)
{
    fputs(line, stderr);
    fputc('\n', stderr);
    fflush(stderr);
}
