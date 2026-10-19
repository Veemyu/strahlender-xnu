using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;
using UnityEngine.Profiling;

namespace Xnu.Probe
{
    // Mess-App MemoryProbe (docs/ipad-messung-1.md): protokolliert Speicher, Bildrate und Thermik
    // und fährt schrittweise Speicherrampen bis kurz vor das Limit. Ausgabe: stderr (devicectl --console)
    // und Datei <persistentDataPath>/memprobe_<variante>_<zeit>.log, jede Zeile sofort auf Platte.
    // Kein Ton, keine Lautstärke; Screen.sleepTimeout gilt nur, solange die App läuft.
    [DisallowMultipleComponent]
    public sealed class MemoryProbe : MonoBehaviour
    {
        public Shader loadShader;

        private const long Mb = ProbeMath.Mb;
        private const long StepBytes = 128 * Mb;
        private const long ReserveBytes = 300 * Mb;
        private const long NativeCapBytes = 6144 * Mb;
        private const long RenderCapBytes = 6144 * Mb;
        private const long ManagedCapBytes = 3072 * Mb;
        private const float PeriodicSeconds = 5f;

        private readonly StringBuilder _sb = new StringBuilder(512);
        private readonly long[] _vm = new long[7];
        private readonly long[] _mtl = new long[3];
        private double[] _frames = new double[20000];
        private FileStream _fs;
        private StreamWriter _writer;
        private string _variant = "unbekannt";
        private Material _load;
        private bool _lowMemory;
        private ulong _seed = 0x9E3779B97F4A7C15UL;
        private string _phase = "start";

        private void Awake()
        {
            DontDestroyOnLoad(gameObject);
            Screen.sleepTimeout = SleepTimeout.NeverSleep;
            var variantAsset = Resources.Load<TextAsset>("MemoryProbeVariant");
            if (variantAsset != null) _variant = variantAsset.text.Trim();
            var fileName = "memprobe_" + _variant.Replace('=', '-').Replace(';', '_') + "_" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + ".log";
            try
            {
                _fs = new FileStream(Path.Combine(Application.persistentDataPath, fileName), FileMode.Create, FileAccess.Write, FileShare.Read);
                _writer = new StreamWriter(_fs, new UTF8Encoding(false));
            }
            catch (Exception e)
            {
                NativeProbe.Log("XNUPROBE|file-open-failed|" + e.Message);
            }
            if (loadShader != null) _load = new Material(loadShader);
            Application.lowMemory += () => { _lowMemory = true; Log("lowMemory", "warning=1"); };
            Log("awake", EnvironmentInfo());
            Log("snapshot.awake", Snapshot());
        }

        private IEnumerator Start()
        {
            StartCoroutine(Periodic());
            yield return null;
            Log("snapshot.firstFrame", Snapshot());

            _phase = "baseline";
            Log("baseline.settings", "vSyncCount=" + QualitySettings.vSyncCount + " targetFrameRate=" + Application.targetFrameRate);
            yield return MeasureFps("baseline_projectdefault", QualitySettings.vSyncCount, Application.targetFrameRate, 8f, 1.5f, 0);
            Log("snapshot.baseline", Snapshot());

            _phase = "fps";
            // (vSyncCount, targetFrameRate): -1 ist der Plattformstandard.
            var matrix = new[] { new[] { 0, -1 }, new[] { 0, 120 }, new[] { 0, 60 }, new[] { 0, 30 }, new[] { 1, -1 }, new[] { 2, -1 }, new[] { 1, 120 },
                                 new[] { 2, 60 }, new[] { 4, 30 }, new[] { 1, 60 }, new[] { 2, 120 } };
            foreach (var c in matrix)
                yield return MeasureFps("fps_idle_v" + c[0] + "_t" + c[1], c[0], c[1], 5f, 1.5f, 0);
            foreach (var c in new[] { new[] { 0, 120 }, new[] { 0, 60 }, new[] { 0, 30 }, new[] { 1, 120 }, new[] { 2, 60 }, new[] { 4, 30 } })
                yield return MeasureFps("fps_light_v" + c[0] + "_t" + c[1], c[0], c[1], 5f, 1.5f, 24);

            if (!_variant.Contains("mode=fps"))
            {
                _phase = "soak";
                yield return Soak(150f, 10f, 160, 0);
                _phase = "soak_full";
                yield return Soak(300f, 20f, 160, Mathf.Max(1, SystemInfo.processorCount - 2));

                QualitySettings.vSyncCount = 0;
                Application.targetFrameRate = 30;

                _phase = "ramp_native";
                yield return Ramp("native", NativeCapBytes, AllocNative);
                _phase = "ramp_render";
                yield return Ramp("render", RenderCapBytes, AllocRender);
                _phase = "ramp_managed";
                yield return Ramp("managed", ManagedCapBytes, AllocManaged);
            }

            _phase = "done";
            for (var i = 0; i < 6; i++)
            {
                yield return new WaitForSeconds(PeriodicSeconds);
            }
            Log("snapshot.final", Snapshot());
            Log("done", "lowMemoryWarning=" + (_lowMemory ? 1 : 0));
            Close();
            Application.Quit();
        }

