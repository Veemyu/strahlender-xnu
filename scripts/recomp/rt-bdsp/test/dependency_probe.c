#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <shaderc/shaderc.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>

static void check_movie(void) {
    assert(avcodec_version() == LIBAVCODEC_VERSION_INT);
    assert(avformat_version() == LIBAVFORMAT_VERSION_INT);
    assert(avutil_version() == LIBAVUTIL_VERSION_INT);
    const char *configuration = avcodec_configuration();
    assert(!strstr(configuration, "--enable-gpl"));
    assert(!strstr(configuration, "--enable-nonfree"));
    assert(strstr(configuration, "--enable-shared"));
    assert(strstr(avcodec_license(), "LGPL version 3"));
    assert(!strcmp(avcodec_license(), avformat_license()));
    assert(!strcmp(avcodec_license(), avutil_license()));
    assert(avcodec_find_decoder(AV_CODEC_ID_VP8));
    assert(avcodec_find_decoder(AV_CODEC_ID_VP9));
    assert(avcodec_find_decoder(AV_CODEC_ID_H264));

    const AVCodec *encoder = avcodec_find_encoder(AV_CODEC_ID_VP8);
    const AVCodec *decoder = avcodec_find_decoder(AV_CODEC_ID_VP8);
    assert(encoder && decoder);
    AVCodecContext *enc = avcodec_alloc_context3(encoder);
    AVCodecContext *dec = avcodec_alloc_context3(decoder);
    assert(enc && dec);
    enc->width = enc->height = 32;
    enc->time_base = (AVRational){1, 25};
    enc->pix_fmt = AV_PIX_FMT_YUV420P;
    enc->bit_rate = 100000;
    assert(avcodec_open2(enc, encoder, NULL) == 0);
    assert(avcodec_open2(dec, decoder, NULL) == 0);
    AVFrame *input = av_frame_alloc(), *output = av_frame_alloc();
    AVPacket *packet = av_packet_alloc();
    assert(input && output && packet);
    input->format = enc->pix_fmt;
    input->width = input->height = 32;
    input->pts = 0;
    assert(av_frame_get_buffer(input, 32) == 0);
    for (int plane = 0; plane < 3; plane++) {
        int size = plane ? 16 : 32;
        for (int y = 0; y < size; y++)
            memset(input->data[plane] + y * input->linesize[plane], plane ? 128 : 64, (size_t)size);
    }
    assert(avcodec_send_frame(enc, input) == 0);
    assert(avcodec_send_frame(enc, NULL) == 0);
    assert(avcodec_receive_packet(enc, packet) == 0);
    assert(packet->size > 0);
    const char *path = "movie-\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e.webm";
    AVFormatContext *mux = NULL;
    assert(avformat_alloc_output_context2(&mux, NULL, "webm", path) == 0 && mux);
    AVStream *stream = avformat_new_stream(mux, NULL);
    assert(stream && avcodec_parameters_from_context(stream->codecpar, enc) == 0);
    stream->time_base = enc->time_base;
    assert(avio_open(&mux->pb, path, AVIO_FLAG_WRITE) == 0);
    assert(avformat_write_header(mux, NULL) == 0);
    packet->stream_index = stream->index;
    av_packet_rescale_ts(packet, enc->time_base, stream->time_base);
    assert(av_interleaved_write_frame(mux, packet) == 0);
    assert(av_write_trailer(mux) == 0);
    assert(avio_closep(&mux->pb) == 0);
    avformat_free_context(mux);
    AVFormatContext *demux = NULL;
    assert(avformat_open_input(&demux, path, NULL, NULL) == 0);
    assert(avformat_find_stream_info(demux, NULL) >= 0);
    assert(demux->nb_streams == 1 && demux->streams[0]->codecpar->codec_id == AV_CODEC_ID_VP8);
    assert(av_read_frame(demux, packet) == 0);
    assert(avcodec_send_packet(dec, packet) == 0);
    assert(avcodec_receive_frame(dec, output) == 0);
    assert(output->width == 32 && output->height == 32);
    assert(output->format == AV_PIX_FMT_YUV420P);
    assert(output->data[0][0] >= 60 && output->data[0][0] <= 68);
    av_packet_free(&packet);
    av_frame_free(&input);
    av_frame_free(&output);
    avcodec_free_context(&enc);
    avcodec_free_context(&dec);
    avformat_close_input(&demux);
    printf("ffmpeg-version=%s\nffmpeg-license=%s\nffmpeg-configuration=%s\n",
           av_version_info(), avcodec_license(), configuration);
    puts("movie=vp8-roundtrip;decoders=vp8,vp9,h264");
}

static void check_shader(void) {
    shaderc_compiler_t compiler = shaderc_compiler_initialize();
    assert(compiler);
    const char *valid = "#version 450\nvoid main(){gl_Position=vec4(0.0,0.0,0.0,1.0);}";
    shaderc_compilation_result_t result = shaderc_compile_into_spv(
        compiler, valid, strlen(valid), shaderc_vertex_shader, "probe.vert", "main", NULL);
    assert(result && shaderc_result_get_compilation_status(result) == shaderc_compilation_status_success);
    assert(shaderc_result_get_length(result) >= 20 && shaderc_result_get_length(result) % 4 == 0);
    uint32_t magic;
    memcpy(&magic, shaderc_result_get_bytes(result), sizeof magic);
    assert(magic == 0x07230203);
    shaderc_result_release(result);
    const char *invalid = "#version 450\nnot a shader";
    result = shaderc_compile_into_spv(
        compiler, invalid, strlen(invalid), shaderc_vertex_shader, "invalid.vert", "main", NULL);
    assert(result && shaderc_result_get_compilation_status(result) != shaderc_compilation_status_success);
    assert(shaderc_result_get_num_errors(result) > 0);
    assert(strlen(shaderc_result_get_error_message(result)) > 0);
    shaderc_result_release(result);
    shaderc_compiler_release(compiler);
    puts("shaderc=valid-spirv-and-invalid-diagnostics");
}

int main(void) {
    check_movie();
    check_shader();
    return 0;
}
