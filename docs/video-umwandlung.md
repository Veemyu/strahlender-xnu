# Video conversion

## Sources and measurement method

All 18 WebM files under `work/romfs/Data/StreamingAssets/Movie` were inspected with ffprobe. All use VP8, 1280×720, 30 fps, and `yuv420p`; none contains an audio track. Bitrates are mean container bitrates reported by ffprobe. Sizes are in MiB (1 MiB = 1,048,576 bytes).

| File (relative to Movie/) | Codec | Resolution | FPS | Pixel format | Duration (s) | Bitrate (kbit/s) | Size (MiB) | Audio |
|---|---:|---:|---:|---|---:|---:|---:|---|
| dia/Ending/movie_dia_ed_female_00.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 993.1 | 35.52 | no |
| dia/Ending/movie_dia_ed_female_01.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.1 | 35.41 | no |
| dia/Ending/movie_dia_ed_female_02.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.6 | 35.43 | no |
| dia/Ending/movie_dia_ed_female_03.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 991.5 | 35.46 | no |
| dia/Ending/movie_dia_ed_male_00.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.3 | 35.42 | no |
| dia/Ending/movie_dia_ed_male_01.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 989.9 | 35.40 | no |
| dia/Ending/movie_dia_ed_male_02.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 989.6 | 35.39 | no |
| dia/Ending/movie_dia_ed_male_03.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.5 | 35.42 | no |
| dia/Opening/movie_dia_en_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1500.1 | 18.97 | no |
| dia/Opening/movie_dia_fr_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1499.2 | 18.96 | no |
| dia/Opening/movie_dia_ge_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1496.7 | 18.93 | no |
| dia/Opening/movie_dia_it_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1495.3 | 18.91 | no |
| dia/Opening/movie_dia_jp_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1559.4 | 19.72 | no |
| dia/Opening/movie_dia_ko_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1553.3 | 19.64 | no |
| dia/Opening/movie_dia_op_loop.webm | VP8 | 1280×720 | 30 | yuv420p | 4.000 | 1934.3 | 0.92 | no |
| dia/Opening/movie_dia_si_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1502.0 | 18.99 | no |
| dia/Opening/movie_dia_sp_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1498.6 | 18.95 | no |
| dia/Opening/movie_dia_tr_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1503.0 | 19.00 | no |

On the Mac, `libx265`, `hevc_videotoolbox`, `libx264`, and `h264_videotoolbox` were available. Tests compared the four-second loop and a 300-second ending video. Wall-clock time covers the entire ffmpeg invocation. SSIM is the overall score; PSNR is the mean. Each reference was the same decoded source. Nothing was played or visually assessed. Every command excluded audio with `-an`.

| Source | Variant | Output (MiB) | Encoding (s) | SSIM | PSNR (dB) |
|---|---|---:|---:|---:|---:|
| Loop, 4 s | libx265 CRF 14 | 2.10 | 3.49 | 0.982360 | 36.60 |
| Loop, 4 s | libx265 CRF 18 | 1.29 | 2.38 | 0.980649 | 36.54 |
| Loop, 4 s | libx264 CRF 14 | 2.45 | 0.99 | 0.982428 | 36.57 |
| Loop, 4 s | hevc_videotoolbox `-q:v 75` | 1.48 | 0.69 | 0.979559 | 36.50 |
| Ending, 300 s | libx265 CRF 14 | 99.19 | 133.43 | 0.988261 | 40.68 |
| Ending, 300 s | libx265 CRF 18 | 50.24 | 99.06 | 0.986286 | 40.50 |
| Ending, 300 s | libx264 CRF 14 | 138.08 | 54.38 | 0.988603 | 40.68 |
| Ending, 300 s | hevc_videotoolbox `-q:v 75` | 62.98 | 29.15 | 0.982772 | 40.20 |
| Ending, first 10-second excerpt | libx265 `lossless=1` | 16.19 | 9.43 | 0.992953 | 45.47 |

## Recommendation and script

`scripts/video_convert.sh` defaults to `libx265` CRF 18, MP4 with `hvc1`, `yuv420p`, and `+faststart`; a CRF 14 profile is also available. VideoToolbox was more than three times faster than CRF 18, but the long test produced roughly 25% larger output and lower SSIM/PSNR. Its measured quality/size trade-off is therefore not sufficiently comparable for the default profile. CRF 18 produced files larger than the VP8 source in both samples (roughly 40% larger); no storage saving is promised.

The 18 sources total 478,591,999 bytes (456.42 MiB). Extrapolating the size-weighted CRF-18 ratio of the two samples (1.414) gives about **645 MiB (677 MB)** for all outputs. This is a rough, content-dependent estimate; the 106-second opening files were not encoded individually.

Re-encoding an already lossy VP8 source is never lossless relative to the original image signal. At most, `lossless=1` preserves the decoded input to the new encode; it cannot recover information lost to VP8. Hardware decoding on iPad and Mac is a user assumption, not a measurement result.

Usage: `scripts/video_convert.sh SOURCE_DIR OUTPUT_DIR [h265-crf14|h265-crf18]`. The script preserves the directory structure and base names, records SHA-256 hashes and sizes in `video-manifest.json` in the output directory, skips unchanged entries, and stops on errors. There is deliberately no H.264 fallback.
