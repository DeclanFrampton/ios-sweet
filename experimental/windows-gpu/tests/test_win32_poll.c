#include <assert.h>
#include "qemu/win32-poll-limit.h"
int main(void) {
 assert(qemu_win32_poll_limit_ns(-1,16)==16000000);
 assert(qemu_win32_poll_limit_ns(301987000000LL,16)==16000000);
 assert(qemu_win32_poll_limit_ns(0,16)==0);
 assert(qemu_win32_poll_limit_ns(1000000,16)==1000000);
 assert(qemu_win32_poll_limit_ns(16000000,16)==16000000);
 assert(qemu_win32_poll_limit_ns(-1,0)==-1);
 assert(qemu_win32_poll_limit_ns(301987000000LL,0)==301987000000LL);
 return 0;
}
