#include "host_shutdown.h"
#include "swkbd_keepalive.h"
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <time.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static unsigned owners;
static int closing, finished, failed, idle_done, idle_result;
static int (*idle_callback)(void);

int host_surface_enter(void) {
    pthread_mutex_lock(&lock);
    int admitted = !closing;
    if (admitted) owners++;
    pthread_mutex_unlock(&lock);
    return admitted;
}

void host_surface_leave(void) {
    pthread_mutex_lock(&lock);
    owners--;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
}

static void *wait_gpu(void *unused) {
    (void)unused;
    int result = idle_callback();
    pthread_mutex_lock(&lock);
    idle_result = result;
    idle_done = 1;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
    return NULL;
}

int host_surface_shutdown(int (*gpu_idle)(void), unsigned timeout_ms) {
    struct timespec deadline;
    if (timespec_get(&deadline, TIME_UTC) != TIME_UTC) {
        fprintf(stderr, "[host-shutdown] cannot establish shutdown deadline\n");
        return 0;
    }
    deadline.tv_sec += timeout_ms / 1000;
    deadline.tv_nsec += (long)(timeout_ms % 1000) * 1000000;
    if (deadline.tv_nsec >= 1000000000) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000; }
    pthread_mutex_lock(&lock);
    if (closing) {
        int result = finished && !failed;
        pthread_mutex_unlock(&lock);
        return result;
    }
    closing = 1;
    pthread_mutex_unlock(&lock);
    fprintf(stderr, "[host-shutdown] surface admission closed\n");
    /* No surface/keepalive lock may be held across the stop or join. */
    if (!swkbd_keepalive_stop(&deadline)) goto error;
    pthread_mutex_lock(&lock);
    while (owners) {
        int status = pthread_cond_timedwait(&changed, &lock, &deadline);
        if (status) {
            pthread_mutex_unlock(&lock);
            fprintf(stderr, "[host-shutdown] surface drain failed: %d%s\n",
                    status, status == ETIMEDOUT ? " (timeout)" : "");
            goto error;
        }
    }
    idle_callback = gpu_idle;
    pthread_mutex_unlock(&lock);
    pthread_t worker;
    int status = pthread_create(&worker, NULL, wait_gpu, NULL);
    if (status) {
        fprintf(stderr, "[host-shutdown] GPU waiter creation failed: %d\n", status);
        goto error;
    }
    pthread_mutex_lock(&lock);
    while (!idle_done) {
        status = pthread_cond_timedwait(&changed, &lock, &deadline);
        if (status) {
            pthread_mutex_unlock(&lock);
            fprintf(stderr, "[host-shutdown] GPU idle failed: %d%s\n",
                    status, status == ETIMEDOUT ? " (timeout)" : "");
            /* Caller terminates; never destroy a surface still used by the driver. */
            int detached = pthread_detach(worker);
            if (detached) fprintf(stderr, "[host-shutdown] waiter detach failed: %d\n", detached);
            goto error;
        }
    }
    int result = idle_result;
    pthread_mutex_unlock(&lock);
    status = pthread_join(worker, NULL);
    if (status || !result) {
        fprintf(stderr, "[host-shutdown] GPU idle/join failed: result=%d join=%d\n", result, status);
        goto error;
    }
    pthread_mutex_lock(&lock);
    finished = 1;
    pthread_mutex_unlock(&lock);
    fprintf(stderr, "[host-shutdown] surface stopped: keepalive joined, CPU drained, GPU idle\n");
    return 1;
error:
    pthread_mutex_lock(&lock);
    failed = 1;
    pthread_mutex_unlock(&lock);
    return 0;
}
