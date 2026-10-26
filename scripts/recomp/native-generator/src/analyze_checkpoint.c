/* SPDX-License-Identifier: MIT. Full-analysis JSON for frozen-reference comparisons. */
#include "analysis.h"
#include "workers.h"
#include <inttypes.h>
#include <string.h>
#include <stdlib.h>
static void addresses(Buffer *out,const Addresses *a) {
    cg_buffer(out,"[",1);for(size_t i=0;i<a->size;i++)cg_printf(out,"%s%" PRIu64,i?",":"",a->items[i]);cg_buffer(out,"]",1);
}
int cg_analyze_checkpoint(int argc,char **argv) {
    cg_phase="analyze";
    if(argc<2)cg_fail(2,"analyze requires an NSO and module name");
    const char *path=argv[0],*offsets=NULL;cg_module=argv[1];
    uint64_t base=0;bool have_base=false,portable=false;const char *jobs=getenv("BDSP_GEN_JOBS");Addresses extra={0};
    for(int i=2;i<argc;i++) {
        const char *option=argv[i];if(!strcmp(option,"--events=jsonl"))continue;
        if(++i==argc)cg_fail(2,"missing analysis option value");
        if(!strcmp(option,"--base")) {base=cg_number(argv[i]);have_base=true;}
        else if(!strcmp(option,"--jobs"))jobs=argv[i];
        else if(!strcmp(option,"--entry-offsets"))offsets=argv[i];
        else if(!strcmp(option,"--setjmp-at"))cg_address(&extra,cg_number(argv[i]));
        else if(!strcmp(option,"--simd")) {if(strcmp(argv[i],"asm")&&strcmp(argv[i],"c"))cg_fail(2,"SIMD mode must be asm or c");portable=!strcmp(argv[i],"c");}
        else cg_fail(2,"unknown analysis option");
    }
    if(!have_base)cg_fail(2,"analyze requires --base");
#ifndef BDSP_WITH_UNICORN
    cg_fail(10,"complete analysis requires Unicorn 2.1.4 C headers and shared library");
#endif
    Nso n=cg_nso(path);cg_phase="analyze";ModuleAnalysis result=cg_analyze_module(&n,base,portable,&extra,offsets,cg_choose_jobs(jobs));
    Buffer out={0};cg_printf(&out,"{\"rounds\":%zu,\"functions\":[",result.rounds);
    for(size_t i=0;i<result.count;i++) {
        const FunctionPlan *f=result.functions[i];
        cg_printf(&out,"%s{\"entry\":%" PRIu64 ",\"end\":%" PRIu64 ",\"labels\":",i?",":"",f->entry,f->end);addresses(&out,&f->labels);
        cg_buffer(&out,",\"tables\":[",strlen(",\"tables\":["));
        for(size_t j=0;j<f->table_count;j++) {
            const JumpTable *t=&f->tables[j];cg_printf(&out,"%s[%" PRIu64 ",",j?",":"",t->pc);
            if(t->all)cg_json_string(&out,"all");else addresses(&out,&t->targets);cg_buffer(&out,"]",1);
        }
        cg_buffer(&out,"]}",2);
    }
    cg_printf(&out,"],\"jumptables\":%zu,\"br_all_labels\":%zu,\"br_dispatch\":%zu,\"nle\":",result.jump_tables,result.all_label_branches,result.dispatch_branches);
    Addresses nle={0};for(size_t i=0;i<result.initial.landing_pads.size;i++)cg_address(&nle,result.initial.landing_pads.items[i]);
    for(size_t i=0;i<result.initial.returns.size;i++)cg_address(&nle,result.initial.returns.items[i]);cg_unique(&nle);addresses(&out,&nle);
    cg_buffer(&out,"}\n",2);if(fwrite(out.data,1,out.size,stdout)!=out.size||fflush(stdout))cg_fail(5,"cannot write analysis result");return 0;
}
