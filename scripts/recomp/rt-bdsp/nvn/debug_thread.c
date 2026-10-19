// Debug-Thread (BDSP_DEBUG_THREAD=1, Standard aus): Screenshots und Readbacks (nvn/dbgthread.patch) laufen auf einem eigenen Thread
// statt auf dem Render-Thread. Einfache Warteschlange (Mutex + Bedingungsvariable), Aufträge laufen der Reihe nach. Eigener Code.
#include <pthread.h>
#include <stdbool.h>
#include <stdlib.h>

typedef struct Job { void (*fn)(void *); void *arg; struct Job *next; } Job;

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t has_work = PTHREAD_COND_INITIALIZER, idle = PTHREAD_COND_INITIALIZER;
static Job *head, *tail;
static int busy;
static bool started;
static int enabled = -1;
void dbg_thread_drain(void);

static void *worker(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mu);
    for (;;) {
        while (!head) pthread_cond_wait(&has_work, &mu);
        Job *j = head;
        head = j->next;
        if (!head) tail = NULL;
        busy = 1;
        pthread_mutex_unlock(&mu);
        j->fn(j->arg);
        free(j);
        pthread_mutex_lock(&mu);
        busy = 0;
        if (!head) pthread_cond_broadcast(&idle);
    }
    return NULL;
}

bool dbg_thread_enabled(void) {
    if (enabled < 0) {
        const char *e = getenv("BDSP_DEBUG_THREAD");
        enabled = e && *e && *e != '0';
    }
    return enabled;
}

// Reiht einen Auftrag ein; ohne aktiven Debug-Thread läuft er sofort auf dem aufrufenden Thread.
void dbg_thread_submit(void (*fn)(void *), void *arg) {
    if (!dbg_thread_enabled()) { fn(arg); return; }
    Job *j = calloc(1, sizeof *j);
    j->fn = fn;
    j->arg = arg;
    pthread_mutex_lock(&mu);
    if (!started) {
        pthread_t t;
        started = pthread_create(&t, NULL, worker, NULL) == 0;
        if (started) { pthread_detach(t); atexit(dbg_thread_drain); }
    }
    if (!started) { pthread_mutex_unlock(&mu); fn(arg); free(j); return; }
    if (tail) tail->next = j; else head = j;
    tail = j;
    pthread_cond_signal(&has_work);
    pthread_mutex_unlock(&mu);
}

// Wartet, bis die Warteschlange leer ist (vor dem Beenden des Prozesses).
void dbg_thread_drain(void) {
    if (!started) return;
    pthread_mutex_lock(&mu);
    while (head || busy) pthread_cond_wait(&idle, &mu);
    pthread_mutex_unlock(&mu);
}
