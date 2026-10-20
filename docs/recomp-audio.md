# Native recompilation audio

Updated: 2026-10-20. Native runtime only; the deprecated Unity rebuild is untouched.
Measurements and generated artifacts stay under `work/`.

## Result

The guest already mixes PCM16 and submits nonempty buffers through IAudioOut.
macOS and iPadOS now play these buffers using Audio Queue Services. The user
confirmed clean sound on both devices. This covers sampled startup, title, and
field scenes, not battles, the ending, or a complete uninterrupted intro.

No custom host Wwise mixer, audio renderer, or Opus decoder was needed for this
first output path. Access to an audren device service alone does not establish
that the guest uses its renderer.

## Evidence

IPC requests are counted once in `ipc.c:ipc_count`; `ipc_note(..., 0)` does not
increment them again.

| Request | Mac variant B | iPad | Mac Pokécenter |
|---|---:|---:|---:|
| audout:u:1, open | 2 | 2 | 2 |
| IAudioOut:7, append | 6,201 | 5,390 | 12,378 |
| IAudioOut:8, released buffers | 69,199 | 14,725 | 34,110 |
| audren:u:4, device service | 3 | 3 | 3 |
| hwopus:1, work-buffer size | 10 | 10 | 10 |
| audren:u:0, open renderer | Not recorded | Not recorded | Not recorded |
| IHardwareOpusDecoder, decode | Not recorded | Not recorded | Not recorded |

Sources: `work/builds/mac-b-run9.log`,
`work/builds/ipad-recomp-20261020-134156.log`, and
`work/recomp/qa/pokecenter-20261019-164824-a4/log_p1.txt`.
These runs differ in duration and build; absolute counts are not performance
comparisons. No audin:u request appears in their summary lines.
The original interpretation was that Wwise code in the guest was likely doing
the mixing in these scenes; service counts alone do not establish that.

A header inventory limited to
`work/romfs/Data/StreamingAssets/Audio/GeneratedSoundBanks/Switch` found
3,241 RIFF/WAVE WEM files with format tag 0xFFFF: 2,859 mono and 382 stereo.
Sample-rate counts: 32,000 Hz (2,337), 48,000 (371), 36,000 (344), 24,000 (162),
6,000 (8), 44,100 (7), 16,000 (5), 8,000 (4), and 12,000 (3).
There are 696 BKHD banks, version 135. The inventory associates 0xFFFF with
Wwise Vorbis, but the tag alone does not prove successful decoding. Host-side
bank decoding or replacement is not part of the implementation.

`BDSP_AUDIO_PROBE=1` logs descriptor/sample statistics, never audio samples.
The initial probe on Mac variant A (`work/builds/audio-probe-mac.log`) ran
before host playback was implemented. It observed negotiated PCM16, 48 kHz,
stereo, 4,096-byte buffers, offset zero: 1,024 frames or 21.333 ms.
One stream initially contained silence. Another had 214,918 nonzero samples
out of 1,048,576 by buffer 512, peak magnitude 2,666/32,768.
The local inventory document, `docs/daten-inventar.md`, labels 0xFFFF as
Wwise Vorbis. In the original check, `ffprobe` recognized the inspected WEM
container data but did not name a decoder; the format tag alone does not show
that the file can be decoded successfully.

All 18 WebM files under `work/romfs/Data/StreamingAssets/Movie/dia` contain only
one VP8 video stream, no audio. The German intro lasts 106.067 seconds.
They were checked with
`ffprobe -show_entries stream=codec_type,codec_name`. The current movie HLE
considers video streams only. Adding FFmpeg audio decoding would not create a
missing track. The intro's Wwise event mapping and measured audiovisual
synchronization remain unresolved; brief listening checks that skipped the intro
do not replace a full movie playback or a sync measurement.

## Output, threads, and synchronization

`audio_output.c/.h` provides a small C interface to Apple's Audio Queue Services.
Each stream has eight reusable host buffers, each capped at 25 ms, bounding
queued host PCM to about 200 ms. PCM is copied from guest memory. Apple's output
callback only releases host buffers; it does not access guest memory or call
kernel/IPC services. Device playback is asynchronous, not performed on the UI
main thread. The existing service timer controls guest buffer release separately.

