// maxwell2msl: command line front end for the Maxwell -> MSL translator (own code of the strahlender-xnu project).
//
// Input: a Maxwell shader blob (starts with the NVN header 0x12345678, then SPH and code; compute: code only) or a
// complete Unity shader program of a Switch bundle (magic 0x0C07513C; the blob and the stage are found automatically).
// Output: MSL on stdout or in a file; metadata as JSON (--info); coverage report as JSON (--survey).
//
// Exit codes: 0 ok (survey: no problems), 1 translation failed (survey: problems found), 2 usage error,
//             3 input/output error (unreadable file, unknown container).
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "container.h"
#include "shader.h"

enum { EXIT_OK = 0, EXIT_XLATE = 1, EXIT_USAGE = 2, EXIT_INPUT = 3 };

static void usage(FILE *f) {
    fputs(
        "usage: maxwell2msl [options] <input>\n"
        "       maxwell2msl --survey --batch <list> [options]\n"
        "\n"
        "  <input>               Maxwell blob (0x12345678 ...) or Unity shader program (0x0C07513C ...)\n"
        "  --stage vs|fs|cs      shader stage; required for raw blobs, optional for Unity programs\n"
        "  -o <file>             write the MSL there (default: stdout)\n"
        "  --info <file>         write metadata (resource map: cbufs, textures, inputs/outputs) as JSON ('-' = stdout)\n"
        "  --cbuf1 <file>        write the compiler constants (hardware cbuf 1) found behind the code, up to 64 KB\n"
        "  --survey              coverage mode: do not stop at the first unsupported instruction, print every\n"
        "                        unknown opcode / unsupported form of the shader as JSON (no MSL)\n"
        "  --batch <list>        (with --survey) list file with one '<vs|fs|cs> <path>' per line, JSON lines out\n"
        "  --attr-kind N=f|i|u   vertex attribute N is float / signed int / unsigned int (default float)\n"
        "  --rt-kind N=f|i|u     render target N type (default float)\n"
        "  --vs-out-mask <hex>   fragment: varyings the vertex shader writes (0 = unknown, all inputs kept)\n"
        "  --flip-y              negate clip y in the vertex shader\n"
        "  --depth-minus-one     remap clip z from [-1,1] to [0,1]\n"
        "  --rscale              keep the resolution-scale table of the original (default: plain coordinates)\n"
        "  --glsl                emit Vulkan GLSL instead of MSL\n"
        "  --lang msl|glsl|hlsl  output language (default msl); hlsl = Unity ShaderLab snippet, contract in shader.h\n"
        "                        (also --hlsl; vertex and fragment only)\n"
        "  --annotate            comment each instruction with its pc and word\n"
        "  --fast-math           do not emit the pragmas that disable Metal's fast math and FMA contraction\n"
        "  --half-compat         Ryujinx-compatible fp16: no rounding to half between half operations (test oracle only;\n"
        "                        the default rounds like the hardware)\n"
        "  --gmem-base N         MSL/GLSL: guest address of the global-memory buffer (default 0)\n"
        "  --gmem-size N         MSL/GLSL: size of the global-memory buffer in bytes (default 0: every access is out of range;\n"
        "                        HLSL maps global memory to the ByteAddressBuffer mx_gmem instead)\n"
        "  -h, --help            this text\n",
        f);
}

typedef struct {
    ShaderKey key;
    const char *stage_arg;
} Opts;

static int parse_stage(const char *s) {
    if (!s) return -1;
    if (!strcmp(s, "vs") || !strcmp(s, "vertex")) return STAGE_VERTEX;
    if (!strcmp(s, "fs") || !strcmp(s, "fragment") || !strcmp(s, "ps")) return STAGE_FRAGMENT;
    if (!strcmp(s, "cs") || !strcmp(s, "compute")) return STAGE_COMPUTE;
    return -1;
}

static const char *stage_name(int st) {
    switch (st) {
    case STAGE_VERTEX: return "vs";
    case STAGE_FRAGMENT: return "fs";
    case STAGE_COMPUTE: return "cs";
    default: return "other";
    }
}

