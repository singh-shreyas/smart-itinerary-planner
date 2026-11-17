/* Window-first route: take stops by closing time, insert each at its cheapest feasible position.
   The feasibility check is a small stand-in for the project's minute-by-minute scheduler. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define N 5
const int DIST[N][N] = {{0,12,20,25,15},{11,0,9,18,22},{21,8,0,7,16},{24,19,6,0,10},{14,23,17,9,0}};
const int VISIT[N]  = {0, 60, 90, 45, 60};
const int CLOSES[N] = {0, 13*60, 17*60, 12*60, 18*60};
#define DAY_START (9*60)

int tour_cost(const int *r, int k) {
    if (k == 0) return 0;
    int t = DIST[0][r[0]];
    for (int i = 0; i + 1 < k; i++) t += DIST[r[i]][r[i + 1]];
    return t + DIST[r[k - 1]][0];
}

int feasible(const int *r, int k) {
    int clock = DAY_START, here = 0;
    for (int i = 0; i < k; i++) {
        clock += DIST[here][r[i]] + VISIT[r[i]];
        if (clock > CLOSES[r[i]]) return 0;
        here = r[i];
    }
    return 1;
}

/* inserts stop into route (length *k) at the cheapest feasible position; 0 if none */
int cheapest_feasible_insertion(int *route, int *k, int stop) {
    int best_cost = -1, best_pos = -1, cand[N];
    for (int pos = 0; pos <= *k; pos++) {
        memcpy(cand, route, (size_t)pos * sizeof(int));
        cand[pos] = stop;
        memcpy(cand + pos + 1, route + pos, (size_t)(*k - pos) * sizeof(int));
        if (!feasible(cand, *k + 1)) continue;
        int c = tour_cost(cand, *k + 1);
        if (best_cost == -1 || c < best_cost) { best_cost = c; best_pos = pos; }  /* ties: earlier */
    }
    if (best_pos == -1) return 0;
    memmove(route + best_pos + 1, route + best_pos, (size_t)(*k - best_pos) * sizeof(int));
    route[best_pos] = stop; (*k)++;
    return 1;
}

int by_closing(const void *a, const void *b) {
    int x = *(const int *)a, y = *(const int *)b;
    return CLOSES[x] != CLOSES[y] ? CLOSES[x] - CLOSES[y] : x - y;
}

int main(void) {
    int stops[] = {1, 2, 3, 4}, route[N], k = 0;
    qsort(stops, 4, sizeof(int), by_closing);
    printf("unplaced:");
    for (int i = 0; i < 4; i++)
        if (!cheapest_feasible_insertion(route, &k, stops[i])) printf(" %d", stops[i]);
    printf("\nroute:");
    for (int i = 0; i < k; i++) printf(" %d", route[i]);
    printf("  travel %d\n", tour_cost(route, k));
    return 0;
}