        private void OnDestroy() => Close();

        private void Close()
        {
            if (_writer == null) return;
            try { _writer.Flush(); _fs.Flush(true); _writer.Dispose(); } catch (Exception) { }
            _writer = null;
        }

        private IEnumerator Periodic()
        {
            while (true)
            {
                yield return new WaitForSecondsRealtime(PeriodicSeconds);
                Log("periodic", Snapshot());
            }
        }

        // ---- Ausgabe -----------------------------------------------------------

        private void Log(string tag, string data)
        {
            var line = "XNUPROBE|" + _variant + "|t=" + Time.realtimeSinceStartup.ToString("F2", CultureInfo.InvariantCulture)
                       + "|" + _phase + "|" + tag + "|" + data;
            NativeProbe.Log(line);
            if (_writer == null) return;
            try { _writer.WriteLine(line); _writer.Flush(); _fs.Flush(true); } catch (Exception) { }
        }

        private static string F(double v) => v.ToString("F1", CultureInfo.InvariantCulture);
        private static string Mib(long bytes) => bytes < 0 ? "-1" : F(bytes / (double)Mb);

        private string EnvironmentInfo()
        {
            _sb.Length = 0;
            _sb.Append("device=").Append(SystemInfo.deviceModel)
              .Append(" os=").Append(SystemInfo.operatingSystem)
              .Append(" unity=").Append(Application.unityVersion)
              .Append(" gfx=").Append(SystemInfo.graphicsDeviceType)
              .Append(" systemMemoryMB=").Append(SystemInfo.systemMemorySize)
              .Append(" physMemMiB=").Append(Mib(NativeProbe.PhysicalMemory()))
              .Append(" graphicsMemoryMB=").Append(SystemInfo.graphicsMemorySize)
              .Append(" screen=").Append(Screen.width).Append('x').Append(Screen.height)
              .Append(" dpi=").Append(F(Screen.dpi))
              .Append(" refreshHz=").Append(F(Screen.currentResolution.refreshRateRatio.value))
              .Append(" maxFps=").Append(NativeProbe.MaxFramesPerSecond())
              .Append(" caDisableMinFrameDurationKey=").Append(NativeProbe.DisableMinFrameDuration())
              .Append(" devBuild=").Append(Debug.isDebugBuild ? 1 : 0)
              .Append(" cpuCores=").Append(SystemInfo.processorCount)
              .Append(" audioListenerVolume=").Append(F(AudioListener.volume))
              .Append(" audioPause=").Append(AudioListener.pause ? 1 : 0);
            return _sb.ToString();
        }

