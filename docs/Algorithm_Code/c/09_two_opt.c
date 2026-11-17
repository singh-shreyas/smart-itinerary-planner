/* 2-opt: reverse a segment whenever that shortens the closed tour; repeat until no move helps. */
#include <stdio.h>
#include <string.h>

#define N 5
const int DIST[N][N] = {{0,12,20,25,15},{11,0,9,18,22},{21,8,0,7,16},{24,19,6,0,10},{14,23,17,9,0}};

int tour_cost(int start, const int *r, int k) {
    int total = DIST[start][r[0]];
    for (int i = 0; i + 1 < k; i++) total += DIST[r[i]][r[i + 1]];
    return total + DIST[r[k - 1]][start];
}

int two_opt(int start, int *route, int k) {
    int best = tour_cost(start, route, k), cand[N], improved = 1;
    while (improved) {
        improved = 0;
        for (int i = 0; i < k - 1; i++)
            for (int j = i + 1; j < k; j++) {
                memcpy(cand, route, (size_t)k * sizeof(int));
                for (int a = i, b = j; a < b; a++, b--) { int t = cand[a]; cand[a] = cand[b]; cand[b] = t; }
                int c = tour_cost(start, cand, k);          /* full re-cost: the table is directed */
                if (c < best) { memcpy(route, cand, (size_t)k * sizeof(int)); best = c; improved = 1; }
            }
    }
    return best;
}

int main(void) {
    int route[] = {4, 3, 1, 2};
    printf("before: %d\n", tour_cost(0, route, 4));
    int cost = two_opt(0, route, 4);
    printf("after:  ");
    for (int i = 0; i < 4; i++) printf("%d ", route[i]);
    printf(" cost %d\n", cost);
    return 0;
}
