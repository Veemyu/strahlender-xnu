#ifndef BDSP_HOST_SHUTDOWN_H
#define BDSP_HOST_SHUTDOWN_H

/* Terminal host close only; swapchain recreation must not close admission. */
int host_surface_enter(void);
void host_surface_leave(void);
/* Main thread only. Nonzero means CPU owners joined/drained and GPU idle.
   Failure is terminal: the host must terminate without destroying the surface. */
int host_surface_shutdown(int (*gpu_idle)(void), unsigned timeout_ms);

#endif
