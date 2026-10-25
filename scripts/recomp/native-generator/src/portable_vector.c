/* SPDX-License-Identifier: MIT. AdvSIMD C-expression emission adapted from SimdC. */
#include "lifter_internal.h"
#include <string.h>
static const char *vu(unsigned s) { return (const char *const[]){"vu8","vu16","vu32","vu64"}[s]; }
static const char *vs(unsigned s) { return (const char *const[]){"vs8","vs16","vs32","vs64"}[s]; }
static const char *ut(unsigned s) { return (const char *const[]){"uint8_t","uint16_t","uint32_t","uint64_t"}[s]; }
static const char *vr(const char *t, unsigned n) { return cg_format("VREG(%s, %u)", t, n); }
static const char *vq(const char *t, unsigned q, unsigned n) { return q ? vr(t,n) : cg_format("VQ(%s, 0, %u)",t,n); }
static Instruction vw(const char *t,unsigned q,unsigned d,const char *e) { return op(cg_format("VW(%s, %u, %u, %s);",t,q,d,e)); }
static unsigned lanes(unsigned q,unsigned s) { return (8u << q) >> s; }
static const char *lop(const char *name,unsigned u) { return cg_format("LOP_%s%s",name,u?" | LOP_U":""); }
static Instruction gen(const char *o,unsigned s,unsigned ne,unsigned d,unsigned sd,unsigned od,unsigned keep,unsigned n,unsigned sn,unsigned on,int m,unsigned sm,unsigned om,int idx,uint64_t imm) {
    return op(cg_format("sl_gen(c, %s, %u, %u, %u, %u, %u, %u, %u, %u, %u, %d, %u, %u, %d, %s);",o,s,ne,d,sd,od,keep,n,sn,on,m,sm,om,idx,hex(imm)));
}
static Instruction same(const char *o,unsigned s,unsigned ne,unsigned d,unsigned n,int m,uint64_t imm,int idx) { return gen(o,s,ne,d,s,0,0,n,s,0,m,s,0,idx,imm); }
static const char *shuffle(const char *a,const char *b,const unsigned *indexes,unsigned count) {
    Buffer out={0};cg_printf(&out,"SHUF(%s, %s",a,b);
    for(unsigned i=0;i<count;i++)cg_printf(&out,", %u",indexes[i]);
    cg_buffer(&out,")",2);return (char*)out.data;
}
static void pair_indexes(unsigned q,unsigned s,unsigned *ev,unsigned *od) {
    unsigned ne=lanes(q,s),nl=16u>>s;
    for(unsigned k=0;k<nl;k++) {
        unsigned a=2*k,b=a+1;
        ev[k]=k<ne?(a<ne?a:nl+a-ne):ne%nl;
        od[k]=k<ne?(b<ne?b:nl+b-ne):ne%nl;
    }
}
static Instruction crypto(uint32_t w,uint64_t pc,unsigned family) {
    unsigned d=bits(w,0,5),n=bits(w,5,5),m=bits(w,16,5);
    if(bits(w,22,2))return unsupported(pc,family==0?"aes size":"sha size");
    unsigned opc=bits(w,12,family==1?3u:5u);
    if(family==0) {if(opc<4||opc>7)return unsupported(pc,"aes opcode");return op(cg_format("sv_aes(c, %u, %u, %u);",opc-4,d,n));}
    if(family==1) {
        if(opc<3)return op(cg_format("sv_sha1hash(c, %u, %u, %u, %u);",opc,d,n,m));
        if(opc==3||opc==6)return op(cg_format("sv_sha_misc(c, %u, %u, %u, %u);",opc==3?0u:3u,d,n,m));
        if(opc==4||opc==5)return op(cg_format("sv_sha256hash(c, %u, %u, %u, %u);",opc==4?1u:0u,d,n,m));
        return unsupported(pc,"sha3 opcode");
    }
    if(opc>2)return unsupported(pc,"sha2 opcode");
    return op(cg_format("sv_sha_misc(c, %u, %u, %u, 0);",(unsigned[]){4,1,2}[opc],d,n));
}
static Instruction copy(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),imm5=bits(w,16,5),imm4=bits(w,11,4),d=bits(w,0,5),n=bits(w,5,5);
    if(scalar&&(u||imm4))return unsupported(pc,"scalar copy");
    if(!(imm5&15))return unsupported(pc,"copy imm5");
    unsigned s=0;while(!(imm5&(1u<<s)))s++;
    unsigned idx=imm5>>(s+1);
    if(s>3)return unsupported(pc,scalar?"scalar dup size":"copy size");
    const char *p=(const char*const[]){"uint8_t","sa16","sa32","sa64"}[s],*t=vu(s);
    if(scalar)return op(cg_format("c->v[%u] = ((%s *)&c->v[%u])[%u];",d,p,n,idx));
    if(u) {if(!q)return unsupported(pc,"ins elem Q");return op(cg_format("((%s *)&c->v[%u])[%u] = ((%s *)&c->v[%u])[%u];",p,d,idx,p,n,imm4>>s));}
    if(imm4<=1) {
        if(s==3&&!q)return unsupported(pc,"dup 1d");
        if(imm4==1)return vw(t,q,d,cg_format("(%s){} + (%s)%s",t,ut(s),reg(true,n,false)));
        unsigned indexes[16];for(unsigned i=0;i<(16u>>s);i++)indexes[i]=idx;
        return vw(t,q,d,shuffle(vr(t,n),vr(t,n),indexes,16u>>s));
    }
    if(imm4==3) {if(!q)return unsupported(pc,"ins Q");return op(cg_format("((%s *)&c->v[%u])[%u] = (%s)%s;",p,d,idx,ut(s),reg(true,n,false)));}
    if(imm4==5) {
        if(s>=2+q)return unsupported(pc,"smov size");
        return op(set(q!=0,d,cg_format("(uint64_t)(int64_t)(%s)((%s *)&c->v[%u])[%u]",(const char*const[]){"int8_t","int16_t","int32_t"}[s],p,n,idx),false));
    }
    if(imm4==7) {if((q&&s!=3)||(!q&&s==3))return unsupported(pc,"umov size");return op(set(q!=0,d,cg_format("((%s *)&c->v[%u])[%u]",p,n,idx),false));}
    return unsupported(pc,"copy imm4");
}
static Instruction permutation(uint32_t w,uint64_t pc,unsigned family) {
    unsigned q=bits(w,30,1),s=bits(w,22,2),m=bits(w,16,5),opc=bits(w,12,3),n=bits(w,5,5),d=bits(w,0,5),idx[16]={0};
    if(family==2) {if(s)return unsupported(pc,"tbl op2");return op(cg_format("sv_tbl(c, %u, %u, %u, %u, %u, %u);",q,bits(w,13,2),bits(w,12,1),d,n,m));}
    if(family==1) {
        unsigned imm=bits(w,11,4);if(s||(!q&&imm>=8))return unsupported(pc,"ext");
        for(unsigned i=0;i<(q?16u:8u);i++)idx[i]=q||imm+i<8?imm+i:16+imm+i-8;
        return vw("vu8",q,d,shuffle(vr("vu8",n),vr("vu8",m),idx,16));
    }
    if(opc==0||opc==4||(s==3&&!q))return unsupported(pc,"permute");
    unsigned ne=lanes(q,s),nl=16u>>s,part=opc>>2,kind=opc&3;
    for(unsigned i=0;i<ne;i++) {
        if(kind==1) {unsigned j=2*i+part;idx[i]=j<ne?j:nl+j-ne;}
        else if(kind==2) {unsigned p=i&~1u;idx[i]=(i&1)?nl+p+part:p+part;}
        else {unsigned b=part*ne/2;idx[i]=(i&1)?nl+b+i/2:b+i/2;}
    }
    return vw(vu(s),q,d,shuffle(vr(vu(s),n),vr(vu(s),m),idx,nl));
}
static Instruction modified_immediate(uint32_t w,uint64_t pc) {
    unsigned q=bits(w,30,1),o=bits(w,29,1),cm=bits(w,12,4),d=bits(w,0,5),v=(bits(w,16,3)<<5)|bits(w,5,5),c=cm>>1;
    if(bits(w,11,1))return unsupported(pc,"fmov half imm");
    if(cm==15&&o&&!q)return unsupported(pc,"fmov 1d");
    uint64_t imm=0;
    if(c<4) {uint64_t x=(uint64_t)v<<(8*c);imm=(x<<32)|x;}
    else if(c<6) {uint64_t x=(uint64_t)v<<(c==5?8:0);for(unsigned shift=0;shift<64;shift+=16)imm|=x<<shift;}
    else if(c==6) {uint64_t x=(cm&1)?((uint64_t)v<<16)|0xffff:((uint64_t)v<<8)|0xff;imm=(x<<32)|x;}
    else if(!(cm&1)&&!o) {for(unsigned shift=0;shift<64;shift+=8)imm|=(uint64_t)v<<shift;}
    else if(!(cm&1)) {for(unsigned i=0;i<8;i++)if(v&(1u<<i))imm|=UINT64_C(0xff)<<(8*i);}
    else if(!o) {uint64_t x=fp_immediate(v,32);imm=(x<<32)|x;}
    else imm=fp_immediate(v,64);
    if(cm<12&&(cm&1))return vw("vu64",q,d,cg_format("%s %s %s",vr("vu64",d),o?"&":"|",hex(o?~imm:imm)));
    if(o&&cm!=14&&cm!=15)imm=~imm;
    const char *value=q&&imm?cg_format("((u128)%s << 64 | %s)",hex(imm),hex(imm)):hex(imm);
    return op(cg_format("c->v[%u] = %s;",d,value));
}
static const char *ff(unsigned s) {return s?"d":"s";}
static const char *ft(unsigned s) {return s?"vf64":"vf32";}
static const char *fu(unsigned s) {return s?"vu64":"vu32";}
static const char *fs(unsigned s) {return s?"VSF64":"VSF32";}
static const char *fset(unsigned s) {return s?"FP_SETD":"FP_SETS";}
static Instruction three_fp(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),a=bits(w,23,1),s=bits(w,22,1),m=bits(w,16,5),opc=bits(w,11,5),n=bits(w,5,5),d=bits(w,0,5);
    if(!scalar&&s&&!q)return unsupported(pc,"fp 2d Q");
    int cmp=-1;
    if(opc==28)cmp=!u?(a?-1:0):(a?2:1);
    else if(opc==29&&u)cmp=a?4:3;
    const char *f=ff(s),*t=ft(s),*sf=fs(s);
    if(cmp>=0) {
        if(scalar)return op(cg_format("c->v[%u] = (%s)vcmp_%s(c, %d, (%s){%s(%u)}, (%s){%s(%u)})[0];",d,ut(2+s),f,cmp,t,sf,n,t,sf,m));
        return vw(fu(s),q,d,cg_format("vcmp_%s(c, %d, %s, %s)",f,cmp,vq(t,q,n),vq(t,q,m)));
    }
    const char *fop=NULL;
    if(!u) {
        if(opc==24)fop=a?"FOP_MINNM":"FOP_MAXNM";
        if(opc==26)fop=a?"FOP_SUB":"FOP_ADD";
        if(opc==27&&!a)fop="FOP_MULX";
        if(opc==30)fop=a?"FOP_MIN":"FOP_MAX";
        if(opc==31)fop=a?"FOP_RSQRTS":"FOP_RECPS";
    } else {
        if(opc==27&&!a)fop="FOP_MUL";
        if(opc==31&&!a)fop="FOP_DIV";
        if(opc==26&&a)fop="FOP_ABD";
    }
    if(scalar) {
        if(!((!u&&!a&&(opc==27||opc==31))||(!u&&a&&opc==31)||(u&&a&&opc==26)))return unsupported(pc,"scalar fp 3same");
        const char *x=cg_format("%s(%u)",sf,n);
        if(opc==31)x=cg_format("neg_%s(%s)",f,x);
        return op(cg_format("%s(%u, op_%s(c, %s, %s, %s(%u), 0));",fset(s),d,f,fop,x,sf,m));
    }
    const char *left=vq(t,q,n),*right=vq(t,q,m),*pair=NULL;
    if(u&&(opc==24||opc==30||(opc==26&&!a)))pair=opc==24?(a?"FOP_MINNM":"FOP_MAXNM"):(opc==30?(a?"FOP_MIN":"FOP_MAX"):"FOP_ADD");
    if(pair) {unsigned ev[16],od[16];pair_indexes(q,2+s,ev,od);return op(cg_format("SV_FOP_%s(%s, %u, %u, %s, %s, (%s){});",s?"D":"S",pair,q,d,shuffle(left,right,ev,16u>>(2+s)),shuffle(left,right,od,16u>>(2+s)),t));}
    if(!u&&opc==25)return op(cg_format("SV_FOP_%s(FOP_MADD, %u, %u, %s, %s, %s);",s?"D":"S",q,d,vq(t,q,d),a?cg_format("vneg_%s(%s)",f,left):left,right));
    if(!fop)return unsupported(pc,"fp 3same opcode");
    if(!strcmp(fop,"FOP_RECPS")||!strcmp(fop,"FOP_RSQRTS"))left=cg_format("vneg_%s(%s)",f,left);
    return op(cg_format("SV_FOP_%s(%s, %u, %u, %s, %s, (%s){});",s?"D":"S",fop,q,d,left,right,t));
}
static Instruction three_same(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),s=bits(w,22,2),m=bits(w,16,5),opc=bits(w,11,5),n=bits(w,5,5),d=bits(w,0,5);
    if(opc>=24)return three_fp(w,pc,scalar);
    unsigned ne=scalar?1:lanes(q,s);
    if(scalar) {
        if(opc==1||opc==5)return same(lop(opc==1?(u?"UQADD":"SQADD"):(u?"UQSUB":"SQSUB"),0),s,1,d,n,(int)m,0,-1);
        if(opc==9||opc==11)return same(lop(opc==9?"QSHL":"QRSHL",u),s,1,d,n,(int)m,0,-1);
        if(opc==22) {if(s!=1&&s!=2)return unsupported(pc,"sqdmulh size");return same(lop(u?"SQRDMULH":"SQDMULH",0),s,1,d,n,(int)m,0,-1);}
        if(s!=3)return unsupported(pc,"scalar 3same size");
        const char *a=cg_format("VS64(%u)",n),*b=cg_format("VS64(%u)",m),*x=u?a:cg_format("(int64_t)%s",a),*y=u?b:cg_format("(int64_t)%s",b);
        if(opc==6||opc==7)return op(cg_format("c->v[%u] = (%s %s %s) ? ~0ull : 0;",d,x,opc==6?">":">=",y));
        if(opc==8||opc==10)return same(lop(opc==8?"SHL":"RSHL",u),3,1,d,n,(int)m,0,-1);
        if(opc==16)return op(cg_format("c->v[%u] = (uint64_t)(%s %s %s);",d,a,u?"-":"+",b));
        if(opc==17)return op(cg_format(u?"c->v[%u] = (%s == %s) ? ~0ull : 0;":"c->v[%u] = (%s & %s) ? ~0ull : 0;",d,a,b));
        return unsupported(pc,"scalar 3same opcode");
    }
    if(s==3&&!q&&opc!=3)return unsupported(pc,"3same 1d");
    const char *t=vu(s),*a=vr(t,n),*b=vr(t,m),*o=vr(t,d),*sa=vr(vs(s),n),*sb=vr(vs(s),m),*x=u?a:sa,*y=u?b:sb;
    if(s==3&&(opc==0||opc==2||opc==4||opc==14||opc==15||opc==12||opc==13))return unsupported(pc,"3same size");
    if(opc==0||opc==2||opc==4)return same(lop(opc==0?"HADD":(opc==2?"RHADD":"HSUB"),u),s,ne,d,n,(int)m,0,-1);
    if(opc==1||opc==5)return vw(t,q,d,cg_format("(%s)__builtin_elementwise_%s_sat(%s, %s)",t,opc==1?"add":"sub",x,y));
    if(opc==3) {
        a=vr("vu64",n);b=vr("vu64",m);o=vr("vu64",d);const char *e;
        if(!u)e=s==0?cg_format("%s & %s",a,b):(s==1?cg_format("%s & ~%s",a,b):(s==2?cg_format("%s | %s",a,b):cg_format("%s | ~%s",a,b)));
        else e=s==0?cg_format("%s ^ %s",a,b):(s==1?cg_format("(%s & %s) | (~%s & %s)",o,a,o,b):(s==2?cg_format("(%s & ~%s) | (%s & %s)",o,b,a,b):cg_format("(%s & %s) | (%s & ~%s)",o,b,a,b)));
        return vw("vu64",q,d,e);
    }
    if(opc==6||opc==7)return vw(t,q,d,cg_format("(%s)(%s %s %s)",t,x,opc==6?">":">=",y));
    if(opc>=8&&opc<=11)return same(lop((const char*const[]){"SHL","QSHL","RSHL","QRSHL"}[opc-8],u),s,ne,d,n,(int)m,0,-1);
    if(opc==12||opc==13)return vw(t,q,d,cg_format("(%s)__builtin_elementwise_%s(%s, %s)",t,opc==12?"max":"min",x,y));
    if(opc==14||opc==15) {const char *e=cg_format("(%s)__builtin_elementwise_max(%s, %s) - (%s)__builtin_elementwise_min(%s, %s)",t,x,y,t,x,y);return vw(t,q,d,opc==15?cg_format("%s + (%s)",o,e):e);}
    if(opc==16)return vw(t,q,d,cg_format("%s %s %s",a,u?"-":"+",b));
    if(opc==17)return vw(t,q,d,u?cg_format("(%s)(%s == %s)",t,a,b):cg_format("(%s)((%s & %s) != 0)",t,a,b));
    if(s==3&&opc!=23)return unsupported(pc,"3same size");
    if(opc==18)return vw(t,q,d,cg_format("%s %s %s * %s",o,u?"-":"+",a,b));
    if(opc==19) {if(u) {if(s)return unsupported(pc,"pmul size");return same(lop("PMUL",0),0,ne,d,n,(int)m,0,-1);}return vw(t,q,d,cg_format("%s * %s",a,b));}
    if(opc==20||opc==21||opc==23) {
        if(opc==23&&u)return unsupported(pc,"addp U");
        unsigned ev[16],od[16];pair_indexes(q,s,ev,od);const char *left=shuffle(u||opc==23?a:sa,u||opc==23?b:sb,ev,16u>>s),*right=shuffle(u||opc==23?a:sa,u||opc==23?b:sb,od,16u>>s);
        return vw(t,q,d,opc==23?cg_format("(%s)(%s + %s)",t,left,right):cg_format("(%s)__builtin_elementwise_%s(%s, %s)",t,opc==20?"max":"min",left,right));
    }
    if(opc==22) {if(s!=1&&s!=2)return unsupported(pc,"sqdmulh size");return same(lop(u?"SQRDMULH":"SQDMULH",0),s,ne,d,n,(int)m,0,-1);}
    return unsupported(pc,"3same opcode");
}
static Instruction three_diff(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),s=bits(w,22,2),m=bits(w,16,5),opc=bits(w,12,4),n=bits(w,5,5),d=bits(w,0,5);
    const char *ops[]={"ADDL","ADDW","SUBL","SUBW","ADDHN","ABAL","SUBHN","ABDL","MLAL","SQDMLAL","MLSL","SQDMLSL","MULL","SQDMULL","PMULL"};
    if(scalar) {if(u||(opc!=9&&opc!=11&&opc!=13)||(s!=1&&s!=2))return unsupported(pc,"scalar 3diff");return gen(lop(ops[opc],0),s,1,d,s+1,0,0,n,s,0,(int)m,s,0,-1,0);}
    if(opc==14) {if(u)return unsupported(pc,"pmull U");if(s==3)return op(cg_format("sl_pmull64(c, %u, %u, %u, %u);",q,d,n,m));if(s)return unsupported(pc,"pmull size");}
    if(s==3||opc==15)return unsupported(pc,"3diff size");
    unsigned ne=8u>>s,off=q*ne;
    if(opc==4||opc==6)return gen(lop((const char*const[]){"ADDHN","RADDHN","SUBHN","RSUBHN"}[(opc==6?2u:0u)+u],0),s,ne,d,s,off,q,n,s+1,0,(int)m,s+1,0,-1,0);
    if(opc==1||opc==3)return gen(lop(ops[opc],u),s,ne,d,s+1,0,0,n,s+1,0,(int)m,s,off,-1,0);
    bool sq=opc==9||opc==11||opc==13;
    if(sq&&(u||(s!=1&&s!=2)))return unsupported(pc,"sqdmull");
    return gen(lop(ops[opc],sq||opc==14?0u:u),s,ne,d,s+1,0,0,n,s,off,(int)m,s,off,-1,0);
}
static Instruction misc_fp(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),a=bits(w,23,1),s=bits(w,22,1),opc=bits(w,12,5),n=bits(w,5,5),d=bits(w,0,5);
    const char *f=ff(s),*t=ft(s),*sf=fs(s),*x=vq(t,q,n);
    if(opc==22||opc==23) {
        if(a)return unsupported(pc,"fcvtn a");
        if(opc==22&&u) {if(!s)return unsupported(pc,"fcvtxn size");if(scalar)return op(cg_format("FP_SETS(%u, simd_d2s_odd(c, VSF64(%u)));",d,n));return op(cg_format("sv_fcvtn(c, 1, %u, 1, %u, %u);",q,d,n));}
        if(scalar||u)return unsupported(pc,"fcvtn/l");
        return op(opc==22?cg_format("sv_fcvtn(c, %u, %u, 0, %u, %u);",s,q,d,n):cg_format("sv_fcvtl(c, %u, %u, %u, %u);",s,q,d,n));
    }
    if(!scalar&&s&&!q)return unsupported(pc,"fp misc 2d Q");
    if(opc>=12&&opc<=15) {
        if(!a)return unsupported(pc,"fp16 misc");
        if(opc==15) {if(scalar)return unsupported(pc,"scalar fabs");return vw(fu(s),q,d,cg_format("%s %s %s%s",vr(fu(s),n),u?"^":"&",u?"":"~",s?"0x8000000000000000ull":"0x80000000u"));}
        int cmp=-1;bool swap=false;
        if(opc==12)cmp=u?1:2;
        if(opc==13) {cmp=u?1:0;swap=u!=0;}
        if(opc==14&&!u) {cmp=2;swap=true;}
        if(cmp<0)return unsupported(pc,"fcm zero");
        const char *left=scalar?cg_format("(%s){%s(%u)}",t,sf,n):x,*right=cg_format("(%s){}",t);
        if(swap) {const char *tmp=left;left=right;right=tmp;}
        if(scalar)return op(cg_format("c->v[%u] = (%s)vcmp_%s(c, %d, %s, %s)[0];",d,ut(2+s),f,cmp,left,right));
        return vw(fu(s),q,d,cg_format("vcmp_%s(c, %d, %s, %s)",f,cmp,left,right));
    }
    if(opc==31) {
        if(!a)return unsupported(pc,"fp misc 11111");
        if(u) {if(scalar)return unsupported(pc,"scalar fsqrt");return op(cg_format("SV_FOP_%s(FOP_SQRT, %u, %u, %s, %s, (%s){});",s?"D":"S",q,d,x,x,t));}
        if(!scalar)return unsupported(pc,"vector frecpx");
        return op(cg_format("%s(%u, recpx_%s(c, %s(%u)));",fset(s),d,f,sf,n));
    }
    if(opc==24||opc==25) {
        if(scalar)return unsupported(pc,"scalar frint");
        int rm=-1;
        if(!u)rm=a?((opc&1)?3:1):((opc&1)?2:0);
        else if(!a)rm=(opc&1)?5:4;
        else if(opc&1)rm=6;
        if(rm<0)return unsupported(pc,"frint");
        return vw(t,q,d,cg_format("vfrint_%s(c, %s, %d)",f,x,rm));
    }
    if(opc==26||opc==27||(opc==28&&!a)) {
        unsigned rm=opc==26?a:(opc==27?2+a:4);
        if(scalar)return op(cg_format("c->v[%u] = (%s)toint_%s(c, %s(%u), %u, 0, %u, %u);",d,ut(2+s),f,sf,n,rm,32u<<s,u));
        return vw(fu(s),q,d,cg_format("vtoint_%s(c, %s, %u, 0, %u)",f,x,rm,u));
    }
    if(opc==28) {if(scalar||s)return unsupported(pc,"urecpe");return same(lop(u?"URSQRTE":"URECPE",0),2,lanes(q,2),d,n,-1,0,-1);}
    if(opc==29) {
        if(!a) {
            if(scalar)return op(cg_format("%s(%u, fromint_%s(c, %s(%u), %u, %u, 0));",fset(s),d,f,s?"VS64":"VS32",n,32u<<s,u));
            return vw(t,q,d,cg_format("vfromint_%s(c, %s, 0, %u)",f,vr(fu(s),n),u));
        }
        if(scalar)return op(cg_format("%s(%u, %s_%s(c, %s(%u)));",fset(s),d,u?"rsqrte":"recpe",f,sf,n));
        return vw(t,q,d,cg_format("v%s_%s(c, %s)",u?"rsqrte":"recpe",f,x));
    }
    return unsupported(pc,"fp misc opcode");
}
static Instruction misc(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),s=bits(w,22,2),opc=bits(w,12,5),n=bits(w,5,5),d=bits(w,0,5),ne=scalar?1:lanes(q,s);
    if(opc>=24||opc==22||opc==23||(opc>=12&&opc<=15))return misc_fp(w,pc,scalar);
    if((opc==3||opc==7)&&!scalar&&s==3&&!q)return unsupported(pc,"misc 1d");
    if(opc==3||opc==7)return same(lop(opc==3?(u?"USQADD":"SUQADD"):(u?"SQNEG":"SQABS"),0),s,ne,d,n,-1,0,-1);
    if(scalar) {
        if(opc==18||opc==20) {
            if(s==3||(opc==18&&!u))return unsupported(pc,"scalar xtn");
            return gen(lop(opc==18?"SQXTUN":(u?"UQXTN":"SQXTN"),0),s,1,d,s,0,0,n,s+1,0,-1,0,0,-1,0);
        }
        if(s!=3)return unsupported(pc,"scalar misc size");
        const char *a=cg_format("VS64(%u)",n),*sa=cg_format("(int64_t)VS64(%u)",n);
        if(opc==8||opc==9||(opc==10&&!u))return op(cg_format("c->v[%u] = (%s %s 0) ? ~0ull : 0;",d,sa,opc==8?(u?">=":">"):(opc==9?(u?"<=":"=="):"<")));
        if(opc==11)return op(u?cg_format("c->v[%u] = (uint64_t)-%s;",d,a):cg_format("c->v[%u] = (%s < 0) ? (uint64_t)-%s : %s;",d,sa,a,a));
        return unsupported(pc,"scalar misc opcode");
    }
    const char *t=vu(s),*a=vr(t,n),*sa=vr(vs(s),n);
    if(opc==0||(opc==1&&!u)) {
        unsigned gsz=opc==1?1u:(u?2u:3u);if(s>=gsz)return unsupported(pc,"rev");
        unsigned es=1u<<s,gb=1u<<gsz,idx[16];
        for(unsigned i=0;i<16;i++) {unsigned g=i/gb*gb,o=i%gb,e=o/es,b=o%es;idx[i]=g+(gb/es-1-e)*es+b;}
        return vw("vu8",q,d,shuffle(vr("vu8",n),vr("vu8",n),idx,16));
    }
    if(s==3&&!q&&opc!=18&&opc!=20&&opc!=19)return unsupported(pc,"misc 1d");
    if(opc==2||opc==6) {if(s==3)return unsupported(pc,"addlp size");return op(cg_format("sl_addlp(c, %u, %u, %u, %u, %u, %u);",u,opc==6?1u:0u,q,s,d,n));}
    if(opc==4) {if(s==3)return unsupported(pc,"clz size");return same(lop(u?"CLZ":"CLS",0),s,ne,d,n,-1,0,-1);}
    if(opc==5) {
        if(!u) {if(s)return unsupported(pc,"cnt size");return same(lop("CNT",0),0,ne,d,n,-1,0,-1);}
        if(s==0)return vw("vu64",q,d,cg_format("~%s",vr("vu64",n)));
        if(s==1)return same(lop("RBIT",0),0,lanes(q,0),d,n,-1,0,-1);
        return unsupported(pc,"not/rbit size");
    }
    if(opc==8||opc==9||(opc==10&&!u))return vw(t,q,d,cg_format("(%s)(%s %s 0)",t,sa,opc==8?(u?">=":">"):(opc==9?(u?"<=":"=="):"<")));
    if(opc==11)return vw(t,q,d,u?cg_format("-%s",a):cg_format("((%s)%s ^ (%s)(%s >> %u)) - (%s)(%s >> %u)",t,sa,t,sa,(8u<<s)-1,t,sa,(8u<<s)-1));
    if(opc==18||opc==20) {
        if(s==3)return unsupported(pc,"xtn size");
        unsigned count=8u>>s;return gen(lop(opc==18?(u?"SQXTUN":"XTN"):(u?"UQXTN":"SQXTN"),0),s,count,d,s,q*count,q,n,s+1,0,-1,0,0,-1,0);
    }
    if(opc==19&&u) {if(s==3)return unsupported(pc,"shll size");unsigned count=8u>>s;return gen(lop("SHLL",0),s,count,d,s+1,0,0,n,s,q*count,-1,0,0,-1,0);}
    return unsupported(pc,"misc2 opcode");
}
static Instruction across(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),s=bits(w,22,2),opc=bits(w,12,5),n=bits(w,5,5),d=bits(w,0,5);
    if(scalar) {
        if(!u) {if(opc==27&&s==3)return op(cg_format("c->v[%u] = (uint64_t)(VS64(%u) + VHI64(%u));",d,n,n));return unsupported(pc,"scalar pairwise");}
        const char *o=opc==12?(s>>1?"FOP_MINNM":"FOP_MAXNM"):(opc==13&&!(s>>1)?"FOP_ADD":(opc==15?(s>>1?"FOP_MIN":"FOP_MAX"):NULL));
        if(!o)return unsupported(pc,"scalar fp pairwise");
        return op(cg_format("%s(%u, pair_%s(c, %s, %s[0], %s[1]));",fset(s&1),d,ff(s&1),o,vr(ft(s&1),n),vr(ft(s&1),n)));
    }
    if(opc==12||opc==15) {
        if(!u)return unsupported(pc,"fp16 across");
        if(!q||(s&1))return unsupported(pc,"fp across size");
        return op(cg_format("sv_fred_s(c, %s, %u, %u);",opc==12?(s>>1?"FOP_MINNM":"FOP_MAXNM"):(s>>1?"FOP_MIN":"FOP_MAX"),d,n));
    }
    int o=opc==3?1:(opc==10?2:(opc==26?3:(opc==27?0:-1)));
    if(o<0||(o==0&&u)||s==3||(s==2&&!q))return unsupported(pc,"across");
    return op(cg_format("sl_across(c, %d, %u, %u, %u, %u, %u);",o,u,q,s,d,n));
}
static Instruction shift_immediate(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),ih=bits(w,19,4),ib=bits(w,16,3),opc=bits(w,11,5),n=bits(w,5,5),d=bits(w,0,5);
    if(!ih)return unsupported(pc,"shift immh");
    unsigned s=0;while((ih>>(s+1))!=0)s++;
    unsigned es=8u<<s,imm=(ih<<3)|ib,rsh=2*es-imm,lsh=imm-es;
    if(scalar)q=1;
    unsigned ne=scalar?1:lanes(q,s);
    if(opc==28||opc==31) {
        if(s<2)return unsupported(pc,"fp16 fixed");
        if(s==3&&!q)return unsupported(pc,"fixed 1d");
        unsigned fsz=s-2;const char *f=ff(fsz);
        if(opc==28) {
            if(scalar)return op(cg_format("%s(%u, fromint_%s(c, %s(%u), %u, %u, %u));",fset(fsz),d,f,fsz?"VS64":"VS32",n,es,u,rsh));
            return vw(ft(fsz),q,d,cg_format("vfromint_%s(c, %s, %u, %u)",f,vr(fu(fsz),n),rsh,u));
        }
        if(scalar)return op(cg_format("c->v[%u] = (%s)toint_%s(c, %s(%u), 3, %u, %u, %u);",d,ut(s),f,fs(fsz),n,rsh,es,u));
        return vw(fu(fsz),q,d,cg_format("vtoint_%s(c, %s, 3, %u, %u)",f,vq(ft(fsz),q,n),rsh,u));
    }
    if(opc>=16&&opc<=19) {
        if(s==3)return unsupported(pc,"narrow shift size");
        ne=scalar?1:8u>>s;
        const char *o=opc==16?(u?"QSHRUN":"SHRN"):(opc==17?(u?"QRSHRUN":"RSHRN"):(opc==18?"QSHRN":"QRSHRN"));
        if(scalar&&opc<=17&&!u)return unsupported(pc,"scalar shrn");
        unsigned part=scalar?0:q;
        return gen(lop(o,opc>=18?u:0u),s,ne,d,s,part*ne,part,n,s+1,0,-1,0,0,-1,rsh);
    }
    if(opc==20) {
        if(scalar||s==3)return unsupported(pc,"sshll");
        ne=8u>>s;return gen(lop("SHLLI",u),s,ne,d,s+1,0,0,n,s,q*ne,-1,0,0,-1,lsh);
    }
    if(s==3&&!q)return unsupported(pc,"shift 1d");
    if(scalar&&s!=3&&opc!=12&&opc!=14)return unsupported(pc,"scalar shift size");
    const char *t=vu(s),*e;
    if(opc==0||opc==2) {
        if(u)e=rsh>=es?cg_format("(%s){}",t):cg_format("(%s >> %u)",vr(t,n),rsh);
        else e=cg_format("(%s)(%s >> %u)",t,vr(vs(s),n),rsh<es?rsh:es-1);
        if(opc==2)e=cg_format("%s + %s",vr(t,d),e);
        return scalar?op(cg_format("c->v[%u] = (uint64_t)((%s)[0]);",d,e)):vw(t,q,d,e);
    }
    if(opc==4||opc==6)return same(lop(opc==4?"RSHRI":"RSRAI",u),s,ne,d,n,-1,rsh,-1);
    if(opc==8) {if(!u)return unsupported(pc,"sri U");return same(lop("SRI",0),s,ne,d,n,-1,rsh,-1);}
    if(opc==10) {
        if(u)return same(lop("SLI",0),s,ne,d,n,-1,lsh,-1);
        e=cg_format("%s << %u",vr(t,n),lsh);return scalar?op(cg_format("c->v[%u] = (uint64_t)((%s)[0]);",d,e)):vw(t,q,d,e);
    }
    if(opc==12) {if(!u)return unsupported(pc,"sqshlu U");return same(lop("QSHLUI",0),s,ne,d,n,-1,lsh,-1);}
    if(opc==14)return same(lop("QSHLI",u),s,ne,d,n,-1,lsh,-1);
    return unsupported(pc,"shift imm opcode");
}
static Instruction indexed(uint32_t w,uint64_t pc,bool scalar) {
    unsigned q=bits(w,30,1),u=bits(w,29,1),s=bits(w,22,2),l=bits(w,21,1),mb=bits(w,20,1),rm=bits(w,16,4),opc=bits(w,12,4),h=bits(w,11,1),n=bits(w,5,5),d=bits(w,0,5),idx,m;
    if((opc==1||opc==5||opc==9)&&!(u&&opc!=9)) {
        if(s<2)return unsupported(pc,"fp16 indexed");
        unsigned fsz=s&1;
        if(fsz) {if(l)return unsupported(pc,"indexed L");idx=h;}else idx=(h<<1)|l;
        m=(mb<<4)|rm;if(!scalar&&fsz&&!q)return unsupported(pc,"indexed 2d Q");
        const char *f=ff(fsz),*t=ft(fsz),*sf=fs(fsz),*setf=fset(fsz);
        const char *el=cg_format("%s[%u]",vr(t,m),idx),*mul=u?"FOP_MULX":"FOP_MUL";
        if(scalar) {
            if(opc==9)return op(cg_format("%s(%u, op_%s(c, %s, %s(%u), %s, 0));",setf,d,f,mul,sf,n,el));
            return op(cg_format("%s(%u, op_%s(c, FOP_MADD, %s(%u), %s, %s));",setf,d,f,sf,d,opc==1?cg_format("%s(%u)",sf,n):cg_format("neg_%s(%s(%u))",f,sf,n),el));
        }
        el=cg_format("vsplat_%s(%s, %u, %u)",f,vr(t,m),idx,q);
        if(opc==9)return op(cg_format("SV_FOP_%s(%s, %u, %u, %s, %s, (%s){});",fsz?"D":"S",mul,q,d,vq(t,q,n),el,t));
        return op(cg_format("SV_FOP_%s(FOP_MADD, %u, %u, %s, %s, %s);",fsz?"D":"S",q,d,vq(t,q,d),opc==1?vq(t,q,n):cg_format("vneg_%s(%s)",f,vq(t,q,n)),el));
    }
    if(s==1) {idx=(h<<2)|(l<<1)|mb;m=rm;}else if(s==2) {idx=(h<<1)|l;m=(mb<<4)|rm;}else return unsupported(pc,"indexed size");
    const char *o=opc==3?"SQDMLAL":(opc==7?"SQDMLSL":(opc==11?"SQDMULL":(opc==12?"SQDMULH":(opc==13?"SQRDMULH":NULL))));
    if(scalar) {
        if(u||!o)return unsupported(pc,"scalar indexed");
        return gen(lop(o,0),s,1,d,opc==12||opc==13?s:s+1,0,0,n,s,0,(int)m,s,0,(int)idx,0);
    }
    unsigned ne=lanes(q,s),indexes[16];for(unsigned i=0;i<(16u>>s);i++)indexes[i]=idx;
    const char *t=vu(s),*el=shuffle(vr(t,m),vr(t,m),indexes,16u>>s);
    if(!u&&opc==8)return vw(t,q,d,cg_format("%s * %s",vr(t,n),el));
    if(u&&(opc==0||opc==4))return vw(t,q,d,cg_format("%s %s %s * %s",vr(t,d),opc==0?"+":"-",vr(t,n),el));
    if(!u&&(opc==12||opc==13))return same(lop(o,0),s,ne,d,n,(int)m,0,(int)idx);
    const char *lng=opc==2?"MLAL":(opc==6?"MLSL":(opc==10?"MULL":(opc==3?"SQDMLAL":(opc==7?"SQDMLSL":(opc==11?"SQDMULL":NULL)))));
    if(!lng||(u&&lng[0]=='S'))return unsupported(pc,"indexed opcode");
    ne=8u>>s;return gen(lop(lng,lng[0]=='S'?0u:u),s,ne,d,s+1,0,0,n,s,q*ne,(int)m,s,0,(int)idx,0);
}
Instruction cg_portable_vector(uint32_t w,uint64_t pc) {
    unsigned o=bits(w,28,4),a=bits(w,23,2),b=bits(w,19,4),c=bits(w,10,9);
    if(o==4&&!(a&2)&&(b&7)==5&&(c&387)==2)return crypto(w,pc,0);
    if(o==5&&!(a&2)&&!(b&4)&&!(c&35))return crypto(w,pc,1);
    if(o==5&&!(a&2)&&(b&7)==5&&(c&387)==2)return crypto(w,pc,2);
    if((o&13)==5) {
        if(a==0&&!(b&12)&&(c&33)==1)return copy(w,pc,true);
        if(!(a&2)&&(b&7)==4&&(c&387)==2)return misc(w,pc,true);
        if(!(a&2)&&(b&7)==6&&(c&387)==2)return across(w,pc,true);
        if(!(a&2)&&(b&4)&&!(c&3))return three_diff(w,pc,true);
        if(!(a&2)&&(b&4)&&(c&1))return three_same(w,pc,true);
        if(a==2&&(c&1))return shift_immediate(w,pc,true);
        if((a&2)&&!(c&1))return indexed(w,pc,true);
        return unsupported(pc,cg_format("simd scalar %08x",w));
    }
    if(!(o&11)&&!(a&2)&&!(b&4)&&!(c&35))return permutation(w,pc,2);
    if(!(o&11)&&!(a&2)&&!(b&4)&&(c&35)==2)return permutation(w,pc,0);
    if((o&11)==2&&!(a&2)&&!(b&4)&&!(c&33))return permutation(w,pc,1);
    if(!(o&9)) {
        if(a==0&&!(b&12)&&(c&33)==1)return copy(w,pc,false);
        if(!(a&2)&&(b&4)&&(c&1))return three_same(w,pc,false);
        if(!(a&2)&&(b&4)&&!(c&3))return three_diff(w,pc,false);
        if(!(a&2)&&(b&7)==4&&(c&387)==2)return misc(w,pc,false);
        if(!(a&2)&&(b&7)==6&&(c&387)==2)return across(w,pc,false);
        if(a==2&&!b&&(c&1))return modified_immediate(w,pc);
        if(a==2&&b&&(c&1))return shift_immediate(w,pc,false);
        if((a&2)&&!(c&1))return indexed(w,pc,false);
        return unsupported(pc,cg_format("simd vector %08x",w));
    }
    return unsupported(pc,cg_format("fp/simd %08x",w));
}