        private string Snapshot()
        {
            NativeProbe.VmInfo(_vm);
            NativeProbe.MetalInfo(_mtl);
            _sb.Length = 0;
            _sb.Append("availMiB=").Append(Mib(NativeProbe.AvailableMemory()))
              .Append(" footprintMiB=").Append(Mib(_vm[0]))
              .Append(" footprintPeakMiB=").Append(Mib(_vm[1]))
              .Append(" internalMiB=").Append(Mib(_vm[2]))
              .Append(" compressedMiB=").Append(Mib(_vm[3]))
              .Append(" residentMiB=").Append(Mib(_vm[4]))
              .Append(" limitRemainingMiB=").Append(Mib(_vm[5]))
              .Append(" virtualMiB=").Append(Mib(_vm[6]))
              .Append(" thermal=").Append(NativeProbe.ThermalState())
              .Append(" lowPower=").Append(NativeProbe.LowPowerMode())
              .Append(" unityAllocMiB=").Append(Mib(Profiler.GetTotalAllocatedMemoryLong()))
              .Append(" unityReservedMiB=").Append(Mib(Profiler.GetTotalReservedMemoryLong()))
              .Append(" monoUsedMiB=").Append(Mib(Profiler.GetMonoUsedSizeLong()))
              .Append(" monoHeapMiB=").Append(Mib(Profiler.GetMonoHeapSizeLong()))
              .Append(" gfxDriverMiB=").Append(Mib(Profiler.GetAllocatedMemoryForGraphicsDriver()))
              .Append(" gcTotalMiB=").Append(Mib(GC.GetTotalMemory(false)))
              .Append(" mtlAllocMiB=").Append(Mib(_mtl[1]))
              .Append(" mtlRecMaxWorkingSetMiB=").Append(Mib(_mtl[0]))
              .Append(" vSync=").Append(QualitySettings.vSyncCount)
              .Append(" target=").Append(Application.targetFrameRate);
            return _sb.ToString();
        }

        // ---- Bildrate ----------------------------------------------------------

        private void DrawLoad(int iterations)
        {
            if (iterations <= 0 || _load == null) return;
            _load.SetFloat("_Iter", iterations);
            Graphics.Blit(Texture2D.whiteTexture, (RenderTexture)null, _load);
        }

        private IEnumerator MeasureFps(string label, int vsync, int target, float seconds, float warmup, int loadIterations)
        {
            QualitySettings.vSyncCount = vsync;
            Application.targetFrameRate = target;
            var n = 0;
            var start = Time.realtimeSinceStartupAsDouble;
            double measuredStart = -1;
            while (true)
            {
                yield return new WaitForEndOfFrame();
                DrawLoad(loadIterations);
                var now = Time.realtimeSinceStartupAsDouble;
                if (now - start >= seconds) break;
                if (now - start < warmup) continue;
                if (measuredStart < 0) measuredStart = now;
                if (n < _frames.Length) _frames[n++] = Time.unscaledDeltaTime;
            }
            var s = ProbeMath.Summarize(_frames, n);
            Log("fps", "label=" + label + " vSync=" + vsync + " target=" + target + " load=" + loadIterations
                       + " frames=" + s.Count + " avgFps=" + F(s.AvgFps) + " minFps=" + F(s.MinFps) + " maxFps=" + F(s.MaxFps)
                       + " p99ms=" + F(s.P99FrameMs) + " maxms=" + F(s.MaxFrameMs)
                       + " wallFps=" + F(n / Math.Max(1e-6, Time.realtimeSinceStartupAsDouble - measuredStart))
                       + " thermal=" + NativeProbe.ThermalState() + " refreshHz=" + F(Screen.currentResolution.refreshRateRatio.value));
        }

        // Dauerlast: misst in Fenstern, damit Drosselung durch Wärme sichtbar wird. Optional mit CPU-Lastthreads.
        private IEnumerator Soak(float totalSeconds, float windowSeconds, int loadIterations, int cpuThreads)
        {
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = 120;
            _stopBurn = false;
            for (var i = 0; i < cpuThreads; i++)
            {
                var t = new System.Threading.Thread(Burn) { IsBackground = true, Name = "probe-burn-" + i };
                t.Start();
            }
            Log("soak.start", "cpuThreads=" + cpuThreads + " " + Snapshot());
            var t0 = Time.realtimeSinceStartupAsDouble;
            var window = 0;
            while (Time.realtimeSinceStartupAsDouble - t0 < totalSeconds)
            {
                var n = 0;
                var ws = Time.realtimeSinceStartupAsDouble;
                while (Time.realtimeSinceStartupAsDouble - ws < windowSeconds)
                {
                    yield return new WaitForEndOfFrame();
                    DrawLoad(loadIterations);
                    if (n < _frames.Length) _frames[n++] = Time.unscaledDeltaTime;
                }
                var s = ProbeMath.Summarize(_frames, n);
                Log("soak.window", "idx=" + window++ + " avgFps=" + F(s.AvgFps) + " minFps=" + F(s.MinFps) + " p99ms=" + F(s.P99FrameMs)
                                   + " " + Snapshot());
            }
            _stopBurn = true;
            Log("soak.end", Snapshot());
        }

