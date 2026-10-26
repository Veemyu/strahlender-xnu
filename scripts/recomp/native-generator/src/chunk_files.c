/* SPDX-License-Identifier: MIT. Remove only the module's obsolete generated chunks. */
#include "codegen.h"
#include <string.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dirent.h>
#include <unistd.h>
#endif
static bool chunk_name(const char *name,const char *module) {
    size_t prefix=strlen(module);if(strncmp(name,module,prefix)||name[prefix]!='_')return false;
    const char *p=name+prefix+1,*start=p;
    while(*p>='0'&&*p<='9')p++;
    if(p-start==3&&!strcmp(p,".c"))return true;
    p=start;for(unsigned i=0;i<5;i++) {char c=*p++;if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;}
    if(*p++!='_')return false;start=p;while(*p>='0'&&*p<='9')p++;
    return p!=start&&!strcmp(p,".c");
}
static bool kept(const Strings *written,const char *name) {
    size_t lo=0,hi=written->size;
    while(lo<hi) {size_t mid=lo+(hi-lo)/2;if(strcmp(written->items[mid],name)<0)lo=mid+1;else hi=mid;}
    return lo<written->size&&!strcmp(written->items[lo],name);
}
#ifdef _WIN32
static wchar_t *wide(const char *text) {
    int length=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,-1,NULL,0);
    if(!length)cg_fail(5,"invalid Unicode output path");
    wchar_t *out=cg_alloc((size_t)length,sizeof(*out));MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,-1,out,length);return out;
}
#endif
void cg_prune_chunks(const char *directory,const char *module,const Strings *written) {
#ifdef _WIN32
    WIN32_FIND_DATAW data;HANDLE search=FindFirstFileW(wide(cg_join(directory,"*")),&data);
    if(search==INVALID_HANDLE_VALUE)cg_fail(5,"cannot list generated chunk folder");
    do {
        int size=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,data.cFileName,-1,NULL,0,NULL,NULL);
        if(!size)continue;char *name=cg_alloc((size_t)size,1);WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,data.cFileName,-1,name,size,NULL,NULL);
        if(chunk_name(name,module)&&!kept(written,name)&&!DeleteFileW(wide(cg_join(directory,name))))cg_fail(5,"cannot remove stale generated chunk");
    }while(FindNextFileW(search,&data));FindClose(search);
#else
    DIR *folder=opendir(directory);if(!folder)cg_fail(5,"cannot list generated chunk folder");
    struct dirent *entry;
    while((entry=readdir(folder)))if(chunk_name(entry->d_name,module)&&!kept(written,entry->d_name))
        if(unlink(cg_join(directory,entry->d_name)))cg_fail(5,"cannot remove stale generated chunk");
    closedir(folder);
#endif
}
