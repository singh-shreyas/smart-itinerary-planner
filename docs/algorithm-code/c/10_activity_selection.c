/* Activity selection (earliest finish first), and stops ordered by closing time. */
#include <stdio.h>
#include <stdlib.h>

typedef struct { char id; int start, finish; } Activity;

int by_finish(const void *pa, const void *pb) {
    const Activity *a = pa, *b = pb;
    if (a->finish != b->finish) return a->finish - b->finish;
    if (a->start != b->start) return a->start - b->start;
    return a->id - b->id;
}

typedef struct { int id, closes; } Stop;
int by_closing(const void *pa, const void *pb) {
    const Stop *a = pa, *b = pb;
    return a->closes != b->closes ? a->closes - b->closes : a->id - b->id;
}

int main(void) {
    Activity act[] = {{'a',9,11},{'b',10,12},{'c',11,13},{'d',12,14},{'e',13,15}};
    qsort(act, 5, sizeof *act, by_finish);
    int last = -1;
    printf("chosen:");
    for (int i = 0; i < 5; i++)
        if (act[i].start >= last) { printf(" %c", act[i].id); last = act[i].finish; }
    printf("\n");

    Stop stops[] = {{1, 18*60}, {2, 17*60}, {3, 21*60}, {4, 17*60}};
    qsort(stops, 4, sizeof *stops, by_closing);
    printf("closing order:");
    for (int i = 0; i < 4; i++) printf(" %d", stops[i].id);
    printf("\n");
    return 0;
}