static uint8_t *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    uint8_t *buf = NULL;
    size_t cap = 0, len = 0;
    for (;;) {
        if (len + 65536 > cap) {
            cap = cap ? cap * 2 : 65536;
            uint8_t *nb = realloc(buf, cap);
            if (!nb) { free(buf); fclose(f); return NULL; }
            buf = nb;
        }
        size_t r = fread(buf + len, 1, cap - len, f);
        len += r;
        if (r == 0) break;
    }
    int err = ferror(f);
    fclose(f);
    if (err) { free(buf); return NULL; }
    *size = len;
    return buf ? buf : malloc(1);
}

static void json_str(FILE *f, const char *s) {
    fputc('"', f);
    for (; *s; s++) {
        unsigned char ch = (unsigned char)*s;
        if (ch == '"' || ch == '\\') fprintf(f, "\\%c", ch);
        else if (ch < 0x20) fprintf(f, "\\u%04x", ch);
        else fputc(ch, f);
    }
    fputc('"', f);
}

static const char *tex_type_str(int t) {
    static const char *const n[] = {"1d", "2d", "3d", "cube", "2d_array", "cube_array", "1d_array", "buffer", "2d_ms"};
    return t >= 0 && t < 9 ? n[t] : "2d";
}

static const char *comp_str(unsigned m, char *buf) {
    int n = 0;
    for (int i = 0; i < 4; i++) if (m & (1u << i)) buf[n++] = "xyzw"[i];
    buf[n] = 0;
    return buf;
}

// XNU: texture / sampler handle tables of the driver's constant buffer 2 as observed in the Unity NVN shaders of the
// game (texture words from 0x568, sampler words from 0x168, 8 bytes per entry). An assumption, see docs/shader-translator.md.
#define HANDLE_CBUF 2
#define TEXTURE_TABLE_BASE 0x568
#define SAMPLER_TABLE_BASE 0x168
#define HANDLE_STRIDE 8

static long table_index(uint32_t off, uint32_t base) {
    return off >= base && (off - base) % HANDLE_STRIDE == 0 ? (long)((off - base) / HANDLE_STRIDE) : -1;
}

