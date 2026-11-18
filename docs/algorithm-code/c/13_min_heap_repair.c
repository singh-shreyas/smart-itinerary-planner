/* Repair: while the chosen stops cannot be routed, pop the weakest (least value per minute)
   from a min-heap and drop it. The selector and route check are small stand-ins here. */
#include <stdio.h>

#define K 4
typedef struct { double key; int score, id; } Entry;

int less(Entry a, Entry b) {                        /* order: key, then score, then id */
    if (a.key != b.key) return a.key < b.key;
    if (a.score != b.score) return a.score < b.score;
    return a.id < b.id;
}

void sift_down(Entry *h, int n, int i) {
    for (;;) {
        int l = 2 * i + 1, r = l + 1, m = i;
        if (l < n && less(h[l], h[m])) m = l;
        if (r < n && less(h[r], h[m])) m = r;
        if (m == i) return;
        Entry t = h[i]; h[i] = h[m]; h[m] = t; i = m;
    }
}

int main(void) {
    int ids[K] = {1, 2, 3, 4}, score[] = {0, 80, 45, 70, 60}, minutes[] = {0, 90, 120, 60, 60};
    int alive[K] = {1, 1, 1, 1}, budget = 240;
    for (;;) {
        int used = 0, n = 0;
        Entry heap[K];
        for (int i = 0; i < K; i++) if (alive[i]) {           /* stand-in selector: take all */
            used += minutes[ids[i]];
            heap[n++] = (Entry){(double)score[ids[i]] / minutes[ids[i]], score[ids[i]], ids[i]};
        }
        if (n == 0 || used <= budget) break;                  /* stand-in route check */
        for (int i = n / 2 - 1; i >= 0; i--) sift_down(heap, n, i);   /* heapify, O(k) */
        int victim = heap[0].id;                              /* weakest on top */
        printf("drop %d\n", victim);
        for (int i = 0; i < K; i++) if (ids[i] == victim) alive[i] = 0;
    }
    printf("keep:");
    for (int i = 0; i < K; i++) if (alive[i]) printf(" %d", ids[i]);
    printf("\n");
    return 0;
}
