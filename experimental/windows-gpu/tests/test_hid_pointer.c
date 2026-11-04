#include <stdbool.h>
#include <assert.h>
#include "hw/input/hid-pointer-compress.h"
struct Event { int buttons, y; };
static void gesture(unsigned head) {
    struct Event q[16] = {{0}};
    unsigned n = 0;
    const struct Event input[] = {{1,1000},{1,800},{1,500},{0,500}};
    for (unsigned i=0; i<4; i++) {
        unsigned prev=(head+n-1)&15, preceding=(head+n-2)&15;
        if (hid_pointer_can_compress(true,n,input[i].buttons,q[prev].buttons,q[preceding].buttons)) {
            q[prev]=input[i];
        } else { q[(head+n)&15]=input[i]; n++; }
    }
    assert(n==3);
    assert(q[head].buttons==1 && q[head].y==1000); /* original finger-down */
    assert(q[(head+1)&15].buttons==1 && q[(head+1)&15].y==500);
    assert(q[(head+2)&15].buttons==0 && q[(head+2)&15].y==500);
}
int main(void) {
    for(unsigned h=0; h<16; h++) gesture(h);
    assert(!hid_pointer_can_compress(true,0,0,0,0));
    assert(!hid_pointer_can_compress(true,1,1,1,0));
    assert(hid_pointer_can_compress(true,2,1,1,1));
    assert(!hid_pointer_can_compress(true,1,0,0,1));
    assert(!hid_pointer_can_compress(true,1,0,1,0));
    assert(hid_pointer_can_compress(false,1,1,1,0)); /* relative mice unchanged */
    return 0;
}