Historical implementation record: the macOS backend added bounded queuing,
start/stop/close, volume control, and silent fallback when no device is
available. The iPadOS backend added the same output path and an audio session;
the library and app built and a targeted device run passed without startup
loops. These checks did not cover real interruptions or device changes, which
remain open below.

A full host queue drops and counts the new host copy, without accelerating
guest release. A callback does not establish that the corresponding buffer has
already become audible. See Apple's
[Audio Queue Services](https://developer.apple.com/documentation/audiotoolbox/audio-queue-services)
and [output callback](https://developer.apple.com/documentation/audiotoolbox/audioqueueoutputcallback).

`services_audio.c` validates descriptor capacity and offset, translates addresses
through G2H, copies PCM, and disposes host output when its service object closes.
The timer cannot concurrently read a closed object; all eight registration slots
can be reused. Negotiated sample rate/channel count determine release duration.
The existing 5 ms safety margin, event signaling, and zero tag for an empty
released list are preserved. Immediate release after copying would risk the
previous Wwise lockup.

The original implementation checklist also called for start/stop and repeated
open/close without resource loss, queue overflow and device failure without a
Wwise hang, and title/field/Pokécenter playback without hangs or unbounded
latency. The synthetic harness now covers repeated open/close and queue bounds;
manual device-failure and long-latency checks remain open below. Silent output
continues to service the existing timed guest releases.

iPad `app.m` configures AVAudioSession for playback. Backgrounding or audio
interruption stops and discards host buffers; returning resumes requested output.
Frameworks are supplied by `deploy_ios.sh`, without editing the personal signing
project or accepted shader gate.

Linux remains silent by agreement. A later SDL3 backend can reuse this PCM
interface. Renderer/Opus implementation should be driven by observed calls, not
assumed prerequisites. LAS runtime audio
(`research/LASRecomp/runtime/services/audio.c`) is a reference for PCM queuing,
not a mixer imported into this implementation.

## Tests and listening checks

The synthetic C service harness checks delayed release, empty zero tags,
mono/24-kHz pacing, the minimum duration, offsets, bounds, a full guest queue,
and 24 open/close cycles (`scripts/tests/test_recomp_audio.py` exercises the real
service implementation against a simulated host and kernel). At audio
completion the full suite passed:
309 tests, three skipped; repository checks passed.

Mac: `work/builds/audio-output-mac.log`, 45 seconds, clean sound confirmed.
Two streams; one dropped host copy on the initially silent stream during startup,
with no subsequent counter growth; no drops on the nonzero stream.

iPad: exactly one 60-second run,
`work/builds/ipad-recomp-20261020-204619.log`. Final 60 fps, 39 guest threads,
2,202 MiB footprint, thermalState 0. Neither stream dropped host buffers.
The second stream had 4,390,474 nonzero samples out of 5,242,880 at buffer 2,560,
peak 7,002. Clean sound confirmed. The unchanged gate built 2,845 pipelines
in 362 ms with a warm cache. Signal 15 came from the agreed run time limit.

Device saves were backed up to `work/recomp/audio/ipad-save-before-audio`.
RomFS and saves survived installation; SaveData.bin, Backup.bin, and user_id.hex
were compared unchanged, so no replacement was necessary.

| Environment variable | Effect |
|---|---|
| BDSP_AUDIO=0 | Silent host output; timed guest release continues |
| BDSP_AUDIO_GAIN=0.10 | 10% app volume; range 0–1, default 1; no system-volume changes |
| BDSP_AUDIO_PROBE=1 | Numeric PCM/queue counters, without storing samples |

Both listening checks used gain 0.10. Set variables when directly launching the
Mac binary, or via RUN_ENV JSON for iPad.

## Remaining checks

Full intro audio and synchronization; long sessions, battles, and ending paths;
mapping the two output objects; real iPad interruptions/backgrounding and device
changes; queue behavior during device failure. Queues are not yet recreated
after a system audio-service restart. Linux output is deferred.

Historical planning note: before implementation, the rough effort estimate was
one workday for macOS including lifecycle and checks, plus another workday for
iPadOS including a device check. This was an estimate, not a measurement. A
custom audio renderer with voices, effects, and Opus was considered a separate,
substantially larger project and was not established as a prerequisite. The
original Linux direction was SDL3 behind this PCM interface, avoiding a direct
PulseAudio/PipeWire client if SDL can open the device.

The original detailed German report is preserved in
[recomp-audio.de.md](recomp-audio.de.md).
