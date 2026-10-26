/* SPDX-License-Identifier: MIT. Whole-module chunking follows frozen eh_gen.py. */
#include "analysis.h"
#include "workers.h"
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint64_t address; char *code; size_t size; Addresses refs; bool eh; } OwnedFunction;
static void *resize(void *old,size_t count,size_t size) {
    if(size&&count>SIZE_MAX/size)cg_fail(4,"generation buffer overflow");
    void *p=realloc(old,count*size);if(!p&&count)cg_fail(4,"not enough memory for emitted chunks");return p;
}
static void append(Buffer *b,const void *data,size_t size) {
    if(size>SIZE_MAX-b->size)cg_fail(4,"emitted chunk size overflow");
    size_t needed=b->size+size;
    if(needed>b->capacity) {size_t capacity=b->capacity?b->capacity:256;while(capacity<needed) {if(capacity>SIZE_MAX/2) {capacity=needed;break;}capacity*=2;}b->data=resize(b->data,capacity,1);b->capacity=capacity;}
    memcpy(b->data+b->size,data,size);b->size=needed;
}
static void address(Addresses *a,uint64_t value) {
    if(a->size==a->capacity) {a->capacity=a->capacity?a->capacity*2:64;a->items=resize(a->items,a->capacity,sizeof(*a->items));}
    a->items[a->size++]=value;
}
static void name(Strings *s,const char *text) {
    if(s->size==s->capacity) {s->capacity=s->capacity?s->capacity*2:16;s->items=resize(s->items,s->capacity,sizeof(*s->items));}
    size_t size=strlen(text)+1;char *copy=resize(NULL,size,1);memcpy(copy,text,size);s->items[s->size++]=copy;
}
static int name_order(const void *a,const void *b) {return strcmp(*(const char*const*)a,*(const char*const*)b);}
static size_t lower(const Addresses *a,uint64_t value) {
    size_t lo=0,hi=a->size;while(lo<hi) {size_t mid=lo+(hi-lo)/2;if(a->items[mid]<value)lo=mid+1;else hi=mid;}return lo;
}
static bool member(const Addresses *a,uint64_t value) {size_t i=lower(a,value);return i<a->size&&a->items[i]==value;}
static OwnedFunction emit(const Nso *n,uint64_t base,bool portable,const FunctionPlan *f,const Addresses *nle,const char *hle) {
    void *mark=cg_mark();size_t start=lower(nle,f->entry),end=lower(nle,f->end);
    EmitFunction input={.nso=n,.base=base,.entry=f->entry,.end=f->end,.portable=portable,.hle=hle,
        .labels=f->labels,.tables=f->tables,.table_count=f->table_count,.nle={nle->items?nle->items+start:NULL,end-start,end-start}};
    EmittedFunction generated=cg_emit_function(&input);
    OwnedFunction out={.address=f->entry,.size=generated.code.size,.code=resize(NULL,generated.code.size,1)};
    memcpy(out.code,generated.code.data,generated.code.size);
    if(generated.refs.size) {out.refs.items=resize(NULL,generated.refs.size,sizeof(*out.refs.items));out.refs.size=out.refs.capacity=generated.refs.size;memcpy(out.refs.items,generated.refs.items,generated.refs.size*sizeof(*out.refs.items));}
    cg_rewind(mark);return out;
}
static void release(OwnedFunction *f) {free(f->code);free(f->refs.items);*f=(OwnedFunction){0};}
static Strings lines(const char *path) {
    Strings result={0};if(!path)return result;Buffer file=cg_read(path);char *p=(char*)file.data;
    while(*p) {
        char *end=strchr(p,'\n');if(end)*end=0;char *begin=p;
        while(isspace((unsigned char)*begin))begin++;
        size_t length=strlen(begin);while(length&&isspace((unsigned char)begin[length-1]))begin[--length]=0;
        if(length&&*p!='#')cg_push(&result,begin);
        if(!end)break;p=end+1;
    }
    return result;
}
static Addresses offsets(const char *path,uint64_t base) {
    Addresses result={0};if(!path)return result;Buffer file=cg_read(path);char *p=(char*)file.data;
    while(*p) {
        while(isspace((unsigned char)*p))p++;if(!*p)break;
        if(*p=='-'||*p=='+')cg_fail(2,"invalid partial-build function offset");
        char *end;errno=0;uintmax_t value=strtoumax(p,&end,16);
        if(errno||p==end||(*end&&!isspace((unsigned char)*end))||value>UINT64_MAX-base)cg_fail(2,"invalid partial-build function offset");
        cg_address(&result,base+value);p=end;
    }
    cg_unique(&result);return result;
}
static const char *hle_at(const Bindings *mapping,const Strings *names,uint64_t entry) {
    uint64_t index;if(!cg_get(mapping,cg_format("%" PRIx64,entry),&index))return NULL;
    if(!names->items||index>=names->size)cg_fail(4,"invalid HLE mapping index");
    return names->items[index];
}
typedef struct {
    const Nso *nso; uint64_t base; bool portable; FunctionPlan **order;
    const Addresses *nle; const Bindings *hle_map; const Strings *hle_names;
    const char *module; bool events;
} EmitWork;
static void *emit_work(void *context,size_t index) {
    EmitWork *work=context;cg_phase="emit";cg_module=work->module;cg_events=work->events;
    void *mark=cg_mark();FunctionPlan *item=work->order[index];const char *hle=hle_at(work->hle_map,work->hle_names,item->entry);
    OwnedFunction *f=resize(NULL,1,sizeof(*f));*f=emit(work->nso,work->base,work->portable,item,work->nle,hle);
    f->eh=!hle&&lower(work->nle,item->entry)<lower(work->nle,item->end);cg_rewind(mark);return f;
}
static void dispose_work(void *result) {OwnedFunction *f=result;release(f);free(f);}
int cg_generate(int argc,char **argv) {
    cg_phase="generate";
    if(argc<4)cg_fail(2,"gen requires module, NSO, base and output folder");
    const char *module=argv[0],*source=argv[1],*out=argv[3],*hle_file=NULL,*only_file=NULL,*entry_offsets=NULL;
    if(!(*module=='_'||isalpha((unsigned char)*module)))cg_fail(2,"module name must be a C identifier");
    for(const char *p=module;*p;p++)if(!(*p=='_'||isalnum((unsigned char)*p)))cg_fail(2,"module name must be a C identifier");
    cg_module=module;uint64_t base=cg_number(argv[2]),chunk=1500,chunk_bytes=1500000,big_fn=100000,window=0x8000,limit=0;
#if defined(__aarch64__) || defined(_M_ARM64)
    bool portable=false;
#else
    bool portable=true;
#endif
    const char *job_option=getenv("BDSP_GEN_JOBS");
    Addresses setjmp={0};
    for(int i=4;i<argc;i++) {
        const char *option=argv[i];if(!strcmp(option,"--events=jsonl"))continue;
        if(++i==argc)cg_fail(2,"missing generator option value");
        if(!strcmp(option,"--hle"))hle_file=argv[i];
        else if(!strcmp(option,"--only"))only_file=argv[i];
        else if(!strcmp(option,"--entry-offsets"))entry_offsets=argv[i];
        else if(!strcmp(option,"--setjmp-at"))cg_address(&setjmp,cg_number(argv[i]));
        else if(!strcmp(option,"--chunk"))chunk=cg_number(argv[i]);
        else if(!strcmp(option,"--chunk-bytes"))chunk_bytes=cg_number(argv[i]);
        else if(!strcmp(option,"--big-fn"))big_fn=cg_number(argv[i]);
        else if(!strcmp(option,"--window"))window=cg_number(argv[i]);
        else if(!strcmp(option,"--limit"))limit=cg_number(argv[i]);
        else if(!strcmp(option,"--jobs"))job_option=argv[i];
        else if(!strcmp(option,"--simd")) {if(strcmp(argv[i],"asm")&&strcmp(argv[i],"c"))cg_fail(2,"SIMD mode must be asm or c");portable=!strcmp(argv[i],"c");}
        else cg_fail(2,"unknown generator option");
    }
    if(!chunk||!chunk_bytes)cg_fail(2,"chunk size and function count must be positive");
#ifndef BDSP_WITH_UNICORN
    cg_fail(10,"complete generation requires Unicorn 2.1.4 C headers and shared library");
#endif
    size_t jobs=cg_choose_jobs(job_option);
    fprintf(stderr,"%s: generator workers %zu\n",module,jobs);
    Nso n=cg_nso(source);cg_phase="analyze";ModuleAnalysis plan=cg_analyze_module(&n,base,portable,&setjmp,entry_offsets,jobs);
    Bindings wanted={0},hle_map={0};Strings hle_names={0},requested=lines(hle_file);
    for(size_t i=0;i<requested.size;i++)cg_set(&wanted,requested.items[i],1);
    for(size_t i=0;i<n.symbol_count;i++) {Symbol s=n.symbols[i];uint64_t ignored;
        if(s.section&&cg_get(&wanted,s.name,&ignored)&&s.value<=UINT64_MAX-base) {cg_push(&hle_names,s.name);cg_set(&hle_map,cg_format("%" PRIx64,base+s.value),hle_names.size-1);}
    }
    Addresses nle={0};for(size_t i=0;i<plan.initial.landing_pads.size;i++)cg_address(&nle,plan.initial.landing_pads.items[i]);
    for(size_t i=0;i<plan.initial.returns.size;i++)cg_address(&nle,plan.initial.returns.items[i]);cg_unique(&nle);
    FunctionPlan **order=cg_alloc(plan.count,sizeof(*order));size_t count=0,available=limit&&limit<plan.count?(size_t)limit:plan.count;
    Addresses only=offsets(only_file,base);
    for(size_t i=0;i<available;i++)if(!only_file||member(&only,plan.functions[i]->entry))order[count++]=plan.functions[i];
    if(only_file&&only.size>count)fprintf(stderr,"%s: --only: %zu starts are not function starts\n",module,only.size-count);
    cg_phase="emit";cg_mkdirs(out);size_t ci=0,nchunks=0,sub=0,eh_count=0,reported=0;uint64_t last_window=UINT64_MAX;
    EmitWork work={&n,base,portable,order,&nle,&hle_map,&hle_names,module,cg_events};
    CgPool *pool=jobs>1&&count?cg_pool_open(jobs,count,emit_work,&work,dispose_work):NULL;
    OwnedFunction pending={0};Addresses all_refs={0};Strings written={0};uint64_t text_lo=base+n.segments[0].offset;
    while(ci<count||pending.code) {
        void *mark=cg_mark();Buffer body={0};Addresses refs={0},functions={0};
        while((ci<count||pending.code)&&functions.size<chunk&&body.size<chunk_bytes) {
            uint64_t next=pending.code?pending.address:order[ci]->entry;
            if(!pending.code&&functions.size&&window&&(next-text_lo)/window!=(functions.items[0]-text_lo)/window)break;
            OwnedFunction f;
            if(pending.code) {f=pending;pending=(OwnedFunction){0};}
            else {
                OwnedFunction *result=pool?cg_pool_next(pool):emit_work(&work,ci);
                f=*result;free(result);ci++;if(f.eh)eh_count++;
            }
            if(f.size>big_fn&&functions.size) {pending=f;break;}
            append(&body,f.code,f.size);address(&functions,f.address);
            for(size_t i=0;i<f.refs.size;i++)address(&refs,f.refs.items[i]);
            bool big=f.size>big_fn;release(&f);if(big)break;
        }
        cg_unique(&refs);uint64_t win=window?(functions.items[0]-text_lo)/window:0;
        sub=win==last_window?sub+1:0;last_window=win;
        const char *filename=cg_format("%s_%05" PRIx64 "_%zu.c",module,win,sub);name(&written,filename);
        Buffer header={0};cg_printf(&header,"#include \"cpu.h\"\n%s",portable?"#include \"simd.h\"\n":"");
        for(size_t i=0;i<refs.size;i++) {cg_printf(&header,"void f_%" PRIx64 "(Cpu *c);\n",refs.items[i]);address(&all_refs,refs.items[i]);}
        for(size_t i=0;i<functions.size;i++) {const char *hle=hle_at(&hle_map,&hle_names,functions.items[i]);if(hle)cg_printf(&header,"void %s(Cpu *c);\n",cg_hle_name(hle));}
        cg_buffer(&header,body.data,body.size);cg_write(cg_join(out,filename),header.data,header.size);
        nchunks++;
        if(ci>reported&&(ci-reported>=1024||ci==count)) {
            fprintf(stderr,"%s: progress %zu/%zu files %zu\n",module,ci,count,nchunks);reported=ci;
        }
        free(body.data);free(refs.items);free(functions.items);cg_rewind(mark);
    }
    cg_pool_close(pool);
    if(written.size>1)qsort(written.items,written.size,sizeof(*written.items),name_order);cg_prune_chunks(out,module,&written);
    Buffer table={0};cg_buffer(&table,"#include \"cpu.h\"\n",strlen("#include \"cpu.h\"\n"));
    for(size_t i=0;i<count;i++)cg_printf(&table,"void f_%" PRIx64 "(Cpu *c);\n",order[i]->entry);
    cg_printf(&table,"const uint64_t %s_fn_addrs[] = {\n",module);
    for(size_t i=0;i<count;i++)cg_printf(&table,"%s0x%" PRIx64 "ull",i?",\n":"",order[i]->entry);
    cg_printf(&table,"};\nconst GuestFn %s_fn_ptrs[] = {\n",module);
    for(size_t i=0;i<count;i++)cg_printf(&table,"%sf_%" PRIx64,i?",\n":"",order[i]->entry);
    cg_printf(&table,"};\nconst uint64_t %s_fn_count = %zu;\n",module,count);cg_write(cg_join(out,cg_format("%s_table.c",module)),table.data,table.size);
    if(only_file) {
        cg_unique(&all_refs);Buffer stubs={0};cg_buffer(&stubs,"#include \"cpu.h\"\n",strlen("#include \"cpu.h\"\n"));
        for(size_t i=0;i<all_refs.size;i++) {uint64_t a=all_refs.items[i];size_t lo=0,hi=count;while(lo<hi) {size_t mid=lo+(hi-lo)/2;if(order[mid]->entry<a)lo=mid+1;else hi=mid;}
            if(lo==count||order[lo]->entry!=a)cg_printf(&stubs,"void f_%" PRIx64 "(Cpu *c) { c->pc = 0x%" PRIx64 "ull; rt_dispatch(c); }\n",a,a);
        }
        cg_write(cg_join(out,cg_format("%s_stubs.c",module)),stubs.data,stubs.size);
    }
    fprintf(stderr,"%s: wrote %zu chunks\n",module,nchunks);
    fprintf(stderr,"eh_gen: functions=%zu chunks=%zu eh_functions=%zu jumptables=%zu br_all_labels=%zu br_dispatch=%zu\n",count,nchunks,eh_count,plan.jump_tables,plan.all_label_branches,plan.dispatch_branches);
    for(size_t i=0;i<written.size;i++)free(written.items[i]);free(written.items);free(all_refs.items);return 0;
}
