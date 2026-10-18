// Reader for the Unity shader-program container of Switch bundles (own code of the strahlender-xnu project).
#include "container.h"

#include <string.h>

#include "shader.h"

static int rd32(const uint8_t *d, size_t n, size_t o, uint32_t *v) {
    if (o > n || n - o < 4) return 0;
    *v = (uint32_t)d[o] | (uint32_t)d[o + 1] << 8 | (uint32_t)d[o + 2] << 16 | (uint32_t)d[o + 3] << 24;
    return 1;
}

const char *unity_program_parse(const uint8_t *d, size_t n, UnityProgram *out) {
    uint32_t v, nkw, total = 0;
    memset(out, 0, sizeof *out);
    if (!rd32(d, n, 0, &v) || v != UNITY_PROGRAM_MAGIC) return "not a Unity shader program (magic 0x0C07513C missing)";
    if (!rd32(d, n, 4, &out->version) || !rd32(d, n, 0x18, &nkw)) return "truncated header";
    size_t pos = 0x1C;
    uint32_t total_kw = 0;
    for (int list = 0; list < 2; list++) {  // global keywords, then local keywords
        if (nkw > 4096) return "implausible keyword count";
        total_kw += nkw;
        for (uint32_t i = 0; i < nkw; i++) {
            uint32_t len;
            if (!rd32(d, n, pos, &len) || len > 4096) return "bad keyword entry";
            pos = (pos + 4 + len + 3) & ~(size_t)3;
        }
        if (list == 0 && !rd32(d, n, pos, &nkw)) return "truncated keyword list";
        if (list == 0) pos += 4;
    }
    out->keyword_count = total_kw;
    size_t hdr = pos;
    uint32_t stage, ctrl;
    if (!rd32(d, n, hdr, &total) || !rd32(d, n, hdr + 4, &stage) || !rd32(d, n, hdr + 0x14, &ctrl))
        return "truncated control header";
    if (ctrl != UNITY_CONTROL_MAGIC) return "control magic 0x98761234 missing";
    out->stage = stage == 0 ? STAGE_VERTEX : stage == 1 ? STAGE_FRAGMENT : -1;
    size_t m = hdr + 0x18;
    for (; m + 4 <= n; m++)
        if (d[m] == 0x78 && d[m + 1] == 0x56 && d[m + 2] == 0x34 && d[m + 3] == 0x12) break;
    if (m + 4 > n) return "Maxwell blob magic 0x12345678 not found";
    // The announced data offset/size do not always cover the code (checked on the bundle shaders), so the blob runs to
    // the end of the program; the translator finds the end of the code by itself.
    out->blob_offset = m;
    out->blob_size = n - m;
    return NULL;
}
