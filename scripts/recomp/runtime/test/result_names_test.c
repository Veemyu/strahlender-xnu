// Test of the nn::Result names of a guest abort (issue 57: the log said only "module 2, description 6063").
#include <stdio.h>
#include <string.h>

#include "result_names.h"

#define CHECK(c) do { if (!(c)) { printf("FAILED line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void) {
    CHECK(strcmp(nn_result_name(0x2f5e02), "fs NullptrArgument") == 0);
    CHECK(nn_result_hint(0x2f5e02) && strstr(nn_result_hint(0x2f5e02), "null buffer"));
    CHECK(strcmp(nn_result_name((1u << 9) | 2), "fs PathNotFound") == 0);
    CHECK(nn_result_hint((1u << 9) | 2) == NULL);   // a missing path comes from the service, not from the SDK argument check
    CHECK(nn_result_name((6063u << 9) | 3) == NULL);  // other module
    CHECK(nn_result_name((9999u << 9) | 2) == NULL);
    printf("Result names test: ok\n");
    return 0;
}
