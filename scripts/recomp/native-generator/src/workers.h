/* SPDX-License-Identifier: MIT. Bounded ordered native tasks; results own their memory. */
#ifndef BDSP_WORKERS_H
#define BDSP_WORKERS_H
#include "codegen.h"
#include <setjmp.h>
typedef struct {
    jmp_buf jump; int code;
    char message[1024], phase[64], module[128];
} CgFailure;
void cg_failure_target(CgFailure *target);
typedef struct CgPool CgPool;
typedef void *(*CgWork)(void *context,size_t index);
typedef void (*CgDispose)(void *result);
size_t cg_choose_jobs(const char *value);
CgPool *cg_pool_open(size_t jobs,size_t count,CgWork work,void *context,CgDispose dispose);
void *cg_pool_next(CgPool *pool);
void cg_pool_close(CgPool *pool);
#endif
