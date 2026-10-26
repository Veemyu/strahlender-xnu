/* SPDX-License-Identifier: MIT. Worker ordering, arena lifetime and failure joins. */
#include "workers.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
static atomic_size_t active,produced,disposed;
static bool fail;
static CgFailure failure;
static void dispose(void *value) {if(value){atomic_fetch_add(&disposed,1);free(value);}}
static void *work(void *context,size_t index) {
    (void)context;atomic_fetch_add(&active,1);cg_phase="worker-probe";cg_module="synthetic";
    void *mark=cg_mark();unsigned char *memory=cg_alloc(257,1);
    for(size_t i=0;i<257;i++)if(memory[i])abort();
    memset(memory,0x5a,257);cg_rewind(mark);
    memory=cg_alloc(257,1);for(size_t i=0;i<257;i++)if(memory[i])abort();
    if(index==0)for(volatile size_t i=0;i<100000;i++){}
    if(fail&&index==19) {atomic_fetch_sub(&active,1);cg_fail(17,"intentional worker failure");}
    size_t *result=malloc(sizeof(*result));if(!result)abort();*result=index;
    atomic_fetch_add(&produced,1);atomic_fetch_sub(&active,1);return result;
}
int main(int argc,char **argv) {
    fail=argc>1&&!strcmp(argv[1],"fail");
    cg_failure_target(&failure);
    if(setjmp(failure.jump)) {
        cg_failure_target(NULL);
        if(!fail||failure.code!=17||strcmp(failure.phase,"worker-probe")||strcmp(failure.module,"synthetic")||atomic_load(&active))return 2;
        /* next() must join all workers and dispose every unconsumed result. */
        if(atomic_load(&produced)!=atomic_load(&disposed))return 3;
        return 0;
    }
    CgPool *pool=cg_pool_open(8,50000,work,NULL,dispose);
    for(size_t i=0;i<50000;i++) {
        size_t *value=cg_pool_next(pool);if(!value||*value!=i)return 4;
        dispose(value);
    }
    cg_pool_close(pool);cg_failure_target(NULL);
    return fail||atomic_load(&active)||atomic_load(&produced)!=50000||atomic_load(&disposed)!=50000;
}
