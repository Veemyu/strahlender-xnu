using System.Runtime.InteropServices;
using UnityEngine;

namespace Xnu.Probe
{
    // Brücke zu Assets/Plugins/iOS/XnuMemoryProbe.m. Außerhalb von iOS liefern alle Aufrufe -1.
    public static class NativeProbe
    {
#if UNITY_IOS && !UNITY_EDITOR
        [DllImport("__Internal")] private static extern long XnuProbe_AvailableMemory();
        [DllImport("__Internal")] private static extern int XnuProbe_VmInfo([Out] long[] values);
        [DllImport("__Internal")] private static extern int XnuProbe_ThermalState();
        [DllImport("__Internal")] private static extern int XnuProbe_LowPowerMode();
        [DllImport("__Internal")] private static extern long XnuProbe_PhysicalMemory();
        [DllImport("__Internal")] private static extern int XnuProbe_MaxFramesPerSecond();
        [DllImport("__Internal")] private static extern int XnuProbe_DisableMinFrameDuration();
        [DllImport("__Internal")] private static extern int XnuProbe_MetalInfo([Out] long[] values);
        [DllImport("__Internal")] private static extern void XnuProbe_Log(string line);

        public static long AvailableMemory() => XnuProbe_AvailableMemory();
        public static bool VmInfo(long[] values) => XnuProbe_VmInfo(values) == 0;
        public static int ThermalState() => XnuProbe_ThermalState();
        public static int LowPowerMode() => XnuProbe_LowPowerMode();
        public static long PhysicalMemory() => XnuProbe_PhysicalMemory();
        public static int MaxFramesPerSecond() => XnuProbe_MaxFramesPerSecond();
        public static int DisableMinFrameDuration() => XnuProbe_DisableMinFrameDuration();
        public static bool MetalInfo(long[] values) => XnuProbe_MetalInfo(values) == 0;
        public static void Log(string line) => XnuProbe_Log(line);
#else
        public static long AvailableMemory() => -1;
        public static bool VmInfo(long[] values) { for (var i = 0; i < values.Length; i++) values[i] = -1; return false; }
        public static int ThermalState() => -1;
        public static int LowPowerMode() => -1;
        public static long PhysicalMemory() => SystemInfo.systemMemorySize * 1024L * 1024L;
        public static int MaxFramesPerSecond() => -1;
        public static int DisableMinFrameDuration() => -1;
        public static bool MetalInfo(long[] values) { for (var i = 0; i < values.Length; i++) values[i] = -1; return false; }
        public static void Log(string line) => Debug.Log(line);
#endif
    }
}