// Machine readable resource map: what a driver (Unity integration, harness) has to bind for this translation.
static void write_info_json(FILE *f, const ShaderInfo *s, size_t blob_bytes, const ShaderKey *key) {
    char cs[8];
    fprintf(f, "{\n  \"stage\": \"%s\",\n  \"language\": \"%s\",\n  \"blobBytes\": %zu,\n  \"instructions\": %u,\n", stage_name(s->stage),
            key->hlsl ? "hlsl" : key->glsl ? "glsl" : "msl", blob_bytes, s->num_insts);
    fprintf(f, "  \"cbufMask\": \"0x%x\",\n  \"cbufDynamic\": \"0x%x\",\n  \"cbufSize\": {", s->cbuf_mask, s->cbuf_dynamic);
    int first = 1;
    for (int i = 0; i < 18; i++) {
        if (!(s->cbuf_mask & (1u << i))) continue;
        fprintf(f, "%s\"%d\": %u", first ? "" : ", ", i, s->cbuf_size[i]);
        first = 0;
    }
    fprintf(f, "},\n  \"metal\": {\"entry\": \"main0\", \"constantBufferSlot\": \"cbuf k -> [[buffer(k)]], constant uint4*\", "
               "\"textureSlot\": \"texture i -> [[texture(i)]] and [[sampler(i)]]\", \"vertexAttribute\": \"location i -> [[attribute(i)]], float4\", "
               "\"stageInterface\": \"vertex out / fragment in: [[user(locn i)]], float4\", \"rscaleBuffer\": %s, \"globalMemoryBuffer\": %s},\n",
            s->uses_rscale ? "18" : "null", s->uses_gmem ? "17" : "null");
    fprintf(f, "  \"compilerConstants\": {\"cbuf\": 1, \"blobOffset\": %u, \"bytesAvailable\": %zu, \"note\": \"data section behind the code, aligned to 0x100; write it with --cbuf1\"},\n",
            s->cbuf1_blob_offset, s->cbuf1_blob_offset < blob_bytes ? blob_bytes - s->cbuf1_blob_offset : 0);
    fprintf(f, "  \"constantBuffers\": [");
    first = 1;
    for (int i = 0; i < 18; i++) {
        if (!(s->cbuf_mask & (1u << i))) continue;
        bool dyn = s->cbuf_dynamic & (1u << i);
        fprintf(f, "%s\n    {\"index\": %d, \"metalBuffer\": %d, \"size\": %u, \"dynamic\": %s, \"staticMinOffset\": %d, \"staticEndOffset\": %d}",
                first ? "" : ",", i, i, s->cbuf_size[i], dyn ? "true" : "false", s->cbuf_end_off[i] ? (int)s->cbuf_min_off[i] : -1,
                s->cbuf_end_off[i] ? (int)s->cbuf_end_off[i] : -1);
        first = 0;
    }
    fprintf(f, "%s],\n  \"textures\": [", first ? "" : "\n  ");
    for (int i = 0; i < s->ntex; i++) {
        const ShaderTexture *t = &s->tex[i];
        fprintf(f, "%s\n    {\"slot\": %d, \"metalTexture\": %d, \"metalSampler\": %d, \"handleOffset\": %u, \"type\": %d, \"typeName\": \"%s\", "
                   "\"shadow\": %s, \"array\": %s, \"bindless\": %s",
                i ? "," : "", i, i, i, t->handle_offset, t->type, tex_type_str(t->type), t->shadow ? "true" : "false",
                t->is_array ? "true" : "false", t->bindless ? "true" : "false");
        if (t->bindless) {
            fprintf(f, ", \"handleCbuf\": %u, \"textureWordOffset\": %u, \"textureTableIndex\": %ld, \"hasSamplerWord\": %s",
                    t->bindless_cbuf, t->bindless_offset,
                    t->bindless_cbuf == HANDLE_CBUF ? table_index(t->bindless_offset, TEXTURE_TABLE_BASE) : -1,
                    t->bindless_has_sampler ? "true" : "false");
            if (t->bindless_has_sampler)
                fprintf(f, ", \"samplerWordOffset\": %u, \"samplerTableIndex\": %ld", t->bindless_sampler_offset,
                        t->bindless_cbuf == HANDLE_CBUF ? table_index(t->bindless_sampler_offset, SAMPLER_TABLE_BASE) : -1);
        }
        fputc('}', f);
    }
    fprintf(f, "%s],\n  \"inputs\": [", s->ntex ? "\n  " : "");
    first = 1;
    for (int i = 0; i < 32; i++) {
        if (!(s->attr_mask & (1u << i))) continue;
        fprintf(f, "%s{\"location\": %d, \"components\": \"%s\"%s}", first ? "" : ", ", i, comp_str(s->in_comp[i], cs),
                s->stage == STAGE_FRAGMENT ? ((s->flat_mask >> i) & 1 ? ", \"interpolation\": \"flat\"" : ", \"interpolation\": \"perspective\"") : "");
        first = 0;
    }
    fprintf(f, "],\n  \"outputs\": [");
    first = 1;
    if (s->stage == STAGE_FRAGMENT) {
        for (int rt = 0; rt < 8; rt++) {
            unsigned m = (s->out_mask >> (rt * 4)) & 0xF;
            if (!m) continue;
            fprintf(f, "%s{\"renderTarget\": %d, \"components\": \"%s\"}", first ? "" : ", ", rt, comp_str(m, cs));
            first = 0;
        }
    } else {
        for (int i = 0; i < 32; i++) {
            if (!(s->out_mask & (1u << i))) continue;
            fprintf(f, "%s{\"location\": %d, \"components\": \"%s\"}", first ? "" : ", ", i, comp_str(s->out_comp[i], cs));
            first = 0;
        }
    }
    fprintf(f, "],\n  \"attrMask\": \"0x%x\",\n  \"outMask\": \"0x%x\",\n", s->attr_mask, s->out_mask);
    fprintf(f, "  \"writesDepth\": %s,\n  \"usesDiscard\": %s,\n  \"writesPointSize\": %s,\n  \"usesGlobalMemory\": %s,\n  \"localMemBytes\": %u\n}\n",
            s->writes_depth ? "true" : "false", s->uses_discard ? "true" : "false", s->writes_point_size ? "true" : "false",
            s->uses_gmem ? "true" : "false", s->local_mem);
}