        private volatile bool _stopBurn;

        private void Burn()
        {
            double x = 1.0001;
            while (!_stopBurn)
            {
                for (var i = 0; i < 1000000; i++) x = x * 1.0000001 + Math.Sin(x) * 1e-9;
                if (double.IsNaN(x)) x = 1.0;
            }
        }

        // ---- Speicherrampen ----------------------------------------------------

        private readonly List<IntPtr> _native = new List<IntPtr>();
        private readonly List<byte[]> _managed = new List<byte[]>();
        private readonly List<RenderTexture> _render = new List<RenderTexture>();

        private IEnumerator AllocNative()
        {
            var p = Marshal.AllocHGlobal((IntPtr)StepBytes);
            FillNative(p, StepBytes);
            _native.Add(p);
            yield break;
        }

        private IEnumerator AllocManaged()
        {
            var a = new byte[StepBytes];
            FillManaged(a);
            _managed.Add(a);
            yield break;
        }

        // 4096 x 4096 ARGBHalf = 128 MiB, wird einmal beschrieben, damit der Speicher belegt ist.
        private IEnumerator AllocRender()
        {
            var rt = new RenderTexture(4096, 4096, 0, RenderTextureFormat.ARGBHalf) { name = "probe_rt_" + _render.Count };
            rt.Create();
            _render.Add(rt);
            yield return new WaitForEndOfFrame();
            if (_load != null)
            {
                _load.SetFloat("_Iter", 1);
                Graphics.Blit(Texture2D.whiteTexture, rt, _load);
            }
        }

        private unsafe void FillNative(IntPtr p, long bytes)
        {
            var q = (ulong*)p;
            var n = bytes / 8;
            var s = _seed;
            for (long i = 0; i < n; i++)
            {
                s ^= s << 13; s ^= s >> 7; s ^= s << 17;
                q[i] = s;
            }
            _seed = s;
        }

        private unsafe void FillManaged(byte[] a)
        {
            fixed (byte* b = a)
            {
                var q = (ulong*)b;
                var n = a.LongLength / 8;
                var s = _seed;
                for (long i = 0; i < n; i++)
                {
                    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
                    q[i] = s;
                }
                _seed = s;
            }
        }

        private int Held(string kind) => kind == "native" ? _native.Count : kind == "managed" ? _managed.Count : _render.Count;

        private IEnumerator Ramp(string kind, long footprintCap, Func<IEnumerator> alloc)
        {
            Log("ramp.start", "kind=" + kind + " stepMiB=" + (StepBytes / Mb) + " reserveMiB=" + (ReserveBytes / Mb) + " capMiB=" + (footprintCap / Mb) + " " + Snapshot());
            var reason = "unbekannt";
            while (true)
            {
                var avail = NativeProbe.AvailableMemory();
                NativeProbe.VmInfo(_vm);
                if (ProbeMath.ShouldStop(avail, _vm[0], StepBytes, ReserveBytes, footprintCap))
                {
                    reason = avail <= 0 ? "available-unbekannt" : avail - StepBytes < ReserveBytes ? "reserve" : "footprint-cap";
                    break;
                }
                yield return alloc();
                yield return null;
                Log("ramp.step", "kind=" + kind + " held=" + Held(kind) + " heldMiB=" + (Held(kind) * (StepBytes / Mb)) + " " + Snapshot());
                yield return new WaitForSecondsRealtime(0.15f);
            }
            Log("ramp.stop", "kind=" + kind + " reason=" + reason + " held=" + Held(kind) + " heldMiB=" + (Held(kind) * (StepBytes / Mb)) + " " + Snapshot());

            yield return new WaitForSecondsRealtime(1f);
            Log("ramp.hold", "kind=" + kind + " " + Snapshot());

            foreach (var p in _native) Marshal.FreeHGlobal(p);
            _native.Clear();
            foreach (var rt in _render) { rt.Release(); Destroy(rt); }
            _render.Clear();
            _managed.Clear();
            yield return null;
            GC.Collect();
            yield return Resources.UnloadUnusedAssets();
            yield return new WaitForSecondsRealtime(3f);
            Log("ramp.released", "kind=" + kind + " " + Snapshot());
        }
    }
}
