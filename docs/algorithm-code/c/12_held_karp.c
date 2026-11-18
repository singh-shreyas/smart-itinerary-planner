/* Held-Karp: exact shortest closed tour by DP over subsets of stops (bitmasks). */
#include <stdio.h>
#include <limits.h>

#define N 5
#define K 4
const int DIST[N][N] = {{0,12,20,25,15},{11,0,9,18,22},{21,8,0,7,16},{24,19,6,0,10},{14,23,17,9,0}};
#define INF INT_MAX

int main(void) {
    int start = 0, stops[K] = {1, 2, 3, 4};
    int full = (1 << K) - 1;
    static int dp[1 << K][K], parent[1 << K][K];
    for (int m = 0; m <= full; m++)
        for (int j = 0; j < K; j++) { dp[m][j] = INF; parent[m][j] = -1; }
    for (int j = 0; j < K; j++) dp[1 << j][j] = DIST[start][stops[j]];

    for (int mask = 1; mask <= full; mask++)
        for (int j = 0; j < K; j++) {
            if (!(mask & (1 << j)) || dp[mask][j] == INF) continue;
            for (int nx = 0; nx < K; nx++) {
                if (mask & (1 << nx)) continue;
                int nm = mask | (1 << nx), c = dp[mask][j] + DIST[stops[j]][stops[nx]];
                if (c < dp[nm][nx]) { dp[nm][nx] = c; parent[nm][nx] = j; }
            }
        }

    int best = INF, last = -1;
    for (int j = 0; j < K; j++) {
        if (dp[full][j] == INF) continue;
        int c = dp[full][j] + DIST[stops[j]][start];
        if (c < best) { best = c; last = j; }
    }
    int order[K], len = 0, mask = full;
    while (last != -1) {                                   /* follow parents back */
        order[len++] = stops[last];
        int p = parent[mask][last];
        mask ^= 1 << last;
        last = p;
    }
    printf("cost %d, order:", best);
    for (int i = len - 1; i >= 0; i--) printf(" %d", order[i]);
    printf("\n");
    return 0;
}