static double now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}

// Resolves container + stage. Returns an error text or NULL.
static const char *locate(const uint8_t *data, size_t n, int stage_arg, int *stage, const uint8_t **blob, size_t *blob_n) {
    uint32_t magic = n >= 4 ? (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 | (uint32_t)data[3] << 24 : 0;
    if (magic == UNITY_PROGRAM_MAGIC) {
        UnityProgram up;
        const char *err = unity_program_parse(data, n, &up);
        if (err) return err;
        *stage = stage_arg >= 0 ? stage_arg : up.stage;
        if (*stage < 0) return "container stage is neither vertex nor fragment; pass --stage";
        *blob = data + up.blob_offset;
        *blob_n = up.blob_size;
        return NULL;
    }
    if (stage_arg < 0) return "raw blob needs --stage vs|fs|cs";
    *stage = stage_arg;
    if (stage_arg != STAGE_COMPUTE && magic != MAXWELL_BLOB_MAGIC) return "blob does not start with the NVN header magic 0x12345678";
    *blob = data;
    *blob_n = n;
    return NULL;
}

// One survey line. Returns 1 when the shader has problems.
static int survey_one(FILE *out, const char *path, const uint8_t *blob, size_t blob_n, int stage, const ShaderKey *key) {
    Survey *sv = calloc(1, sizeof *sv);
    double t0 = now_us();
    ShaderInfo *info = maxwell_translate_ex(blob, blob_n, stage, key, sv);
    double dt = now_us() - t0;
    int bad = sv->n > 0 || info->error[0];
    fprintf(out, "{\"file\": ");
    json_str(out, path);
    fprintf(out, ", \"stage\": \"%s\", \"bytes\": %zu, \"insts\": %u, \"translatable\": %s, \"us\": %.0f", stage_name(stage), blob_n,
            info->num_insts, bad ? "false" : "true", dt);
    if (info->error[0]) {
        fprintf(out, ", \"error\": ");
        json_str(out, info->error);
    }
    fprintf(out, ", \"unknownOpcodes\": [");
    int first = 1;
    for (int i = 0; i < sv->n; i++) {
        const SurveyItem *it = &sv->items[i];
        if (!it->unknown_opcode) continue;
        fprintf(out, "%s{\"name\": \"%s\", \"bits\": \"0x%03x\", \"count\": %u, \"example\": \"0x%016llx\"}", first ? "" : ", ", it->name,
                it->opcode_bits, it->count, (unsigned long long)it->example_word);
        first = 0;
    }
    fprintf(out, "], \"unsupportedForms\": [");
    first = 1;
    for (int i = 0; i < sv->n; i++) {
        const SurveyItem *it = &sv->items[i];
        if (it->unknown_opcode) continue;
        fprintf(out, "%s{\"name\": ", first ? "" : ", ");
        json_str(out, it->name);
        fprintf(out, ", \"count\": %u, \"example\": \"0x%016llx\"}", it->count, (unsigned long long)it->example_word);
        first = 0;
    }
    fprintf(out, "]%s}\n", sv->overflow ? ", \"overflow\": true" : "");
    maxwell_free(info);
    free(sv);
    return bad;
}

static int parse_kind(const char *arg, uint8_t *table, int max) {
    char *eq;
    long idx = strtol(arg, &eq, 10);
    if (eq == arg || *eq != '=' || idx < 0 || idx >= max) return 0;
    char k = eq[1];
    if (eq[2] || (k != 'f' && k != 'i' && k != 'u')) return 0;
    table[idx] = k == 'f' ? 0 : k == 'i' ? 1 : 2;
    return 1;
}

int main(int argc, char **argv) {
    Opts o = {0};
    o.key.no_rscale = true;
    const char *input = NULL, *out_path = NULL, *info_path = NULL, *batch = NULL, *cbuf1_path = NULL;
    int survey = 0;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
#define NEED_ARG() (i + 1 < argc ? argv[++i] : (fprintf(stderr, "maxwell2msl: %s needs an argument\n", a), usage(stderr), exit(EXIT_USAGE), (char *)0))
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(stdout); return EXIT_OK; }
        else if (!strcmp(a, "--stage")) o.stage_arg = NEED_ARG();
        else if (!strcmp(a, "-o")) out_path = NEED_ARG();
        else if (!strcmp(a, "--info")) info_path = NEED_ARG();
        else if (!strcmp(a, "--cbuf1")) cbuf1_path = NEED_ARG();
        else if (!strcmp(a, "--survey")) survey = 1;
        else if (!strcmp(a, "--batch")) batch = NEED_ARG();
        else if (!strcmp(a, "--attr-kind")) { if (!parse_kind(NEED_ARG(), o.key.attr_kind, 32)) { fprintf(stderr, "maxwell2msl: bad --attr-kind\n"); return EXIT_USAGE; } }
        else if (!strcmp(a, "--rt-kind")) { if (!parse_kind(NEED_ARG(), o.key.rt_kind, 8)) { fprintf(stderr, "maxwell2msl: bad --rt-kind\n"); return EXIT_USAGE; } }
        else if (!strcmp(a, "--vs-out-mask")) o.key.vs_out_mask = (uint32_t)strtoul(NEED_ARG(), NULL, 16);
        else if (!strcmp(a, "--flip-y")) o.key.flip_y = true;
        else if (!strcmp(a, "--depth-minus-one")) o.key.depth_minus_one = true;
        else if (!strcmp(a, "--rscale")) o.key.no_rscale = false;
        else if (!strcmp(a, "--glsl")) o.key.glsl = 1;
        else if (!strcmp(a, "--hlsl")) o.key.hlsl = 1;
        else if (!strcmp(a, "--lang")) {
            const char *l = NEED_ARG();
            o.key.glsl = !strcmp(l, "glsl");
            o.key.hlsl = !strcmp(l, "hlsl");
            if (strcmp(l, "msl") && !o.key.glsl && !o.key.hlsl) { fprintf(stderr, "maxwell2msl: unknown language '%s' (msl, glsl, hlsl)\n", l); return EXIT_USAGE; }
        }
        else if (!strcmp(a, "--annotate")) o.key.annotate = true;
        else if (!strcmp(a, "--fast-math")) o.key.fast_math = true;
        else if (!strcmp(a, "--half-compat")) o.key.half_compat = true;
        else if (!strcmp(a, "--gmem-size")) maxwell_gmem_size = strtoull(NEED_ARG(), NULL, 0);
        else if (!strcmp(a, "--gmem-base")) maxwell_gmem_base = strtoull(NEED_ARG(), NULL, 0);
        else if (a[0] == '-' && a[1]) { fprintf(stderr, "maxwell2msl: unknown option %s\n", a); usage(stderr); return EXIT_USAGE; }
        else if (!input) input = a;
        else { fprintf(stderr, "maxwell2msl: more than one input file\n"); return EXIT_USAGE; }
    }
    int stage_arg = -1;
    if (o.stage_arg) {
        stage_arg = parse_stage(o.stage_arg);
        if (stage_arg < 0) { fprintf(stderr, "maxwell2msl: unknown stage '%s' (vs, fs, cs)\n", o.stage_arg); return EXIT_USAGE; }
    }
    if (batch && !survey) { fprintf(stderr, "maxwell2msl: --batch needs --survey\n"); return EXIT_USAGE; }
    if (batch && input) { fprintf(stderr, "maxwell2msl: --batch and an input file exclude each other\n"); return EXIT_USAGE; }
    if (!batch && !input) { usage(stderr); return EXIT_USAGE; }

    FILE *out = stdout;
    if (out_path && !survey) {
        out = fopen(out_path, "wb");
        if (!out) { fprintf(stderr, "maxwell2msl: cannot write %s: %s\n", out_path, strerror(errno)); return EXIT_INPUT; }
    }

    if (batch) {  // coverage over many files in one process
        FILE *lf = fopen(batch, "r");
        if (!lf) { fprintf(stderr, "maxwell2msl: cannot read %s: %s\n", batch, strerror(errno)); return EXIT_INPUT; }
        FILE *bout = out_path ? fopen(out_path, "wb") : stdout;
        if (!bout) { fprintf(stderr, "maxwell2msl: cannot write %s: %s\n", out_path, strerror(errno)); return EXIT_INPUT; }
        char line[4096];
        long total = 0, bad = 0, io_err = 0;
        double t0 = now_us();
        while (fgets(line, sizeof line, lf)) {
            char *nl = strpbrk(line, "\r\n");
            if (nl) *nl = 0;
            if (!line[0]) continue;
            char *sp = strchr(line, ' ');
            int st = -1;
            char *path = line;
            if (sp) { *sp = 0; st = parse_stage(line); path = sp + 1; }
            if (st < 0) st = stage_arg;
            size_t n;
            uint8_t *data = read_file(path, &n);
            const uint8_t *blob;
            size_t blob_n;
            const char *err = data ? locate(data, n, st, &st, &blob, &blob_n) : "cannot read file";
            total++;
            if (err) {
                fprintf(bout, "{\"file\": ");
                json_str(bout, path);
                fprintf(bout, ", \"inputError\": ");
                json_str(bout, err);
                fprintf(bout, "}\n");
                io_err++;
            } else {
                bad += survey_one(bout, path, blob, blob_n, st, &o.key);
            }
            free(data);
        }
        fclose(lf);
        if (bout != stdout) fclose(bout);
        fprintf(stderr, "maxwell2msl: %ld shaders, %ld with problems, %ld unreadable, %.2f s\n", total, bad, io_err, (now_us() - t0) / 1e6);
        return io_err ? EXIT_INPUT : bad ? EXIT_XLATE : EXIT_OK;
    }

    size_t n;
    uint8_t *data = read_file(input, &n);
    if (!data) { fprintf(stderr, "maxwell2msl: cannot read %s: %s\n", input, strerror(errno)); return EXIT_INPUT; }
    int stage;
    const uint8_t *blob;
    size_t blob_n;
    const char *err = locate(data, n, stage_arg, &stage, &blob, &blob_n);
    if (err) { fprintf(stderr, "maxwell2msl: %s: %s\n", input, err); free(data); return EXIT_INPUT; }

    int rc = EXIT_OK;
    if (survey) {
        rc = survey_one(stdout, input, blob, blob_n, stage, &o.key) ? EXIT_XLATE : EXIT_OK;
    } else {
        ShaderInfo *info = maxwell_translate(blob, blob_n, stage, &o.key);
        if (!info->msl) {
            fprintf(stderr, "maxwell2msl: %s: translation failed: %s\n", input, info->error[0] ? info->error : "unknown error");
            rc = EXIT_XLATE;
        } else {
            fputs(info->msl, out);
            if (info_path) {
                FILE *jf = !strcmp(info_path, "-") ? stdout : fopen(info_path, "wb");
                if (!jf) { fprintf(stderr, "maxwell2msl: cannot write %s: %s\n", info_path, strerror(errno)); rc = EXIT_INPUT; }
                else { write_info_json(jf, info, blob_n, &o.key); if (jf != stdout) fclose(jf); }
            }
            if (cbuf1_path) {  // XNU: compiler constants (hardware cbuf 1), at most 64 KB, zero-padded to the bound size
                FILE *cf = fopen(cbuf1_path, "wb");
                size_t off = info->cbuf1_blob_offset, avail = off < blob_n ? blob_n - off : 0;
                if (!cf) { fprintf(stderr, "maxwell2msl: cannot write %s: %s\n", cbuf1_path, strerror(errno)); rc = EXIT_INPUT; }
                else {
                    if (fwrite(blob + off, 1, avail > 65536 ? 65536 : avail, cf) != (avail > 65536 ? 65536 : avail)) rc = EXIT_INPUT;
                    if (fclose(cf) != 0) rc = EXIT_INPUT;
                }
            }
        }
        maxwell_free(info);
    }
    if (out != stdout && fclose(out) != 0) rc = EXIT_INPUT;
    free(data);
    return rc;
}
