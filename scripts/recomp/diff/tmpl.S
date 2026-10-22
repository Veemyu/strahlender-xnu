// Reference loop of the differential test (docs/recomp-diff.md). Own code, AArch64.
// void tmpl(const Case *in /*x0*/, Out *out /*x1*/, uint64_t n /*x2*/): per case load V0..V7, X0..X3, NZCV, FPCR,
// clear FPSR, execute the four instruction slots (UDF markers 0xE7F0A001..4, overwritten by the driver) and
// store V0, X0, NZCV, FPSR. V8..V31 are zero (like a fresh Cpu in c mode). The same bytes run under Unicorn
// and natively on the M1 (JIT), the counterpart is the generated C code.
    .text
    .globl tmpl
tmpl:
    stp x29, x30, [sp, #-160]!
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    stp d8, d9, [sp, #48]
    stp d10, d11, [sp, #64]
    stp d12, d13, [sp, #80]
    stp d14, d15, [sp, #96]
    mov x19, x0
    mov x20, x1
    mov x21, x2
    mrs x22, fpcr
    movi v8.2d, #0
    movi v9.2d, #0
    movi v10.2d, #0
    movi v11.2d, #0
    movi v12.2d, #0
    movi v13.2d, #0
    movi v14.2d, #0
    movi v15.2d, #0
    movi v16.2d, #0
    movi v17.2d, #0
    movi v18.2d, #0
    movi v19.2d, #0
    movi v20.2d, #0
    movi v21.2d, #0
    movi v22.2d, #0
    movi v23.2d, #0
    movi v24.2d, #0
    movi v25.2d, #0
    movi v26.2d, #0
    movi v27.2d, #0
    movi v28.2d, #0
    movi v29.2d, #0
    movi v30.2d, #0
    movi v31.2d, #0
1:
    ldp q0, q1, [x19]
    ldp q2, q3, [x19, #32]
    ldp q4, q5, [x19, #64]
    ldp q6, q7, [x19, #96]
    ldp x0, x1, [x19, #128]
    ldp x2, x3, [x19, #144]
    ldp x16, x17, [x19, #160]
    msr nzcv, x16
    msr fpcr, x17
    msr fpsr, xzr
    ldr x16, [x19, #176]
    cbz x16, 2f
    add x1, x19, #256
2:
    .inst 0xE7F0A001
    .inst 0xE7F0A002
    .inst 0xE7F0A003
    .inst 0xE7F0A004
    mrs x16, nzcv
    mrs x17, fpsr
    str q0, [x20]
    str x0, [x20, #16]
    stp x16, x17, [x20, #24]
    ldr x16, [x19, #176]
    cbz x16, 3f
    sub x1, x1, x19
3:
    str x1, [x20, #40]
    ldp x16, x17, [x19, #192]
    stp x16, x17, [x20, #48]
    ldp x16, x17, [x19, #208]
    stp x16, x17, [x20, #64]
    ldp x16, x17, [x19, #224]
    stp x16, x17, [x20, #80]
    ldp x16, x17, [x19, #240]
    stp x16, x17, [x20, #96]
    ldp x16, x17, [x19, #256]
    stp x16, x17, [x20, #112]
    ldp x16, x17, [x19, #272]
    stp x16, x17, [x20, #128]
    ldp x16, x17, [x19, #288]
    stp x16, x17, [x20, #144]
    ldp x16, x17, [x19, #304]
    stp x16, x17, [x20, #160]
    ldp x16, x17, [x19, #320]
    stp x16, x17, [x20, #176]
    ldp x16, x17, [x19, #336]
    stp x16, x17, [x20, #192]
    ldp x16, x17, [x19, #352]
    stp x16, x17, [x20, #208]
    ldp x16, x17, [x19, #368]
    stp x16, x17, [x20, #224]
    add x19, x19, #384
    add x20, x20, #240
    subs x21, x21, #1
    b.ne 1b
    msr fpcr, x22
    ldp d14, d15, [sp, #96]
    ldp d12, d13, [sp, #80]
    ldp d10, d11, [sp, #64]
    ldp d8, d9, [sp, #48]
    ldp x21, x22, [sp, #32]
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #160
    ret
