/* SPDX-License-Identifier: MIT. Ordered CFG/Unicorn analysis from Module + EH extension. */
#include "analysis.h"
#include "workers.h"
#include "lifter_internal.h"
#include <stdlib.h>
#include <string.h>
#ifdef BDSP_WITH_UNICORN
#include <unicorn/unicorn.h>
#if UC_API_MAJOR != 2 || UC_API_MINOR != 1 || UC_API_PATCH != 4
#error Native analysis requires Unicorn 2.1.4
#endif
#endif
#define SCRATCH UINT64_C(0x7300000000)
typedef struct { unsigned char kind; bool negative; uint64_t target; } Classified;
typedef struct { uint64_t pc; Addresses targets; bool resolved; } WideTable;
typedef struct {
    const Nso *nso; uint64_t base, lo, hi; bool portable, no_unwind;
    Classified *classes; void *engine;
    Bindings wide_index; WideTable **wide; size_t wide_count, wide_capacity;
    size_t jump_tables, all_labels, dispatch;
} ScanModule;
static bool member(const Addresses *a,uint64_t value) {
    size_t lo=0,hi=a->size;
    while(lo<hi) {size_t mid=lo+(hi-lo)/2;if(a->items[mid]<value)lo=mid+1;else hi=mid;}
    return lo<a->size&&a->items[lo]==value;
}
static bool inside(const ScanModule *m,uint64_t a) {return a>=m->lo&&a<m->hi&&!(a&3);}
static uint32_t word(const ScanModule *m,uint64_t a) {
    if(!inside(m,a))cg_fail(4,"analysis instruction outside module text");
    return cg_u32(m->nso->image+(size_t)(a-m->base));
}
static Classified classify(ScanModule *m,uint64_t pc) {
    size_t index=(size_t)((pc-m->lo)/4);
    if(!inside(m,pc))cg_fail(4,"classification outside text");
    if(!m->classes[index].kind) {
        void *mark=cg_mark();
        Instruction ins=cg_lift_basic(word(m,pc),pc,m->portable,pc>m->lo,pc>m->lo?word(m,pc-4):0);
        if(ins.kind==CG_PENDING)cg_fail(4,"native analysis encountered an unimplemented instruction family");
        m->classes[index]=(Classified){(unsigned char)(ins.kind+1),ins.negative_target,ins.target};
        cg_rewind(mark);
    }
    Classified result=m->classes[index];result.kind--;return result;
}
static bool linear(Classified c) {return c.kind==CG_OP||c.kind==CG_ASM;}
#ifdef BDSP_WITH_UNICORN
static uc_engine *active_engine;
static bool registered_engine;
static void close_engine(void) {if(active_engine) {uc_close(active_engine);active_engine=NULL;}}
static uc_engine *emulator(ScanModule *m) {
    if(m->engine)return m->engine;
    unsigned major=0,minor=0,version=uc_version(&major,&minor);
    if(major!=2||minor!=1||((version>>8)&255)!=4)cg_fail(10,"native Unicorn library version differs from pinned 2.1.4");
    uc_engine *mu=NULL;
    if(uc_open(UC_ARCH_ARM64,UC_MODE_ARM,&mu)!=UC_ERR_OK)cg_fail(4,"cannot create native Unicorn engine");
    active_engine=mu;
    if(!registered_engine) {if(atexit(close_engine))cg_fail(4,"cannot register Unicorn cleanup");registered_engine=true;}
    uint64_t cpacr=0x300000;
    if(uc_mem_map(mu,m->base,m->nso->size,UC_PROT_ALL)!=UC_ERR_OK||
       uc_mem_write(mu,m->base,m->nso->image,m->nso->size)!=UC_ERR_OK||
       uc_mem_map(mu,SCRATCH,0x100000,UC_PROT_ALL)!=UC_ERR_OK||
       uc_reg_write(mu,UC_ARM64_REG_CPACR_EL1,&cpacr)!=UC_ERR_OK)cg_fail(4,"cannot initialize Unicorn module memory");
    m->engine=mu;return mu;
}
static bool step_to(uc_engine *mu,uint64_t from,uint64_t to) {
    uint64_t pc=from;
    for(unsigned i=0;i<64;i++) {
        if(pc==to)return true;
        if(uc_emu_start(mu,pc,0,0,1)!=UC_ERR_OK||uc_reg_read(mu,UC_ARM64_REG_PC,&pc)!=UC_ERR_OK)return false;
    }
    return false;
}
static int target_register(unsigned r) {return r<29?UC_ARM64_REG_X0+(int)r:(r==29?UC_ARM64_REG_X29:UC_ARM64_REG_X30);}
static bool emulate(ScanModule *m,uint64_t br,uint64_t entry,uint64_t end,uint64_t start,uint64_t set_at,uint32_t indexes,unsigned count,Addresses *targets) {
    uc_engine *mu=emulator(m);unsigned rn=bits(word(m,br),5,5);
    for(unsigned i=0;i<count;i++) {
        uint64_t scratch=SCRATCH+0x80000;
        for(unsigned r=0;r<29;r++)if(uc_reg_write(mu,UC_ARM64_REG_X0+(int)r,&scratch)!=UC_ERR_OK)return false;
        if(uc_reg_write(mu,UC_ARM64_REG_SP,&scratch)!=UC_ERR_OK)return false;
        for(uint64_t a=entry;a<start;a+=4) {
            uint32_t w=word(m,a);
            if(((w&0x1f000000)==0x10000000||(w&0xff800000)==0x91000000)&&uc_emu_start(mu,a,0,0,1)!=UC_ERR_OK)return false;
        }
        if(set_at!=start&&!step_to(mu,start,set_at))return false;
        uint64_t value=i;
        for(unsigned r=0;r<32;r++)if(indexes&(UINT32_C(1)<<r)) {
            /* Preserve the frozen Python _set_index mapping for registers >=29. */
            int reg_id=r<29?UC_ARM64_REG_X0+(int)r:UC_ARM64_REG_X29;
            if(uc_reg_write(mu,reg_id,&value)!=UC_ERR_OK)return false;
        }
        if(!step_to(mu,set_at,br))return false;
        uint64_t target;
        if(uc_reg_read(mu,target_register(rn),&target)!=UC_ERR_OK||target<entry||target>=end||(target&3))return false;
        cg_address(targets,target);
    }
    cg_unique(targets);return true;
}
#else
static bool emulate(ScanModule *m,uint64_t br,uint64_t entry,uint64_t end,uint64_t start,uint64_t set_at,uint32_t indexes,unsigned count,Addresses *targets) {
    (void)m;(void)br;(void)entry;(void)end;(void)start;(void)set_at;(void)indexes;(void)count;(void)targets;
    cg_fail(10,"native Unicorn C dependency missing; rebuild with the pinned Unicorn package");
}
#endif
static uint32_t index_registers(ScanModule *m,uint64_t start,uint64_t at,unsigned idx) {
    uint32_t registers=UINT32_C(1)<<idx;bool changed=true;
    while(changed) {
        changed=false;
        for(uint64_t a=start;a<at;a+=4) {
            uint32_t w=word(m,a);unsigned rd=w&31,src=31;
            if((w&0x7f800000)==0x12000000||(w&0x7f800000)==0x53000000||(w&0x7f800000)==0x13000000)src=bits(w,5,5);
            else if((w&0x7fe0ffe0)==0x2a0003e0)src=bits(w,16,5);
            if(src>=31||rd>=31)continue;
            uint32_t mask=(UINT32_C(1)<<src)|(UINT32_C(1)<<rd);
            if((registers&mask)&&(registers&mask)!=mask) {registers|=mask;changed=true;}
        }
    }
    return registers;
}
static bool fallthrough_table(ScanModule *m,uint64_t br,uint64_t entry,uint64_t end,Addresses *targets) {
    uint64_t guard=0,cmp=0;bool have_guard=false,have_cmp=false;
    for(unsigned back=1;back<=16&&br>=entry+(uint64_t)back*4;back++) {
        uint64_t a=br-(uint64_t)back*4;uint32_t w=word(m,a);unsigned condition=bits(w,0,4);
        if((w&0xff000010)==0x54000000&&(condition==8||condition==2)) {guard=a;have_guard=true;break;}
        unsigned k=classify(m,a).kind;
        if(k==CG_B||k==CG_BL||k==CG_BLR||k==CG_BR||k==CG_RET||k==CG_TRAP)return false;
    }
    if(!have_guard)return false;
    for(unsigned back=1;back<=8&&guard>=entry+(uint64_t)back*4;back++) {
        uint64_t a=guard-(uint64_t)back*4;uint32_t w=word(m,a);
        if((w&0x7f80001f)==0x7100001f) {cmp=a;have_cmp=true;break;}
        if(classify(m,a).kind!=CG_OP)return false;
    }
    if(!have_cmp)return false;
    uint32_t cw=word(m,cmp);if(bits(cw,22,1))return false;
    unsigned count=bits(cw,10,12)+(bits(word(m,guard),0,4)==8?1u:0u);
    if(!count||count>4096)return false;
    uint64_t start=cmp;
    while(start>=entry+4&&cmp-(start-4)<=48&&linear(classify(m,start-4)))start-=4;
    uint32_t indexes=index_registers(m,start,cmp,bits(cw,5,5));
    return emulate(m,br,entry,end,start,cmp,indexes,count,targets);
}
static bool taken_table(ScanModule *m,uint64_t br,uint64_t entry,uint64_t end,Addresses *targets) {
    uint64_t start=br;
    while(start>=entry+4&&br-(start-4)<=48&&linear(classify(m,start-4)))start-=4;
    for(uint64_t g=entry;g<end;g+=4) {
        uint32_t w=word(m,g);unsigned cond=bits(w,0,4);
        if((w&0xff000010)!=0x54000000||(cond!=9&&cond!=3))continue;
        uint64_t target=g+(uint64_t)(sext(bits(w,5,19),19)*4);if(target!=start)continue;
        uint32_t cw=g>=entry+4?word(m,g-4):0;
        if((cw&0x7f80001f)!=0x7100001f||bits(cw,22,1))continue;
        unsigned count=bits(cw,10,12)+(cond==9?1u:0u);if(!count||count>4096)continue;
        return emulate(m,br,entry,end,start,start,UINT32_C(1)<<bits(cw,5,5),count,targets);
    }
    return false;
}
static bool jump_table(ScanModule *m,uint64_t br,uint64_t entry,uint64_t end,Addresses *targets) {
    if(fallthrough_table(m,br,entry,end,targets))return true;
    *targets=(Addresses){0};if(taken_table(m,br,entry,end,targets))return true;
    *targets=(Addresses){0};
    const char *key=cg_format("%" PRIx64,br);uint64_t index;
    if(!cg_get(&m->wide_index,key,&index)) {
        WideTable *wide=cg_alloc(1,sizeof(*wide));wide->pc=br;
        uint64_t context=br>=m->lo+0x1000?br-0x1000:m->lo;
        wide->resolved=fallthrough_table(m,br,context,m->hi,&wide->targets);
        if(!wide->resolved&&m->no_unwind) {
            wide->targets=(Addresses){0};
            wide->resolved=fallthrough_table(m,br,context,m->hi,&wide->targets);
            if(!wide->resolved) {wide->targets=(Addresses){0};wide->resolved=taken_table(m,br,context,m->hi,&wide->targets);}
        }
        if(m->wide_count==m->wide_capacity) {
            size_t cap=m->wide_capacity?m->wide_capacity*2:16;WideTable **next=cg_alloc(cap,sizeof(*next));
            if(m->wide_count)memcpy(next,m->wide,m->wide_count*sizeof(*next));m->wide=next;m->wide_capacity=cap;
        }
        index=m->wide_count++;m->wide[index]=wide;cg_set(&m->wide_index,key,index);
    }
    if(!m->wide||index>=m->wide_count)cg_fail(4,"invalid jump table cache index");
    WideTable *wide=m->wide[index];if(wide->resolved)*targets=wide->targets;return wide->resolved;
}
static bool computed_target(ScanModule *m,uint64_t br,uint64_t entry) {
    unsigned rn=bits(word(m,br),5,5);
    for(unsigned back=1;back<=16&&br>=entry+(uint64_t)back*4;back++) {
        uint64_t a=br-(uint64_t)back*4;if(!linear(classify(m,a)))return false;
        uint32_t w=word(m,a);
        if((w&31)==rn)return (w&0x1f000000)==0x0b000000||(w&0x9f000000)==0x10000000;
    }
    return false;
}
static FunctionPlan *scan(ScanModule *m,uint64_t entry,uint64_t end) {
    FunctionPlan *f=cg_alloc(1,sizeof(*f));f->entry=entry;f->end=end;cg_address(&f->labels,entry);
    bool terminated=false;size_t table_capacity=0;
    for(uint64_t pc=entry;pc<end;pc+=4) {
        Classified ins=classify(m,pc);
        if(ins.kind==CG_B||ins.kind==CG_BCOND) {
            if(!ins.negative&&ins.target>=entry&&ins.target<end)cg_address(&f->labels,ins.target);
            else if(!ins.negative&&inside(m,ins.target))cg_address(&f->external,ins.target);
        } else if(ins.kind==CG_BL) {
            if(!ins.negative&&inside(m,ins.target))cg_address(&f->external,ins.target);
        } else if(ins.kind==CG_BR) {
            Addresses targets={0};bool resolved=jump_table(m,pc,entry,end,&targets),all=false;
            if(resolved&&targets.size) {
                for(size_t j=0;j<targets.size;j++) {
                    uint64_t t=targets.items[j];cg_address(&f->labels,t);
                    if(t<entry||t>=end)cg_address(&f->external,t);
                }
                size_t valid=0;
                /* Wide-cache arrays stay immutable across subsequent scans. */
                Addresses local={0};for(size_t j=0;j<targets.size;j++)if(targets.items[j]>=entry&&targets.items[j]<end) {cg_address(&local,targets.items[j]);valid++;}
                targets=local;all=!valid;m->jump_tables++;
            } else if(computed_target(m,pc,entry)) {all=true;m->all_labels++;}
            else {m->dispatch++;goto classified_branch;}
            if(f->table_count==table_capacity) {
                size_t cap=table_capacity?table_capacity*2:4;JumpTable *next=cg_alloc(cap,sizeof(*next));
                if(f->table_count)memcpy(next,f->tables,f->table_count*sizeof(*next));f->tables=next;table_capacity=cap;
            }
            f->tables[f->table_count++]=(JumpTable){pc,targets,all};
        }
classified_branch:
        terminated=ins.kind==CG_B||ins.kind==CG_BR||ins.kind==CG_RET||ins.kind==CG_TRAP;
    }
    if(!terminated&&end<m->hi)cg_address(&f->external,end);
    size_t valid=0;for(size_t i=0;i<f->labels.size;i++)if(f->labels.items[i]>=entry&&f->labels.items[i]<end)f->labels.items[valid++]=f->labels.items[i];
    f->labels.size=valid;cg_unique(&f->labels);cg_unique(&f->external);return f;
}
typedef struct {ScanModule *module;uint64_t *entries,*ends;const char *name;bool events;} PureWork;
static void *pure_work(void *context,size_t index) {
    PureWork *work=context;ScanModule *m=work->module;cg_phase="scan";cg_module=work->name;cg_events=work->events;
    uint64_t entry=work->entries[index],end=work->ends[index];
    for(uint64_t pc=entry;pc<end;pc+=4)if(classify(m,pc).kind==CG_BR)return NULL;
    FunctionPlan *f=scan(m,entry,end),*owned=malloc(sizeof(*owned));
    if(!owned)cg_fail(4,"not enough memory for scan worker result");*owned=*f;
    owned->labels=(Addresses){0};owned->external=(Addresses){0};
    if(f->labels.size) {
        owned->labels.items=malloc(f->labels.size*sizeof(uint64_t));if(!owned->labels.items)cg_fail(4,"not enough memory for scan labels");
        memcpy(owned->labels.items,f->labels.items,f->labels.size*sizeof(uint64_t));owned->labels.size=owned->labels.capacity=f->labels.size;
    }
    if(f->external.size) {
        owned->external.items=malloc(f->external.size*sizeof(uint64_t));if(!owned->external.items)cg_fail(4,"not enough memory for scan references");
        memcpy(owned->external.items,f->external.items,f->external.size*sizeof(uint64_t));owned->external.size=owned->external.capacity=f->external.size;
    }
    return owned;
}
static void dispose_plan(void *value) {FunctionPlan *f=value;if(!f)return;free(f->labels.items);free(f->external.items);free(f);}
static FunctionPlan *retain_plan(FunctionPlan *source) {
    FunctionPlan *f=cg_alloc(1,sizeof(*f));*f=*source;
    f->labels.items=cg_alloc(source->labels.size,sizeof(uint64_t));f->labels.capacity=f->labels.size;
    if(f->labels.size)memcpy(f->labels.items,source->labels.items,f->labels.size*sizeof(uint64_t));
    f->external.items=cg_alloc(source->external.size,sizeof(uint64_t));f->external.capacity=f->external.size;
    if(f->external.size)memcpy(f->external.items,source->external.items,f->external.size*sizeof(uint64_t));
    dispose_plan(source);return f;
}
typedef struct {ScanModule *module;const char *name;bool events;} ClassWork;
static void *classify_work(void *context,size_t index) {
    ClassWork *work=context;ScanModule *m=work->module;cg_phase="classify";cg_module=work->name;cg_events=work->events;
    size_t start=index*16384,end=start+16384,count=m->nso->segments[0].size/4;if(end>count)end=count;
    for(size_t i=start;i<end;i++)classify(m,m->lo+i*4);return NULL;
}
ModuleAnalysis cg_analyze_module(const Nso *nso,uint64_t base,bool portable,const Addresses *setjmp,const char *offsets,size_t jobs) {
    ModuleAnalysis result={.initial=cg_initial_analysis(nso,base,setjmp,offsets)};
    ScanModule m={.nso=nso,.base=base,.lo=base+nso->segments[0].offset,.hi=base+nso->segments[0].offset+nso->segments[0].size,
        .portable=portable,.no_unwind=!nso->eh_start||nso->eh_start==nso->eh_end,.classes=cg_alloc(nso->segments[0].size/4,sizeof(Classified))};
    size_t classification_tasks=(nso->segments[0].size/4+16383)/16384;
    if(jobs>1&&classification_tasks) {
        ClassWork work={&m,cg_module,cg_events};
        if(classification_tasks>1) {
            CgPool *pool=cg_pool_open(jobs,classification_tasks,classify_work,&work,NULL);
            for(size_t i=0;i<classification_tasks;i++)cg_pool_next(pool);cg_pool_close(pool);
        } else classify_work(&work,0);
    }
    Addresses starts={0};
    for(size_t i=0;i<result.initial.entries.size;i++)cg_address(&starts,result.initial.entries.items[i]);
    Bindings scanned={0};FunctionPlan **cache=NULL;size_t count=0,capacity=0;
    for(;;) {
        result.rounds++;size_t before=starts.size;Addresses extra={0};
        FunctionPlan **current=cg_alloc(starts.size,sizeof(*current));
        uint64_t *missing_entries=cg_alloc(starts.size,sizeof(uint64_t)),*missing_ends=cg_alloc(starts.size,sizeof(uint64_t));size_t missing=0;
        unsigned char *scheduled=cg_alloc(starts.size,1);
        for(size_t i=0;i<starts.size;i++) {
            uint64_t entry=starts.items[i],end=i+1<starts.size?starts.items[i+1]:m.hi,index;
            if(cg_get(&scanned,cg_format("%" PRIx64 ":%" PRIx64,entry,end),&index)) {
                if(!cache||index>=count)cg_fail(4,"invalid function analysis cache index");
                current[i]=cache[index];
            }
            else if(jobs>1&&end-entry>=1024) {scheduled[i]=1;missing_entries[missing]=entry;missing_ends[missing++]=end;}
        }
        PureWork pure={&m,missing_entries,missing_ends,cg_module,cg_events};
        CgPool *pool=jobs>1&&missing?cg_pool_open(jobs,missing,pure_work,&pure,dispose_plan):NULL;
        for(size_t i=0;i<starts.size;i++) {
            uint64_t entry=starts.items[i],end=i+1<starts.size?starts.items[i+1]:m.hi;
            if(!current[i]) {
                FunctionPlan *owned=pool&&scheduled[i]?cg_pool_next(pool):NULL;
                FunctionPlan *f=owned?retain_plan(owned):scan(&m,entry,end);
                if(count==capacity) {size_t cap=capacity?capacity*2:256;FunctionPlan **next=cg_alloc(cap,sizeof(*next));if(count)memcpy(next,cache,count*sizeof(*next));cache=next;capacity=cap;}
                size_t index=count++;cache[index]=f;cg_set(&scanned,cg_format("%" PRIx64 ":%" PRIx64,entry,end),index);current[i]=f;
            }
            for(size_t j=0;j<current[i]->external.size;j++)if(!member(&starts,current[i]->external.items[j]))cg_address(&extra,current[i]->external.items[j]);
        }
        cg_pool_close(pool);
        cg_unique(&extra);
        fprintf(stderr,"%s: scan round %zu progress %zu/%zu\n",cg_module,result.rounds,starts.size,starts.size);
        if(!extra.size) {result.functions=current;result.count=starts.size;break;}
        for(size_t i=0;i<extra.size;i++)cg_address(&starts,extra.items[i]);cg_unique(&starts);
        if(starts.size<=before)cg_fail(4,"analysis fixpoint did not progress");
    }
#ifdef BDSP_WITH_UNICORN
    if(m.engine)close_engine();
#endif
    result.jump_tables=m.jump_tables;result.all_label_branches=m.all_labels;result.dispatch_branches=m.dispatch;return result;
}
