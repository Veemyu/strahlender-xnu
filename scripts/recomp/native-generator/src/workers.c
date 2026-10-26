/* SPDX-License-Identifier: MIT. Deterministic bounded pthread/Win32 worker pool. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "workers.h"
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
typedef CRITICAL_SECTION Mutex;
typedef CONDITION_VARIABLE Condition;
typedef HANDLE Thread;
#define lock EnterCriticalSection
#define unlock LeaveCriticalSection
static void condition_wait(Condition *c,Mutex *m) {if(!SleepConditionVariableCS(c,m,INFINITE))cg_fail(4,"native worker condition wait failed");}
static void wake(Condition *c) {WakeAllConditionVariable(c);}
#else
#include <pthread.h>
#include <unistd.h>
#ifdef __APPLE__
#include <sys/sysctl.h>
#else
#include <sched.h>
#endif
typedef pthread_mutex_t Mutex;
typedef pthread_cond_t Condition;
typedef pthread_t Thread;
static void lock(Mutex *m) {if(pthread_mutex_lock(m))cg_fail(4,"native worker lock failed");}
static void unlock(Mutex *m) {if(pthread_mutex_unlock(m))cg_fail(4,"native worker unlock failed");}
static void condition_wait(Condition *c,Mutex *m) {if(pthread_cond_wait(c,m))cg_fail(4,"native worker wait failed");}
static void wake(Condition *c) {if(pthread_cond_broadcast(c))cg_fail(4,"native worker wake failed");}
#endif
typedef struct {void *value;bool ready;} Slot;
#define TASK_BATCH 8
typedef struct {struct CgPool *pool;size_t index,start,count,finished;void *results[TASK_BATCH];} Worker;
struct CgPool {
    Mutex mutex;Condition changed;Thread *threads;Worker *workers;CgFailure *failures;
    size_t jobs,count,capacity,next_job,next_read;Slot *slots;bool stopping,failed;
    CgFailure error;CgWork work;CgDispose dispose;void *context;
    void *ready[TASK_BATCH];size_t ready_count,ready_pos;
};
static void *allocate(size_t count,size_t size) {
    if(size&&count>SIZE_MAX/size)cg_fail(4,"worker allocation overflow");
    void *p=calloc(count,size);if(!p)cg_fail(4,"not enough memory for native workers");return p;
}
size_t cg_choose_jobs(const char *value) {
    if(value&&strcmp(value,"auto")) {uint64_t jobs=cg_number(value);if(!jobs||jobs>SIZE_MAX/(TASK_BATCH*2))cg_fail(2,"jobs must be auto or a positive integer");return (size_t)jobs;}
    size_t cpus=1;uint64_t memory=0;
#ifdef _WIN32
    DWORD count=GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);if(count)cpus=count;
    MEMORYSTATUSEX status={.dwLength=sizeof(status)};if(GlobalMemoryStatusEx(&status))memory=status.ullTotalPhys;
#else
    long count=sysconf(_SC_NPROCESSORS_ONLN);if(count>0)cpus=(size_t)count;
#ifdef __APPLE__
    size_t length=sizeof(memory);if(sysctlbyname("hw.memsize",&memory,&length,NULL,0))memory=0;
#else
    cpu_set_t affinity;if(!sched_getaffinity(0,sizeof(affinity),&affinity)) {int available=CPU_COUNT(&affinity);if(available>0&&(size_t)available<cpus)cpus=(size_t)available;}
    long pages=sysconf(_SC_PHYS_PAGES),page_size=sysconf(_SC_PAGESIZE);
    if(pages>0&&page_size>0&&(uint64_t)pages<=UINT64_MAX/(uint64_t)page_size)memory=(uint64_t)pages*(uint64_t)page_size;
    FILE *file=fopen("/sys/fs/cgroup/memory.max","r");
    if(file) {char text[64];if(fgets(text,sizeof(text),file)&&strcmp(text,"max\n")) {char *end;errno=0;uintmax_t limit=strtoumax(text,&end,10);if(!errno&&end!=text&&limit&&(!memory||limit<memory))memory=limit;}fclose(file);}
    file=fopen("/sys/fs/cgroup/cpu.max","r");
    if(file) {char quota[32];uint64_t period;if(fscanf(file,"%31s %" SCNu64,quota,&period)==2&&strcmp(quota,"max")&&period) {char *end;uintmax_t n=strtoumax(quota,&end,10);uint64_t limit=(uint64_t)(n/period+(n%period!=0));if(end!=quota&&limit&&limit<cpus)cpus=(size_t)limit;}fclose(file);}
#endif
#endif
    /* Module image/classification is shared; only bounded temporary emit data is per worker. */
    if(memory) {uint64_t limit=memory/(128u*1024u*1024u);if(!limit)limit=1;if(limit<cpus)cpus=(size_t)limit;}
    return cpus?cpus:1;
}
static void run_worker(Worker *worker) {
    CgPool *p=worker->pool;CgFailure *failure=&p->failures[worker->index];
    for(;;) {
        lock(&p->mutex);
        while(!p->stopping&&p->next_job<p->count&&p->next_job>=p->next_read+p->capacity)condition_wait(&p->changed,&p->mutex);
        if(p->stopping||p->next_job==p->count) {unlock(&p->mutex);break;}
        worker->start=p->next_job;worker->count=p->count-p->next_job;
        size_t available=p->next_read+p->capacity-p->next_job;
        if(worker->count>available)worker->count=available;
        if(worker->count>TASK_BATCH)worker->count=TASK_BATCH;
        worker->finished=0;p->next_job+=worker->count;unlock(&p->mutex);
        cg_failure_target(failure);
        if(setjmp(failure->jump)==0) {
            while(worker->finished<worker->count) {
                void *mark=cg_mark();
                worker->results[worker->finished]=p->work(p->context,worker->start+worker->finished);
                worker->finished++;cg_rewind(mark);
            }
        } else {
            cg_failure_target(NULL);cg_rewind(NULL);
            for(size_t i=0;i<worker->finished;i++)if(worker->results[i]&&p->dispose)p->dispose(worker->results[i]);
            lock(&p->mutex);
            if(!p->failed) {p->failed=true;p->error=*failure;}p->stopping=true;wake(&p->changed);unlock(&p->mutex);break;
        }
        cg_failure_target(NULL);
        lock(&p->mutex);
        for(size_t i=0;i<worker->count;i++) {
            Slot *slot=&p->slots[(worker->start+i)%p->capacity];slot->value=worker->results[i];slot->ready=true;
        }
        wake(&p->changed);unlock(&p->mutex);
    }
    cg_failure_target(NULL);cg_thread_finish();
}
#ifdef _WIN32
static DWORD WINAPI thread_main(LPVOID value) {run_worker(value);return 0;}
#else
static void *thread_main(void *value) {run_worker(value);return NULL;}
#endif
CgPool *cg_pool_open(size_t jobs,size_t count,CgWork work,void *context,CgDispose dispose) {
    if(!jobs||!count)cg_fail(4,"native worker pool requires tasks and workers");
    if(jobs>count)jobs=count;if(jobs>SIZE_MAX/(TASK_BATCH*2))cg_fail(4,"worker count overflow");
    CgPool *p=allocate(1,sizeof(*p));p->jobs=jobs;p->count=count;p->capacity=jobs*TASK_BATCH*2;p->work=work;p->context=context;p->dispose=dispose;
    p->slots=allocate(p->capacity,sizeof(*p->slots));p->threads=allocate(jobs,sizeof(*p->threads));p->workers=allocate(jobs,sizeof(*p->workers));p->failures=allocate(jobs,sizeof(*p->failures));
#ifdef _WIN32
    InitializeCriticalSection(&p->mutex);InitializeConditionVariable(&p->changed);
#else
    if(pthread_mutex_init(&p->mutex,NULL)||pthread_cond_init(&p->changed,NULL))cg_fail(4,"cannot initialize native worker synchronization");
#endif
    for(size_t i=0;i<jobs;i++) {
        p->workers[i]=(Worker){.pool=p,.index=i};
#ifdef _WIN32
        p->threads[i]=CreateThread(NULL,0,thread_main,&p->workers[i],0,NULL);if(!p->threads[i])cg_fail(4,"cannot create native worker thread");
#else
        if(pthread_create(&p->threads[i],NULL,thread_main,&p->workers[i]))cg_fail(4,"cannot create native worker thread");
#endif
    }
    return p;
}
void cg_pool_close(CgPool *p) {
    if(!p)return;lock(&p->mutex);p->stopping=true;wake(&p->changed);unlock(&p->mutex);
    for(size_t i=0;i<p->jobs;i++) {
#ifdef _WIN32
        WaitForSingleObject(p->threads[i],INFINITE);CloseHandle(p->threads[i]);
#else
        if(pthread_join(p->threads[i],NULL))cg_fail(4,"cannot join native worker thread");
#endif
    }
    for(size_t i=0;i<p->capacity;i++)if(p->slots[i].ready&&p->slots[i].value&&p->dispose)p->dispose(p->slots[i].value);
    for(size_t i=p->ready_pos;i<p->ready_count;i++)if(p->ready[i]&&p->dispose)p->dispose(p->ready[i]);
#ifdef _WIN32
    DeleteCriticalSection(&p->mutex);
#else
    pthread_mutex_destroy(&p->mutex);pthread_cond_destroy(&p->changed);
#endif
    free(p->threads);free(p->workers);free(p->failures);free(p->slots);free(p);
}
void *cg_pool_next(CgPool *p) {
    if(p->ready_pos<p->ready_count)return p->ready[p->ready_pos++];
    lock(&p->mutex);
    if(p->next_read>=p->count) {unlock(&p->mutex);cg_fail(4,"no remaining ordered worker result");}
    while(!p->failed&&!p->slots[p->next_read%p->capacity].ready)condition_wait(&p->changed,&p->mutex);
    if(p->failed) {CgFailure error=p->error;unlock(&p->mutex);cg_pool_close(p);cg_phase=error.phase;cg_module=error.module;cg_fail(error.code,"%s",error.message);}
    if(p->next_read>=p->count) {unlock(&p->mutex);cg_fail(4,"no remaining ordered worker result");}
    p->ready_count=0;p->ready_pos=0;
    while(p->ready_count<TASK_BATCH&&p->next_read<p->count) {
        Slot *slot=&p->slots[p->next_read%p->capacity];if(!slot->ready)break;
        p->ready[p->ready_count++]=slot->value;*slot=(Slot){0};p->next_read++;
    }
    wake(&p->changed);unlock(&p->mutex);return p->ready[p->ready_pos++];
}
